"""PR #19 review findings (@09f589d, @b17ae9e) that were merged unfixed.

1. The order page's top bar must match what is actually left: an order that
   is fully cancelled is not "已全部发货", and a finished order never says
   "可以发货".
2. A failed whole-order allocation must not say "没有入库" (a receiving word).
"""
from django.urls import reverse

from inventory.models import Allocation, Order
from inventory.receiving_batch import LineErrors

from .conftest import EXP_1
from .test_allocate_order import accept, page, post


def test_fully_shipped_order_says_shipped_not_ready(client, world):
    bal = world.opening(10, expiry=EXP_1)
    order = accept([(3, None)], number="SYN-RF-SHIP")
    line = order.lines.get()
    alloc = world.allocate(line.pk, [(bal, 3)])
    world.ship(order.pk, [(alloc.result["allocation_ids"][0], 3)])
    html = page(client, order)
    assert "已全部发货" in html
    assert "可以发货" not in html


def test_fully_cancelled_order_says_cancelled_not_shipped(client, world):
    world.opening(10, expiry=EXP_1)
    order = accept([(3, None)], number="SYN-RF-CANCEL")
    world.cancel(order.lines.get().pk)
    html = page(client, order)
    assert "已全部取消" in html
    assert "已全部发货" not in html and "可以发货" not in html


def test_part_shipped_part_cancelled_order_states_both(client, world):
    bal = world.opening(10, expiry=EXP_1)
    order = accept([(5, None)], number="SYN-RF-MIX")
    line = order.lines.get()
    alloc = world.allocate(line.pk, [(bal, 5)])
    world.ship(order.pk, [(alloc.result["allocation_ids"][0], 2)])
    world.cancel(line.pk)
    html = page(client, order)
    assert "已处理完：发出 2 件，取消 3 件" in html
    assert "已全部发货" not in html and "可以发货" not in html


def test_allocation_failure_message_does_not_talk_about_receiving(client, world):
    a = world.opening(10, location="A-01", expiry=EXP_1)
    order = accept([(3, None)], number="SYN-RF-MSG")
    line = order.lines.get()
    html = post(client, order, {(line.pk, a.pk): 9}).content.decode()  # 9 > 3 still needed
    assert "整张订单没有保存" in html and "多填了 6" in html
    assert "入库" not in html.split("整张订单没有保存", 1)[1].split("</li>", 1)[0]
    assert Allocation.objects.count() == 0


def test_receiving_failure_message_unchanged():
    assert LineErrors({1: "x"}).message == "有 1 行需要改，整张单没有入库。"
