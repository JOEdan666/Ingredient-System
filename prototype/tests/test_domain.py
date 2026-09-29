"""Quantity scenarios for D07 / I1-I11 / A01 A02 A03 A05 A10 on synthetic data.

Runs on SQLite (simulated persistence): proves the arithmetic and the
rejections, NOT concurrency or locking (A06 needs PostgreSQL, T06).
"""
import pytest

from inventory import domain
from inventory.domain import DomainError, OperationConflict
from inventory.models import (
    Allocation,
    ImmutableRowError,
    Operation,
    Order,
    OrderLine,
    ReservationEntry,
    StockBalance,
    StockLot,
    StockMovement,
)
from inventory.synthetic import load_synthetic_fixture

from .conftest import ACTOR, EXP_1, EXP_2, new_op


def _order_id(res):
    return res.result["order_id"]


def _alloc_ids(res):
    return res.result["allocation_ids"]


# (a) --------------------------------------------------------------------

def test_a_accept_20_of_100_then_ship_keeps_available_80(world):
    bal = world.opening(100)
    order = world.accept("SYN-O-A", 20)
    assert world.numbers(world.product_a) == {"on_hand": 100, "sellable": 100, "reserved": 20, "available": 80}

    alloc = world.allocate(world.line_id(order), [(bal, 20)])
    assert world.numbers(world.product_a)["available"] == 80  # allocating does not deduct again

    world.ship(_order_id(order), [(_alloc_ids(alloc)[0], 20)])
    assert world.numbers(world.product_a) == {"on_hand": 80, "sellable": 80, "reserved": 0, "available": 80}


def test_a10_cancel_before_ship_returns_to_100(world):
    bal = world.opening(100)
    order = world.accept("SYN-O-A10", 20)
    world.allocate(world.line_id(order), [(bal, 5)])  # 5 allocated, 15 still unallocated
    world.cancel(world.line_id(order))
    assert world.numbers(world.product_a) == {"on_hand": 100, "sellable": 100, "reserved": 0, "available": 100}
    line = OrderLine.objects.get(pk=world.line_id(order))
    assert line.qty_cancelled == 20 and line.qty_unallocated == 0


# (b) --------------------------------------------------------------------

def test_b_ship_8_then_cancel_remaining_12_ends_at_92(world):
    bal = world.opening(100)
    order = world.accept("SYN-O-B", 20)
    alloc = world.allocate(world.line_id(order), [(bal, 20)])
    world.ship(_order_id(order), [(_alloc_ids(alloc)[0], 8)])
    assert world.numbers(world.product_a) == {"on_hand": 92, "sellable": 92, "reserved": 12, "available": 80}

    res = world.cancel(world.line_id(order))
    assert res.result == {"cancelled": 12}
    assert world.numbers(world.product_a) == {"on_hand": 92, "sellable": 92, "reserved": 0, "available": 92}
    # Shipped quantity can never be cancelled back to 100.
    with pytest.raises(DomainError) as err:
        world.cancel(world.line_id(order))
    assert err.value.code == "nothing_to_cancel"
    assert world.numbers(world.product_a)["available"] == 92


# (c) --------------------------------------------------------------------

def test_c_same_cancel_submitted_twice_releases_once(world):
    world.opening(100)
    order = world.accept("SYN-O-C", 20)
    op = new_op()
    first = world.cancel(world.line_id(order), qty=5, op=op)
    second = world.cancel(world.line_id(order), qty=5, op=op)  # e.g. double click / network retry
    assert first.replayed is False and second.replayed is True
    assert second.result == first.result
    assert world.numbers(world.product_a)["reserved"] == 15
    assert ReservationEntry.objects.filter(kind=ReservationEntry.Kind.RELEASE).count() == 1


def test_c_second_full_cancel_with_new_id_changes_nothing(world):
    world.opening(100)
    order = world.accept("SYN-O-C2", 20)
    world.cancel(world.line_id(order))
    before = world.numbers(world.product_a)
    with pytest.raises(DomainError) as err:
        world.cancel(world.line_id(order))
    assert err.value.code == "nothing_to_cancel"
    assert world.numbers(world.product_a) == before == {"on_hand": 100, "sellable": 100, "reserved": 0,
                                                        "available": 100}


# (d) --------------------------------------------------------------------

def test_d_same_operation_id_applies_once(world):
    world.opening(100)
    op = new_op()
    first = world.accept("SYN-O-D", 20, op=op)
    second = world.accept("SYN-O-D", 20, op=op)
    assert (first.replayed, second.replayed) == (False, True)
    assert second.result == first.result
    assert Order.objects.filter(number="SYN-O-D").count() == 1
    assert world.numbers(world.product_a)["reserved"] == 20
    assert Operation.objects.filter(pk=op).count() == 1


