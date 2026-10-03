"""Whole-order shipment (整张订单一次发货): same pattern as receiving/allocation, no new business rule."""
from django.urls import reverse

from inventory import domain
from inventory.models import Allocation, Order, Shipment, StockBalance, StockMovement

from .conftest import ACTOR, EXP_1, new_op

DEMO_ACTOR = "员工甲（合成）"


def allocated_order(world, qtys=(3, 4)):
    a = world.opening(10, location="A-01", expiry=EXP_1)
    res = domain.accept_order(operation_id=new_op(), actor=ACTOR, owner_code="SYN-OWNER-A", number="SYN-SHIP",
                              lines=[{"product": "000777", "qty": q} for q in qtys])
    order = Order.objects.get(pk=res.result["order_id"])
    for line in order.lines.order_by("line_no"):
        domain.allocate_line(operation_id=new_op(), actor=ACTOR, line_id=line.pk,
                             picks=[{"balance_id": a.pk, "qty": line.qty_ordered}])
    return order, a


def post(client, order, values, op="ship-op-1"):
    data = {"actor": DEMO_ACTOR, "operation_id": op, **{f"ship_{k}": str(v) for k, v in values.items()}}
    return client.post(reverse("ship", args=[order.pk]), data, follow=True)


def allocs(order):
    return list(Allocation.objects.filter(order_line__order=order).order_by("order_line__line_no"))


def test_default_ships_everything_in_one_click_and_rows_are_folded(client, world):
    order, a = allocated_order(world)
    html = client.get(reverse("order_detail", args=[order.pk])).content.decode()
    assert "整张发货" in html and 'id="ship-ready-count">2</span> 项按分配数量发货' in html
    visible, folded = html.split("按分配数量发货（已折叠", 1)
    ship_part = visible[visible.index("整张发货"):]
    assert 'class="srow' not in ship_part and folded.count('class="srow') == 2  # rows only inside the fold
    x, y = allocs(order)
    html = post(client, order, {x.pk: 3, y.pk: 4}).content.decode()
    assert "发货完成：2 项，共 7 件" in html and "已全部发货" in html
    assert StockBalance.objects.get(pk=a.pk).on_hand == 3 and Shipment.objects.count() == 1


def test_partial_row_is_shown_and_rest_stays_for_next_time(client, world):
    order, a = allocated_order(world)
    x, y = allocs(order)
    html = post(client, order, {x.pk: 3, y.pk: 1}).content.decode()
    assert "发货完成：2 项，共 4 件" in html and "还有 3 件未发" in html
    assert "整张发货" in html  # the remaining 3 can be shipped later


def test_changed_row_moves_out_of_fold_and_can_move_back(client, world):
    order, _ = allocated_order(world)
    html = client.get(reverse("order_detail", args=[order.pk])).content.decode()
    assert 'id="ship-attention-rows"' in html
    assert 'id="ship-ready-rows"' in html
    assert '(left === 0 ? ready : attention).appendChild(tr)' in html
    assert 'fold.hidden = ready.children.length === 0' in html


def test_bad_row_ships_nothing_keeps_values_and_names_the_row(client, world):
    order, a = allocated_order(world)
    x, y = allocs(order)
    before = (StockBalance.objects.get(pk=a.pk).on_hand, StockMovement.objects.count())
    resp = post(client, order, {x.pk: 2, y.pk: 9})
    html = resp.content.decode()
    assert resp.status_code == 400 and "整张订单没有发货" in html
    assert "多发了 5（这项只分配了 4 件未发）" in html  # the row's own reason, not just the live hint
    assert f'name="ship_{x.pk}" min="0" max="3" value="2"' in html
    assert (StockBalance.objects.get(pk=a.pk).on_hand, StockMovement.objects.count()) == before


def test_allocation_of_another_order_is_refused(client, world):
    order, a = allocated_order(world)
    other = domain.accept_order(operation_id=new_op(), actor=ACTOR, owner_code="SYN-OWNER-A", number="SYN-OTHER",
                                lines=[{"product": "000777", "qty": 1}])
    other_line = Order.objects.get(pk=other.result["order_id"]).lines.get()
    domain.allocate_line(operation_id=new_op(), actor=ACTOR, line_id=other_line.pk, picks=[{"balance_id": a.pk, "qty": 1}])
    foreign = Allocation.objects.get(order_line=other_line)
    html = post(client, order, {foreign.pk: 1}).content.decode()
    assert "不属于这张订单" in html and Shipment.objects.count() == 0


def test_same_form_twice_ships_once(client, world):
    order, a = allocated_order(world)
    x, y = allocs(order)
    post(client, order, {x.pk: 3, y.pk: 4}, op="ship-dup")
    post(client, order, {x.pk: 3, y.pk: 4}, op="ship-dup")
    assert Shipment.objects.count() == 1 and StockBalance.objects.get(pk=a.pk).on_hand == 3


def test_non_number_quantity_is_refused(client, world):
    order, a = allocated_order(world, qtys=(3,))
    x = allocs(order)[0]
    resp = post(client, order, {x.pk: "abc"})
    assert resp.status_code == 400 and "发货数量必须是 0 或正整数" in resp.content.decode()
    assert Shipment.objects.count() == 0
