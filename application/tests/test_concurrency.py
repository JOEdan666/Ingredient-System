"""Committed, separate-connection PostgreSQL checks for D09 / A05 A06 A10."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import time

import pytest
from django.db import IntegrityError, connection, connections
from django.test import override_settings

from inventory import domain
from inventory.domain import DomainError, OperationConflict
from inventory.models import Operation, ProductAvailability, ReservationEntry, StockBalance, StockMovement
from .conftest import ACTOR, new_op

pytestmark = pytest.mark.concurrency


def _worker(call, callback=None, *, no_lock=False):
    try:
        with domain.test_probe(callback or (lambda point: None), without_availability_lock=no_lock):
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                pid = cursor.fetchone()[0]
            try:
                return pid, call(), None
            except Exception as exc:
                return pid, None, exc
    finally:
        connections.close_all()


def _wait_for_lock(pid, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s", [pid])
            row = cursor.fetchone()
        if row and row[0] == "Lock":
            return True
        time.sleep(0.02)
    return False


class DetectedMissingLock(Exception):
    """The deliberately unlocked path reached a stale read before A committed."""


@override_settings(INVENTORY_TEST_HOOKS=True)
def _competing_orders(world, *, no_lock=False, same_id=False):
    held = Event()
    release = Event()
    b_at_lock = Event()
    b_read = Event()
    b_pid = []
    op_a, op_b = new_op(), new_op()
    if same_id:
        op_b = op_a

    def a_probe(point):
        if point == "after_availability_read":
            held.set()
            if not release.wait(8):
                raise AssertionError("A was not released")

    def b_probe(point):
        if point == "before_availability_lock":
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                b_pid.append(cursor.fetchone()[0])
            b_at_lock.set()
        elif point == "after_availability_read":
            b_read.set()
            if no_lock:
                raise DetectedMissingLock()

    def accept(number, op):
        return domain.accept_order(operation_id=op, actor=ACTOR, owner_code=world.owner_a.code,
                                   number=number, lines=[{"product": world.product_a.code, "qty": 4}])

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(_worker, lambda: accept("SYN-RACE-A", op_a), a_probe)
        assert held.wait(5), "A never reached the locked read"
        b = pool.submit(_worker, lambda: accept("SYN-RACE-A" if same_id else "SYN-RACE-B", op_b),
                        b_probe, no_lock=no_lock)
        try:
            if same_id:
                # B waits on the Operation primary-key insert, before reaching availability.
                time.sleep(0.15)
                assert not b.done()
            else:
                assert b_at_lock.wait(5), "B never reached the lock point"
                if no_lock:
                    assert b_read.wait(5), "unlocked B did not pass the read; counterexample invalid"
                else:
                    assert not b_read.wait(0.1), "B read before A committed"
                    assert _wait_for_lock(b_pid[0]), "PostgreSQL did not report B waiting on a lock"
                    assert not b.done(), "B returned before A committed"
        finally:
            release.set()
        result_a, result_b = a.result(timeout=8), b.result(timeout=8)
    return result_a, result_b, b_read.is_set()


@pytest.mark.parametrize("repeat", range(3))
def test_unallocated_orders_share_product_lock(world, repeat):
    world.opening(5)
    (pid_a, a, err_a), (pid_b, b, err_b), read = _competing_orders(world)
    assert a is not None and err_a is None
    assert b is None and isinstance(err_b, DomainError) and err_b.code == "insufficient_available"
    assert not read and pid_a != pid_b  # B is rejected before the post-read hook.
    assert world.numbers(world.product_a)["available"] == 1


def test_missing_for_update_counterexample_is_detected(world):
    world.opening(5)
    # On the deliberately broken path B passes the read while A still holds
    # the correct row lock. A correct implementation must fail this assertion.
    (_, a, err_a), (_, b, err_b), read = _competing_orders(world, no_lock=True)
    assert read and a is not None and err_a is None
    assert b is None and isinstance(err_b, DetectedMissingLock)


@override_settings(INVENTORY_TEST_HOOKS=True)
def test_allocated_orders_compete_for_same_balance(world):
    selected = world.opening(5, location="A-01")
    world.opening(5, location="B-01", source="SYN-SECOND")
    a_order = world.accept("SYN-ALLOC-A", 4)
    b_order = world.accept("SYN-ALLOC-B", 4)
    held, release, b_at_lock = Event(), Event(), Event()
    b_pid = []

    def a_probe(point):
        if point == "after_allocation_read":
            held.set()
            assert release.wait(8)

    def b_probe(point):
        if point == "before_availability_lock":
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                b_pid.append(cursor.fetchone()[0])
            b_at_lock.set()

    def allocate(order):
        return domain.allocate_line(operation_id=new_op(), actor=ACTOR, line_id=world.line_id(order),
                                    picks=[{"balance_id": selected.pk, "qty": 4}])

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(_worker, lambda: allocate(a_order), a_probe)
        assert held.wait(5)
        b = pool.submit(_worker, lambda: allocate(b_order), b_probe)
        try:
            assert b_at_lock.wait(5)
            assert _wait_for_lock(b_pid[0])
        finally:
            release.set()
        (_, a_result, a_error), (_, b_result, b_error) = a.result(timeout=8), b.result(timeout=8)
    assert a_result is not None and a_error is None
    assert b_result is None and isinstance(b_error, DomainError) and b_error.code == "i2_free"
    assert StockBalance.objects.get(pk=selected.pk).allocated == 4


def test_same_operation_id_two_connections_replays_once(world):
    world.opening(5)
    (_, a, err_a), (_, b, err_b), _ = _competing_orders(world, same_id=True)
    assert err_a is err_b is None
    assert a.result == b.result and not a.replayed and b.replayed
    assert world.numbers(world.product_a)["reserved"] == 4


def test_same_operation_id_different_payload_rejected(world):
    world.opening(5)
    op = new_op()
    world.accept("SYN-ONE", 4, op=op)
    with pytest.raises(OperationConflict):
        world.accept("SYN-ONE", 3, op=op)
    assert Operation.objects.filter(pk=op).count() == 1


def test_ship_does_not_deduct_available_twice(world):
    balance = world.opening(5)
    order = world.accept("SYN-SHIP", 4)
    allocated = world.allocate(world.line_id(order), [(balance, 4)])
    world.ship(order.result["order_id"], [(allocated.result["allocation_ids"][0], 4)])
    assert world.numbers(world.product_a) == {"on_hand": 1, "sellable": 1, "reserved": 0, "available": 1}


def test_multiline_rejection_rolls_back_everything(world):
    world.opening(5)
    with pytest.raises(DomainError):
        domain.accept_order(operation_id=new_op(), actor=ACTOR, owner_code=world.owner_a.code,
                            number="SYN-MULTI", lines=[{"product": "000777", "qty": 2},
                                                       {"product": "000777", "qty": 4}])
    assert not ReservationEntry.objects.exists()
    assert world.numbers(world.product_a)["available"] == 5


def test_move_failure_after_out_movement_rolls_back(world, monkeypatch):
    balance = world.opening(5)
    before = StockMovement.objects.count()
    original = domain._movement

    def fail_inbound(*args, **kwargs):
        if args[1] == StockMovement.Kind.MOVE_IN:
            raise RuntimeError("synthetic crash after MOVE_OUT")
        return original(*args, **kwargs)

    monkeypatch.setattr(domain, "_movement", fail_inbound)
    with pytest.raises(RuntimeError):
        domain.move_stock(operation_id=new_op(), actor=ACTOR, balance_id=balance.pk,
                          qty=2, to_location_code="B-01")
    assert StockMovement.objects.count() == before
    assert StockBalance.objects.get(pk=balance.pk).on_hand == 5


def test_duplicate_cancel_releases_once(world):
    world.opening(5)
    order = world.accept("SYN-CANCEL", 4)
    op = new_op()
    a = world.cancel(world.line_id(order), qty=2, op=op)
    b = world.cancel(world.line_id(order), qty=2, op=op)
    assert not a.replayed and b.replayed
    assert world.numbers(world.product_a)["available"] == 3
    assert ReservationEntry.objects.filter(kind=ReservationEntry.Kind.RELEASE).count() == 1


def test_database_rejects_negative_balance(world):
    balance = world.opening(5)
    with pytest.raises(IntegrityError):
        with connection.cursor() as cursor:
            cursor.execute("UPDATE inventory_stockbalance SET on_hand = -1 WHERE id = %s", [balance.pk])
    assert StockBalance.objects.get(pk=balance.pk).on_hand == 5


def test_opposite_moves_finish_without_deadlock(world):
    a = world.opening(5, location="A-01")
    b = world.opening(5, location="B-01", source="SYN-OTHER")
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(lambda: _move_worker(a.pk, "B-01"))
        second = pool.submit(lambda: _move_worker(b.pk, "A-01"))
        assert first.result(timeout=8) is None
        assert second.result(timeout=8) is None
    assert domain.check_invariants() == []


def _move_worker(balance_id, destination):
    try:
        domain.move_stock(operation_id=new_op(), actor=ACTOR, balance_id=balance_id,
                          qty=1, to_location_code=destination)
    finally:
        connections.close_all()