def test_d_same_operation_id_different_content_is_rejected(world):
    world.opening(100)
    op = new_op()
    world.accept("SYN-O-D2", 20, op=op)
    with pytest.raises(OperationConflict):
        world.accept("SYN-O-D2", 30, op=op)
    assert world.numbers(world.product_a)["reserved"] == 20


def test_d_duplicate_allocation_cannot_over_allocate_line(world):
    """InvenTree counterexample (T01): a repeated allocation POST shipped 20 on a 10 line."""
    bal = world.opening(100)
    order = world.accept("SYN-O-D3", 10)
    op = new_op()
    world.allocate(world.line_id(order), [(bal, 10)], op=op)
    world.allocate(world.line_id(order), [(bal, 10)], op=op)  # retry: replayed
    with pytest.raises(DomainError) as err:
        world.allocate(world.line_id(order), [(bal, 10)])  # new id: line has nothing left
    assert err.value.code == "i4"
    assert Allocation.objects.count() == 1
    assert StockBalance.objects.get(pk=bal.pk).allocated == 10


# (e) --------------------------------------------------------------------

def test_e_pending_inspection_stock_cannot_be_allocated(world):
    ok = world.opening(5, location="A-01")
    pending = world.opening(5, location="RECEIVING", condition="PENDING_INSPECTION")
    # Pending stock is not sellable: only 5 available.
    assert world.numbers(world.product_a) == {"on_hand": 10, "sellable": 5, "reserved": 0, "available": 5}
    order = world.accept("SYN-O-E", 5)
    with pytest.raises(DomainError) as err:
        world.allocate(world.line_id(order), [(pending, 5)])
    assert err.value.code == "i2_condition"
    world.allocate(world.line_id(order), [(ok, 5)])


def test_e_inspection_pass_makes_stock_allocatable_in_receiving(world):
    pending = world.opening(5, location="RECEIVING", condition="PENDING_INSPECTION")
    with pytest.raises(DomainError) as err:
        world.accept("SYN-O-E2", 3)
    assert err.value.code == "insufficient_available"
    res = domain.change_condition(operation_id=new_op(), actor=ACTOR, balance_id=pending.pk, qty=5,
                                  to_condition="AVAILABLE")
    passed = StockBalance.objects.get(pk=res.result["to_balance_id"])
    assert passed.location.code == "RECEIVING"  # not put away yet, still shippable
    order = world.accept("SYN-O-E2", 3)
    world.allocate(world.line_id(order), [(passed, 3)])


def test_unknown_condition_is_rejected_not_treated_as_available(world):
    with pytest.raises(DomainError) as err:
        world.opening(5, condition="MAYBE_OK")
    assert err.value.code == "unknown_condition"
    assert StockMovement.objects.count() == 0


# (f) --------------------------------------------------------------------

def test_f_requested_expiry_cannot_be_swapped(world):
    other = world.opening(10, location="A-01", expiry=EXP_2)
    right = world.opening(10, location="B-01", expiry=EXP_1)
    order = world.accept("SYN-O-F", 4, requested_expiry=EXP_1)
    with pytest.raises(DomainError) as err:
        world.allocate(world.line_id(order), [(other, 4)])
    assert err.value.code == "i8"
    world.allocate(world.line_id(order), [(right, 4)])


def test_f_accept_rejected_when_requested_expiry_short(world):
    world.opening(10, expiry=EXP_2)
    world.opening(2, location="B-01", expiry=EXP_1)
    with pytest.raises(DomainError) as err:
        world.accept("SYN-O-F2", 4, requested_expiry=EXP_1)  # product has 12, expiry EXP_1 has 2
    assert err.value.code == "expiry_shortfall"
    assert not Order.objects.filter(number="SYN-O-F2").exists()


def test_f_unspecified_line_cannot_take_stock_reserved_for_an_expiry(world):
    exp1 = world.opening(4, location="A-01", expiry=EXP_1)
    world.opening(6, location="B-01", expiry=EXP_2)
    world.accept("SYN-O-F3", 4, requested_expiry=EXP_1)
    free_order = world.accept("SYN-O-F4", 4)
    with pytest.raises(DomainError) as err:
        world.allocate(world.line_id(free_order), [(exp1, 4)])
    assert err.value.code == "expiry_shortfall"


# A01 --------------------------------------------------------------------

