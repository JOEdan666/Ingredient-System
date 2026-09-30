"""T11: an unexpected failure shows a code and leaves a record with no business data; refusals do not."""
import re

import pytest
from django.urls import reverse

from inventory import domain, errors, queries
from inventory.models import ErrorLog, Order, StockBalance

from .conftest import ACTOR, new_op

SECRET = "SECRET-客户甲-000777-99件"


def boom(*a, **k):
    raise RuntimeError(f"cannot read {SECRET}")


def test_unexpected_error_shows_code_and_writes_a_record_without_the_message(client, world, monkeypatch):
    monkeypatch.setattr(queries, "product_summaries", boom)
    resp = client.get(reverse("inventory") + f"?product={SECRET}")
    html = resp.content.decode()
    assert resp.status_code == 500 and "这一步没有成功" in html and "可能没有完成，也可能已经完成" in html and "没有保存" not in html
    code = re.search(r"E-[0-9A-F]{8}", html).group(0)
    row = ErrorLog.objects.get()
    assert row.code == code and row.method == "GET" and row.path == "/" and row.error_type == "RuntimeError"
    assert re.fullmatch(r"views\.py:\d+ inventory_page", row.location)  # innermost frame of our own code
    stored = " ".join(str(getattr(row, f.name)) for f in ErrorLog._meta.fields)
    assert SECRET not in stored and "000777" not in stored  # neither the message nor the query string
    assert SECRET not in html  # and the employee's screen does not echo it either


def test_error_page_lists_the_record_and_the_code_can_be_searched(client, world, monkeypatch):
    monkeypatch.setattr(queries, "product_summaries", boom)
    code = re.search(r"E-[0-9A-F]{8}", client.get(reverse("inventory")).content.decode()).group(0)
    monkeypatch.undo()
    page = client.get(reverse("errors")).content.decode()
    assert code in page and "RuntimeError" in page and "不含商品、客户、数量" in page
    assert code in client.get(reverse("errors"), {"code": code[2:6].lower()}).content.decode()
    assert "没有找到这个编号" in client.get(reverse("errors"), {"code": "E-00000000"}).content.decode()


def test_refusals_and_unknown_pages_are_not_errors(client, world):
    a = world.opening(10)
    res = world.accept("SYN-ERR-1", 3)
    domain.allocate_line(operation_id=new_op(), actor=ACTOR, line_id=world.line_id(res), picks=[{"balance_id": a.pk, "qty": 3}])
    order = Order.objects.get(number="SYN-ERR-1")
    alloc = order.lines.get().allocations.get()
    over = client.post(reverse("ship", args=[order.pk]), {"actor": "员工甲（合成）", "operation_id": "e-1", f"ship_{alloc.pk}": "9"})
    assert over.status_code == 400 and "多发了" in over.content.decode()
    assert client.get(reverse("order_detail", args=[99999])).status_code == 404
    assert client.get("/no-such-page/").status_code == 404
    assert ErrorLog.objects.count() == 0
    assert "还没有错误记录" in client.get(reverse("errors")).content.decode()


def test_an_error_in_a_post_is_logged_as_post_and_changes_nothing(client, world, monkeypatch):
    a = world.opening(10)
    monkeypatch.setattr(domain, "move_stock", boom)
    before = StockBalance.objects.get(pk=a.pk).on_hand
    resp = client.post(reverse("move"), {"actor": "员工甲（合成）", "operation_id": "e-2", "balance_id": a.pk, "qty": 1, "to_location": "B-01"})
    assert resp.status_code == 500 and ErrorLog.objects.get().method == "POST"
    assert StockBalance.objects.get(pk=a.pk).on_hand == before


def test_a_failing_log_never_hides_the_friendly_page(client, world, monkeypatch):
    monkeypatch.setattr(queries, "product_summaries", boom)
    monkeypatch.setattr(ErrorLog.objects, "create", boom)
    resp = client.get(reverse("inventory"))
    html = resp.content.decode()
    assert resp.status_code == 500 and "这一步没有成功" in html and "连错误记录也没能保存" in html


def test_only_the_newest_rows_are_kept(db, rf, monkeypatch):
    monkeypatch.setattr(errors, "KEEP", 5)
    request = rf.get("/x/")
    codes = [errors.record(request, ValueError("x")) for _ in range(8)]
    assert ErrorLog.objects.count() == 5 and set(ErrorLog.objects.values_list("code", flat=True)) == set(codes[-5:])


def test_nav_has_the_link(client, db):
    assert reverse("errors") in client.get(reverse("inventory")).content.decode()
