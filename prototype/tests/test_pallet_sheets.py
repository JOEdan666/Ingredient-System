"""Pallet header sheets (板头纸): generated from orders, one page per pallet, never touching stock."""
import re

import pytest
from django.urls import reverse

from inventory import pallet_sheets
from inventory.domain import DomainError
from inventory.models import (
    Allocation, Order, PalletSheet, ProductAvailability, ReservationEntry, StockBalance, StockMovement,
)

ACTOR = "员工甲（合成）"
FORM = {"ship_to": "合成客戶 甲", "address": "合成地址 1 號", "delivery_time": "下午3時前", "pallet_count": "3",
        "actor": ACTOR, "operation_id": "x"}


def stock_state():
    return (list(StockBalance.objects.values_list("pk", "on_hand", "allocated").order_by("pk")),
            list(ProductAvailability.objects.values_list("pk", "sellable", "reserved").order_by("pk")),
            StockMovement.objects.count(), ReservationEntry.objects.count(), Allocation.objects.count())


@pytest.fixture
def two_orders(world):
    world.opening(20)
    a = world.accept("SYN-ORD-B", 2).result["order_id"]
    b = world.accept("SYN-ORD-A", 3).result["order_id"]
    return a, b


def test_order_page_offers_sheet_and_generated_pages_follow_sample_layout(client, two_orders):
    a, b = two_orders
    assert "打印板头纸" in client.get(reverse("order_detail", args=[a])).content.decode()
    before = stock_state()
    resp = client.post(reverse("pallet_sheet_form", args=[a]), {**FORM, "orders": [a, b]}, follow=True)
    html = resp.content.decode()
    assert resp.redirect_chain and "/print/" in resp.redirect_chain[-1][0]
    pages = re.findall(r'<section class="sheet"', html)
    assert len(pages) == 3
    for i in range(1, 4):
        assert f"共3板 ({i}/3)" in html
    assert "訂單編號:" in html and "SYN-ORD-A &amp; SYN-ORD-B" in html  # sorted, joined like the sample
    assert "收貨客戶: 合成客戶 甲" in html and "送貨地址: 合成地址 1 號" in html and "送貨時間: 下午3時前" in html
    assert "size: A4 portrait" in html
    # printing again (reload) and generating does not touch stock
    client.get(resp.redirect_chain[-1][0])
    assert stock_state() == before
    assert "共3板" in client.get(reverse("order_detail", args=[a])).content.decode()  # listed on the order


@pytest.mark.parametrize("change, code", [
    ({"ship_to": "  "}, "missing_field"),
    ({"address": ""}, "missing_field"),
    ({"delivery_time": ""}, "missing_field"),
    ({"pallet_count": 0}, "bad_count"),
    ({"pallet_count": 100}, "bad_count"),
    ({"pallet_count": "abc"}, "bad_count"),
    ({"actor": ""}, "missing_actor"),
    ({"order_ids": []}, "no_orders"),
])
def test_invalid_input_is_refused_and_nothing_saved(two_orders, change, code):
    a, _ = two_orders
    kwargs = {"order_ids": [a], "ship_to": "合成客戶", "address": "合成地址", "delivery_time": "上午",
              "pallet_count": 2, "actor": ACTOR, **change}
    with pytest.raises(DomainError) as err:
        pallet_sheets.create_sheet(**kwargs)
    assert err.value.code == code
    assert PalletSheet.objects.count() == 0


def test_orders_of_different_owners_cannot_share_a_sheet(world):
    world.opening(5)
    world.opening(5, owner="SYN-OWNER-B")
    a = world.accept("SYN-ORD-1", 1).result["order_id"]
    b = world.accept("SYN-ORD-2", 1, owner="SYN-OWNER-B").result["order_id"]
    with pytest.raises(DomainError) as err:
        pallet_sheets.create_sheet(order_ids=[a, b], ship_to="x", address="y", delivery_time="z", pallet_count=1, actor=ACTOR)
    assert err.value.code == "mixed_owner"


def test_rejected_form_keeps_typed_values_and_second_visit_is_prefilled(client, two_orders):
    a, _ = two_orders
    html = client.post(reverse("pallet_sheet_form", args=[a]), {**FORM, "pallet_count": "0", "orders": [a]}).content.decode()
    assert "板头纸没有生成" in html and 'value="合成地址 1 號"' in html
    client.post(reverse("pallet_sheet_form", args=[a]), {**FORM, "orders": [a]})
    html = client.get(reverse("pallet_sheet_form", args=[a])).content.decode()
    assert 'value="合成客戶 甲"' in html and 'value="3"' in html  # last sheet for this order


def test_printed_text_is_a_snapshot(two_orders):
    a, _ = two_orders
    sheet = pallet_sheets.create_sheet(order_ids=[a], ship_to="合成客戶", address="舊地址", delivery_time="上午",
                                       pallet_count=1, actor=ACTOR)
    Order.objects.filter(pk=a).update(number="SYN-RENAMED")
    sheet.refresh_from_db()
    assert sheet.order_numbers == "SYN-ORD-B" and sheet.address == "舊地址"