def test_a01_notice_adds_nothing_receipt_counts_and_receiving_stock_ships(world):
    domain.create_notice(operation_id=new_op(), actor=ACTOR, owner_code="SYN-OWNER-A", number="SYN-ASN-1",
                         lines=[{"product": "000777", "qty": 10, "expiry": EXP_1}])
    assert world.numbers(world.product_a)["on_hand"] == 0
    assert StockMovement.objects.count() == 0  # I9

    from inventory.models import ReceiptNoticeLine
    nline = ReceiptNoticeLine.objects.get(notice__number="SYN-ASN-1")
    res = domain.confirm_receipt(operation_id=new_op(), actor=ACTOR, notice_line_id=nline.pk, qty=8,
                                 expiry_date=EXP_1, external_lot="", location_code="RECEIVING",
                                 condition="AVAILABLE")
    bal = StockBalance.objects.get(pk=res.result["balance_id"])
    assert world.numbers(world.product_a)["on_hand"] == 8

    order = world.accept("SYN-O-A01", 3)
    alloc = world.allocate(world.line_id(order), [(bal, 3)])
    world.ship(_order_id(order), [(_alloc_ids(alloc)[0], 3)])
    assert world.numbers(world.product_a) == {"on_hand": 5, "sellable": 5, "reserved": 0, "available": 5}


# A02 (fixture) ----------------------------------------------------------

def test_a02_multi_location_allocation_and_move_with_fixture(empty_db):
    load_synthetic_fixture()
    a01 = StockBalance.objects.get(owner__code="DEMO-OWNER-A", location__code="A-01")
    b01 = StockBalance.objects.get(owner__code="DEMO-OWNER-A", location__code="B-01")
    product = a01.product
    order = domain.accept_order(operation_id=new_op(), actor=ACTOR, owner_code="DEMO-OWNER-A",
                                number="DEMO-O1", lines=[{"product": "000123", "qty": 10,
                                                          "requested_expiry": "2027-09-02"}])
    line_id = order.result["line_ids"][0]
    alloc = domain.allocate_line(operation_id=new_op(), actor=ACTOR, line_id=line_id,
                                 picks=[{"balance_id": a01.pk, "qty": 6}, {"balance_id": b01.pk, "qty": 4}])
    pa = product.availability
    pa.refresh_from_db()
    assert pa.available == 4  # only B 4 left available (pending 3 in RECEIVING is not sellable)
    domain.ship(operation_id=new_op(), actor=ACTOR, order_id=order.result["order_id"],
                items=[{"allocation_id": a, "qty": q} for a, q in zip(alloc.result["allocation_ids"], (6, 4))])
    pa.refresh_from_db()
    b01.refresh_from_db()
    assert (b01.on_hand, b01.allocated, pa.reserved, pa.available) == (4, 0, 0, 4)

    domain.move_stock(operation_id=new_op(), actor=ACTOR, balance_id=b01.pk, qty=2, to_location_code="C-01")
    pa.refresh_from_db()
    assert pa.sellable == 4 and pa.available == 4
    by_loc = {b.location.code: b.on_hand for b in StockBalance.objects.filter(product=product,
                                                                            condition="AVAILABLE")}
    assert by_loc == {"A-01": 0, "B-01": 2, "C-01": 2}


def test_fixture_load_is_idempotent(empty_db):
    load_synthetic_fixture()
    count = StockMovement.objects.count()
    load_synthetic_fixture()
    assert StockMovement.objects.count() == count == 4


# A03 --------------------------------------------------------------------

def test_a03_other_owner_stock_cannot_be_allocated(world):
    world.opening(10, owner="SYN-OWNER-A")
    other = world.opening(10, owner="SYN-OWNER-B")
    order = world.accept("SYN-O-A03", 4)
    with pytest.raises(DomainError) as err:
        world.allocate(world.line_id(order), [(other, 4)])
    assert err.value.code == "i3"
    assert world.numbers(world.product_b) == {"on_hand": 10, "sellable": 10, "reserved": 0, "available": 10}


def test_a03_owner_b_cannot_order_owner_a_stock_by_same_code(world):
    world.opening(10, owner="SYN-OWNER-A")
    with pytest.raises(DomainError) as err:
        world.accept("SYN-O-A03B", 1, owner="SYN-OWNER-B")
    assert err.value.code == "insufficient_available"


def test_a03_same_expiry_different_receipts_stay_separate_lots(world):
    a = world.opening(5, expiry=EXP_1, source="SYN-RCV-1")
    b = world.opening(5, expiry=EXP_1, source="SYN-RCV-2")
    assert a.lot_id != b.lot_id
    assert StockLot.objects.filter(expiry_date=EXP_1).count() == 2


