"""Page flow on synthetic data (Django test client, SQLite).

Checks that pages call the domain layer, show the simulated-persistence
notice, and that the order-history page answers A09's questions.
"""
import re
import uuid

import pytest
from django.urls import reverse

from inventory import domain
from inventory.models import Allocation, Order, ReceiptNoticeLine, StockBalance
from inventory.synthetic import load_synthetic_fixture

BANNER = "模拟持久化（本机 SQLite），不证明并发和锁"
ACTOR = "员工甲（合成）"


@pytest.fixture
def loaded(db):
    load_synthetic_fixture()
    yield
    assert domain.check_invariants() == []


def post(client, name, data, **kwargs):
    data = {"operation_id": data.pop("operation_id", None) or f"page-{name}-{uuid.uuid4().hex}",
            "actor": ACTOR, **data}
    return client.post(reverse(name, kwargs=kwargs or None), data, follow=True)


@pytest.mark.parametrize("name", ["inventory", "receiving", "outbound", "history"])
def test_every_page_shows_simulation_notice(client, loaded, name):
    resp = client.get(reverse(name))
    assert resp.status_code == 200
    assert BANNER in resp.content.decode()


def test_inventory_defaults_to_available_with_expandable_detail(client, loaded):
    html = client.get(reverse("inventory"), {"owner": "DEMO-OWNER-A"}).content.decode()
    # owner A: sellable 14 (A-01 6 + B-01 8), pending 3 is not sellable.
    assert re.search(r'class="num big">14 ', html)
    assert "展开实物 / 占用" in html and "不可售" in html


def test_full_outbound_flow_and_history(client, loaded):
    resp = post(client, "accept_order", {"owner": "DEMO-OWNER-A", "number": "DEMO-O1", "source_ref": "SYN-PDF-1 p1",
                                         "product_1": "000123", "qty_1": "10", "expiry_1": "2027-09-02"})
    assert "接单完成" in resp.content.decode()
    order = Order.objects.get(number="DEMO-O1")
    line = order.lines.get()
    a01 = StockBalance.objects.get(owner__code="DEMO-OWNER-A", location__code="A-01")
    b01 = StockBalance.objects.get(owner__code="DEMO-OWNER-A", location__code="B-01")
    pending = StockBalance.objects.get(owner__code="DEMO-OWNER-A", condition="PENDING_INSPECTION")

    page = client.get(reverse("order_detail", kwargs={"order_id": order.pk})).content.decode()
    assert f'name="pick_{a01.pk}"' in page and f'name="pick_{pending.pk}"' not in page  # pending not offered

    resp = post(client, "allocate", {"line_id": line.pk, f"pick_{a01.pk}": "6", f"pick_{b01.pk}": "4"},
                order_id=order.pk)
    assert "分配批次/货位完成" in resp.content.decode()
    items = {f"ship_{a.pk}": str(a.qty_open) for a in Allocation.objects.filter(order_line=line)}
    resp = post(client, "ship", items, order_id=order.pk)
    assert "发货完成" in resp.content.decode()

    html = client.get(reverse("history"), {"number": "DEMO-O1"}).content.decode()
    for text in ("2027-09-02", "A-01", "B-01", ACTOR, "SYN-PDF-1 p1", "实物发出（库存流水）"):
        assert text in html


def test_double_submit_same_form_is_replayed_not_repeated(client, loaded):
    data = {"operation_id": "page-dup-1", "owner": "DEMO-OWNER-A", "number": "SYN-O-DUP",
            "product_1": "000123", "qty_1": "2"}
    post(client, "accept_order", dict(data))
    resp = post(client, "accept_order", dict(data))
    assert "已返回第一次的结果" in resp.content.decode()
    assert Order.objects.filter(number="SYN-O-DUP").count() == 1


def test_rejection_is_shown_and_writes_nothing(client, loaded):
    resp = post(client, "accept_order", {"owner": "DEMO-OWNER-A", "number": "SYN-O-BIG",
                                         "product_1": "000123", "qty_1": "999"})
    assert "接单被拒绝" in resp.content.decode()
    assert not Order.objects.filter(number="SYN-O-BIG").exists()


def test_receiving_flow_notice_receipt_inspection(client, loaded):
    post(client, "create_notice", {"owner": "DEMO-OWNER-A", "number": "SYN-ASN-9",
                                   "product_1": "000123", "qty_1": "10", "expiry_1": "2028-03-01"})
    nline = ReceiptNoticeLine.objects.get(notice__number="SYN-ASN-9")
    before = sum(b.on_hand for b in StockBalance.objects.filter(owner__code="DEMO-OWNER-A"))
    assert before == 17  # notice added nothing (6 + 8 + 3)
    resp = post(client, "confirm_receipt", {"notice_line_id": nline.pk, "qty": "8", "expiry": "2028-03-01",
                                            "external_lot": "", "location": "RECEIVING",
                                            "condition": "PENDING_INSPECTION"})
    assert "实收完成" in resp.content.decode()
    new = StockBalance.objects.get(lot__expiry_date="2028-03-01")
    assert new.condition == "PENDING_INSPECTION"
    resp = post(client, "change_condition", {"balance_id": new.pk, "qty": "8", "to_condition": "AVAILABLE"})
    assert "改状态完成" in resp.content.decode()
    assert StockBalance.objects.get(lot__expiry_date="2028-03-01", condition="AVAILABLE").on_hand == 8
