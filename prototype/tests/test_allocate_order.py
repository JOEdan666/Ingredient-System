"""Whole-order allocation (整张订单一次选货位), approved acceptance sheet 2026-09-30."""
import pytest
from django.urls import reverse

from inventory import domain
from inventory.models import Allocation, Order, StockBalance

from .conftest import ACTOR, EXP_1, EXP_2, new_op

DEMO_ACTOR = "员工甲（合成）"


def accept(lines, number="SYN-ORD-W"):
    res = domain.accept_order(operation_id=new_op(), actor=ACTOR, owner_code="SYN-OWNER-A", number=number,
                              lines=[{"product": "000777", "qty": q, "requested_expiry": e} for q, e in lines])
    return Order.objects.get(pk=res.result["order_id"])


def post(client, order, picks, op="op-w1"):
    data = {"actor": DEMO_ACTOR, "operation_id": op}
    data.update({f"pick_{l}_{b}": str(q) for (l, b), q in picks.items()})
    return client.post(reverse("allocate", args=[order.pk]), data, follow=True)


def page(client, order):
    return client.get(reverse("order_detail", args=[order.pk])).content.decode()


def test_1_4_one_save_allocates_every_line(client, world):
    a = world.opening(10, location="A-01", expiry=EXP_1)
    b = world.opening(10, location="B-01", expiry=EXP_2)
    order = accept([(3, None), (4, None)])
    l1, l2 = order.lines.order_by("line_no")
    html = post(client, order, {(l1.pk, a.pk): 3, (l2.pk, b.pk): 4}).content.decode()
    assert "分配已保存：2 行，共 7 件" in html and "全部配好，可以发货" in html
    assert Allocation.objects.count() == 2


def test_2_prefill_only_when_there_is_no_real_choice(client, world):
    world.opening(10, location="A-01", expiry=EXP_1)
    world.opening(10, location="B-01", expiry=EXP_2)
    order = accept([(3, EXP_1)])  # only A-01 has EXP_1 -> prefilled
    line = order.lines.get()
    html = page(client, order)
    assert "已先填好" in html and 'value="3"' in html and "1 行已配好" in html
    world.opening(10, location="C-01", expiry=EXP_1)  # now two places share EXP_1 -> staff must choose
    html = page(client, order)
    assert "已先填好" not in html and "还差 3" in html
    order2 = accept([(3, None)], number="SYN-ORD-NOEXP")  # no requested expiry -> never prefilled
    assert "已先填好" not in page(client, order2)
    assert Allocation.objects.filter(order_line=line).count() == 0  # showing a suggestion writes nothing


def test_3_short_line_is_red_and_can_be_saved_with_the_rest(client, world):
    a = world.opening(10, location="A-01", expiry=EXP_1)
    order = accept([(3, None), (4, None)])
    l1, l2 = order.lines.order_by("line_no")
    html = page(client, order)
    assert "还差 3" in html and "还差 4" in html
    html = post(client, order, {(l1.pk, a.pk): 3, (l2.pk, a.pk): 2}).content.decode()
    assert "分配已保存：2 行，共 5 件" in html and "还有 1 行没配够" in html


def test_4_bad_line_saves_nothing_keeps_values_and_names_the_line(client, world):
    a = world.opening(10, location="A-01", expiry=EXP_1)
    order = accept([(3, None), (4, None)])
    l1, l2 = order.lines.order_by("line_no")
    resp = post(client, order, {(l1.pk, a.pk): 3, (l2.pk, a.pk): 9})  # line 2 over-filled by 5
    html = resp.content.decode()
    assert resp.status_code == 400 and "整张订单没有保存" in html and "多填了 5" in html
    assert f'name="pick_{l1.pk}_{a.pk}" min="0" max="10" value="3"' in html
    assert Allocation.objects.count() == 0


def test_later_line_failure_undoes_earlier_lines(client, world):
    a = world.opening(10, location="A-01", expiry=EXP_1)
    b = world.opening(2, location="B-01", expiry=EXP_2)
    order = accept([(3, None), (4, EXP_1)])  # line 2 requires EXP_1; B-01 is EXP_2 -> domain refuses
    l1, l2 = order.lines.order_by("line_no")
    html = post(client, order, {(l1.pk, a.pk): 3, (l2.pk, b.pk): 2}).content.decode()
    assert "不能改用" in html and Allocation.objects.count() == 0
    assert StockBalance.objects.get(pk=a.pk).allocated == 0


def test_same_form_submitted_twice_is_not_applied_twice(client, world):
    a = world.opening(10, location="A-01", expiry=EXP_1)
    order = accept([(3, None)])
    line = order.lines.get()
    post(client, order, {(line.pk, a.pk): 3}, op="op-dup")
    post(client, order, {(line.pk, a.pk): 3}, op="op-dup")
    assert Allocation.objects.count() == 1 and StockBalance.objects.get(pk=a.pk).allocated == 3
