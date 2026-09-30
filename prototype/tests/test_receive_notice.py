"""Whole-notice receipt (整张验货纸一次确认实收). One test per line of the approved acceptance sheet."""
import pytest
from django.urls import reverse

from inventory import domain
from inventory.models import ReceiptLine, StockBalance, StockMovement

from .conftest import ACTOR, new_op

DEMO_ACTOR = "员工甲（合成）"


@pytest.fixture
def notice(world):
    res = domain.create_notice(operation_id=new_op(), actor=ACTOR, owner_code="SYN-OWNER-A", number="SYN-ASN-9",
                               lines=[{"product": "000777", "qty": 10, "expiry": "2027-09-02"},
                                      {"product": "000777", "qty": 20, "expiry": None},
                                      {"product": "000777", "qty": 5, "expiry": None}])
    notice_id = res.result["notice_id"]
    line_ids = list(domain.ReceiptNotice.objects.get(pk=notice_id).lines.order_by("line_no").values_list("pk", flat=True))
    return notice_id, line_ids


def post(client, notice_id, line_ids, qtys, **extra):
    data = {"actor": DEMO_ACTOR, "operation_id": "x", "default_location": "A-01", "condition": "AVAILABLE", **extra}
    for lid, q in zip(line_ids, qtys):
        data[f"qty_{lid}"] = str(q)
    return client.post(reverse("receive_notice", args=[notice_id]), data, follow=True)


def on_hand():
    return sum(b.on_hand for b in StockBalance.objects.all())


def test_1_notice_is_folded_to_a_summary_line(client, notice):
    html = client.get(reverse("receiving")).content.decode()
    assert "SYN-ASN-9" in html and "3 行" in html and "共 35 件" in html and "未收货" in html
    assert '<details class="card notice">' in html  # closed by default


def test_2_3_matching_rows_fold_and_differences_open_red(client, notice):
    html = client.get(reverse("receiving")).content.decode()
    assert "3 行与预计一致（已折叠" in html  # every row prefilled with expected quantity
    notice_id, ids = notice
    html = post(client, notice_id, ids, [10, 20, "-1"]).content.decode()  # one bad row -> page re-rendered
    assert "2 行与预计一致（已折叠" in html and 'class="rrow err"' in html


def test_4_one_click_posts_every_line_and_stock_goes_up(client, notice):
    notice_id, ids = notice
    before = on_hand()
    html = post(client, notice_id, ids, [10, 18, 0]).content.decode()
    assert "整张单已入库：2 行，共 28 件" in html and "1 行实收为 0" in html
    assert on_hand() == before + 28
    assert ReceiptLine.objects.count() == 2
    assert "已收货" in html


def test_5_bad_row_writes_nothing_keeps_values_and_names_the_row(client, notice):
    notice_id, ids = notice
    before = (on_hand(), StockMovement.objects.count())
    resp = post(client, notice_id, ids, [10, 17, "abc"], default_location="")
    html = resp.content.decode()
    assert resp.status_code == 400 and "整张单没有入库" in html
    assert "实收数量必须是 0 或正整数" in html  # row 3
    assert "没有选货位" in html  # rows 1-2 have quantities but no location anywhere
    assert f'name="qty_{ids[1]}" value="17"' in html  # typed values kept
    assert (on_hand(), StockMovement.objects.count()) == before


def test_row_location_overrides_the_shared_one(client, notice):
    notice_id, ids = notice
    post(client, notice_id, ids, [10, 20, 5], **{f"loc_{ids[2]}": "B-01"})
    locs = sorted(ReceiptLine.objects.values_list("location_code", flat=True))
    assert locs == ["A-01", "A-01", "B-01"]


def test_6_same_notice_cannot_be_received_twice(client, notice):
    notice_id, ids = notice
    post(client, notice_id, ids, [10, 20, 5])
    before = on_hand()
    html = post(client, notice_id, ids, [10, 20, 5]).content.decode()
    assert "已经收过货了" in html and on_hand() == before


def test_all_zero_is_refused(client, notice):
    notice_id, ids = notice
    html = post(client, notice_id, ids, [0, 0, 0]).content.decode()
    assert "没有东西可以入库" in html and ReceiptLine.objects.count() == 0


def test_failure_on_a_later_line_undoes_earlier_lines(client, notice, monkeypatch):
    notice_id, ids = notice
    real = domain.confirm_receipt

    def flaky(**kw):
        if kw["notice_line_id"] == ids[2]:
            raise domain.DomainError("boom", "模拟第 3 行入库失败")
        return real(**kw)

    monkeypatch.setattr("inventory.receiving_batch.domain.confirm_receipt", flaky)
    before = on_hand()
    html = post(client, notice_id, ids, [10, 20, 5]).content.decode()
    assert "模拟第 3 行入库失败" in html and on_hand() == before and ReceiptLine.objects.count() == 0
