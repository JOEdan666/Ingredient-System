"""Page flow on synthetic data (Django test client, SQLite).

Checks that pages call the domain layer, show the simulated-persistence
notice, and that the order-history page answers A09's questions.
"""
import re
import uuid

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from pathlib import Path

from inventory import domain
from inventory.models import Allocation, Order, ReceiptNoticeLine, StockBalance
from inventory.synthetic import load_synthetic_fixture

BANNER = "数据只存在这台电脑"
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


@pytest.mark.parametrize("name", ["inventory", "import_preview", "receiving", "outbound", "history"])
def test_every_page_shows_simulation_notice(client, loaded, name):
    resp = client.get(reverse(name))
    assert resp.status_code == 200
    assert BANNER in resp.content.decode()


def test_real_format_upload_shows_summary_without_writing_inventory(client, loaded):
    fixture = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic" / "real-format" / "stock_export_synthetic.xlsx"
    before = StockBalance.objects.count()
    upload = SimpleUploadedFile("stock.xlsx", fixture.read_bytes(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response = client.post(reverse("import_preview"), {"owner_new": "PREVIEW-OWNER", "file": upload}, follow=True)
    html = response.content.decode()
    assert response.status_code == 200
    assert "读出行数" in html and "确认入账" in html
    assert StockBalance.objects.count() == before


def test_import_rejects_unsupported_file_type(client, loaded):
    upload = SimpleUploadedFile("wrong.csv", b"a,b", content_type="text/csv")
    response = client.post(reverse("import_preview"), {"owner_new": "PREVIEW-OWNER", "file": upload})
    assert "只支持 .xlsx 表格和 .pdf 送货单" in response.content.decode()


def test_import_reports_broken_pdf_instead_of_returning_500(client, loaded):
    upload = SimpleUploadedFile("broken.pdf", b"not a pdf", content_type="application/pdf")
    response = client.post(reverse("import_preview"), {"owner_new": "PREVIEW-OWNER", "file": upload})
    assert response.status_code == 200
    assert "文件读不出来" in response.content.decode()


def test_inventory_defaults_to_available_with_expandable_detail(client, loaded):
    html = client.get(reverse("inventory"), {"owner": "DEMO-OWNER-A"}).content.decode()
    # owner A: sellable 14 (A-01 6 + B-01 8), pending 3 is not sellable.
    assert re.search(r'class="pavail"><b>14</b>', html)
    assert '<details class="prod">' in html and "不可售" in html  # detail folded by default


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
    assert f'name="pick_{line.pk}_{a01.pk}"' in page and f'_{pending.pk}"' not in page  # pending not offered

    resp = post(client, "allocate", {f"pick_{line.pk}_{a01.pk}": "6", f"pick_{line.pk}_{b01.pk}": "4"},
                order_id=order.pk)
    assert "分配已保存：1 行，共 10 件" in resp.content.decode()
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


# --- Review fixes (2026-09-28): tampered forms must be rejected, not act on another order or crash ---

def _two_orders(client):
    post(client, "accept_order", {"owner": "DEMO-OWNER-A", "number": "SYN-O-X", "product_1": "000123", "qty_1": "1"})
    post(client, "accept_order", {"owner": "DEMO-OWNER-A", "number": "SYN-O-Y", "product_1": "000123", "qty_1": "1"})
    return Order.objects.get(number="SYN-O-X"), Order.objects.get(number="SYN-O-Y")


def test_cancel_with_line_of_another_order_is_rejected(client, loaded):
    order_x, order_y = _two_orders(client)
    line_y = order_y.lines.get()
    resp = post(client, "cancel_line", {"line_id": line_y.pk, "qty": "1", "reason": "UNPAID"}, order_id=order_x.pk)
    assert "不属于当前订单" in resp.content.decode()
    line_y.refresh_from_db()
    assert line_y.qty_cancelled == 0


def test_allocate_with_line_of_another_order_is_rejected(client, loaded):
    order_x, order_y = _two_orders(client)
    line_y = order_y.lines.get()
    a01 = StockBalance.objects.get(location__code="A-01", owner__code="DEMO-OWNER-A")
    resp = post(client, "allocate", {f"pick_{line_y.pk}_{a01.pk}": "1"}, order_id=order_x.pk)
    assert "不属于这张订单" in resp.content.decode()
    assert not Allocation.objects.filter(order_line=line_y).exists()


def test_non_numeric_ship_id_is_rejected_not_500(client, loaded):
    order_x, _ = _two_orders(client)
    resp = post(client, "ship", {"ship_abc": "1"}, order_id=order_x.pk)
    assert resp.status_code == 400
    assert "不属于这张订单" in resp.content.decode()


@pytest.mark.parametrize("field_fmt, value, text", [
    ("pick_abc", "1", "一个数量都没填"),               # malformed key: ignored, nothing to save
    ("pick_{line}_{bal}", "abc", "分配数量必须是 0 或正整数"),  # malformed quantity
])
def test_bad_allocation_input_is_refused_not_500(client, loaded, field_fmt, value, text):
    order_x, _ = _two_orders(client)
    line = order_x.lines.get()
    a01 = StockBalance.objects.get(location__code="A-01", owner__code="DEMO-OWNER-A")
    resp = post(client, "allocate", {field_fmt.format(line=line.pk, bal=a01.pk): value}, order_id=order_x.pk)
    assert resp.status_code == 400 and text in resp.content.decode()
    assert not Allocation.objects.filter(order_line=line).exists()