# Other invariants --------------------------------------------------------

def test_i10_allocated_stock_cannot_be_moved(world):
    bal = world.opening(10)
    order = world.accept("SYN-O-I10", 8)
    world.allocate(world.line_id(order), [(bal, 8)])
    with pytest.raises(DomainError) as err:
        domain.move_stock(operation_id=new_op(), actor=ACTOR, balance_id=bal.pk, qty=3, to_location_code="C-01")
    assert err.value.code == "insufficient_free"
    domain.move_stock(operation_id=new_op(), actor=ACTOR, balance_id=bal.pk, qty=2, to_location_code="C-01")


def test_i11_accept_beyond_available_is_rejected(world):
    world.opening(5)
    world.accept("SYN-O-I11A", 4)
    with pytest.raises(DomainError) as err:
        world.accept("SYN-O-I11B", 4)
    assert err.value.code == "insufficient_available"
    assert world.numbers(world.product_a) == {"on_hand": 5, "sellable": 5, "reserved": 4, "available": 1}


def test_i11_hold_cannot_push_reserved_above_sellable(world):
    bal = world.opening(5)
    world.accept("SYN-O-I11C", 4)  # unallocated reservation of 4
    with pytest.raises(DomainError) as err:
        domain.change_condition(operation_id=new_op(), actor=ACTOR, balance_id=bal.pk, qty=2, to_condition="HOLD")
    assert err.value.code == "i11"
    assert world.numbers(world.product_a)["sellable"] == 5


def test_i1_i2_cannot_allocate_more_than_free(world):
    bal = world.opening(3)
    world.opening(10, location="B-01")
    order = world.accept("SYN-O-I2", 5)
    with pytest.raises(DomainError) as err:
        world.allocate(world.line_id(order), [(bal, 5)])
    assert err.value.code == "i2_free"


def test_i7_posted_rows_are_append_only(world):
    world.opening(5)
    mv = StockMovement.objects.get()
    mv.qty = 50
    with pytest.raises(ImmutableRowError):
        mv.save()
    with pytest.raises(ImmutableRowError):
        mv.delete()


def test_rejected_command_writes_nothing_and_leaves_no_operation(world):
    world.opening(5)
    op = new_op()
    before = (StockMovement.objects.count(), ReservationEntry.objects.count(), Operation.objects.count())
    with pytest.raises(DomainError):
        world.accept("SYN-O-RB", 6, op=op)
    assert (StockMovement.objects.count(), ReservationEntry.objects.count(), Operation.objects.count()) == before
    assert not Operation.objects.filter(pk=op).exists()


def test_reconciliation_detects_tampered_projection(world):
    bal = world.opening(5)
    StockBalance.objects.filter(pk=bal.pk).update(on_hand=7)  # bypass the domain on purpose
    problems = domain.check_invariants()
    assert any("流水合计" in p for p in problems)
    StockBalance.objects.filter(pk=bal.pk).update(on_hand=5)  # restore so the fixture teardown passes


# --- Review fixes (2026-09-28, PR #6 review by Codex and the Claude reviewer routine) ---

def _record_lock_calls(monkeypatch):
    calls = []
    real = domain._lock_balances

    def spy(ids):
        calls.append(sorted(set(ids)))
        return real(ids)

    monkeypatch.setattr(domain, "_lock_balances", spy)
    return calls


def test_move_locks_source_and_destination_in_one_sorted_step(world, monkeypatch):
    # T02 §5: lock all balance rows of a command together in id order. Locking the
    # source first and the destination later lets A->B and B->A moves deadlock
    # on PostgreSQL. SQLite cannot show the deadlock, so check the lock calls.
    world.opening(5, location="A-01")
    moving = world.opening(3, location="B-01")
    calls = _record_lock_calls(monkeypatch)
    res = domain.move_stock(operation_id=new_op(), actor=ACTOR, balance_id=moving.pk, qty=1,
                            to_location_code="A-01")
    dest = res.result["to_balance_id"]
    assert calls == [sorted([moving.pk, dest])]   # one call, both rows, id order


def test_condition_change_locks_both_rows_in_one_sorted_step(world, monkeypatch):
    pending = world.opening(4, location="RECEIVING", condition="PENDING_INSPECTION")
    world.opening(2, location="RECEIVING", condition="AVAILABLE")
    calls = _record_lock_calls(monkeypatch)
    domain.change_condition(operation_id=new_op(), actor=ACTOR, balance_id=pending.pk, qty=4,
                            to_condition="AVAILABLE")
    assert len(calls) == 1 and len(calls[0]) == 2
