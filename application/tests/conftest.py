"""Synthetic fixtures run against committed PostgreSQL transactions."""
import itertools
from datetime import date

import pytest

from inventory import domain
from inventory.models import Location, Owner, Product, ProductAvailability, StockBalance

ACTOR = "synthetic-tester"
EXP_1 = date(2027, 9, 2)
EXP_2 = date(2028, 1, 15)
_ops = itertools.count(1)


def new_op() -> str:
    return f"test-op-{next(_ops)}"


class World:
    def __init__(self):
        self.owner_a = domain.create_owner("SYN-OWNER-A", "合成货主 A")
        self.owner_b = domain.create_owner("SYN-OWNER-B", "合成货主 B")
        for code, kind in [("RECEIVING", Location.Kind.RECEIVING), ("A-01", Location.Kind.STORAGE),
                           ("B-01", Location.Kind.STORAGE), ("C-01", Location.Kind.STORAGE)]:
            domain.create_location(code, kind)
        # Same code under two owners: two different products (A03).
        self.product_a = domain.create_product(self.owner_a, "000777", name_zh="合成商品 A")
        self.product_b = domain.create_product(self.owner_b, "000777", name_zh="合成商品 B")

    def opening(self, qty, *, owner="SYN-OWNER-A", location="A-01", condition="AVAILABLE", expiry=EXP_1,
                source=None, lot=""):
        res = domain.post_opening(
            operation_id=new_op(), actor=ACTOR, owner_code=owner, product_code="000777",
            source_ref=source or f"SYN-OPEN-{next(_ops)}", external_lot=lot, expiry_date=expiry,
            location_code=location, condition=condition, qty=qty,
        )
        return StockBalance.objects.get(pk=res.result["balance_id"])

    def accept(self, number, qty, *, owner="SYN-OWNER-A", requested_expiry=None, op=None):
        res = domain.accept_order(
            operation_id=op or new_op(), actor=ACTOR, owner_code=owner, number=number,
            lines=[{"product": "000777", "qty": qty, "requested_expiry": requested_expiry}],
        )
        return res

    @staticmethod
    def line_id(res):
        return res.result["line_ids"][0]

    def allocate(self, line_id, picks, op=None):
        return domain.allocate_line(operation_id=op or new_op(), actor=ACTOR, line_id=line_id,
                                    picks=[{"balance_id": b.pk, "qty": q} for b, q in picks])

    def ship(self, order_id, items, op=None):
        return domain.ship(operation_id=op or new_op(), actor=ACTOR, order_id=order_id,
                           items=[{"allocation_id": a, "qty": q} for a, q in items])

    def cancel(self, line_id, qty=None, op=None):
        return domain.cancel_line(operation_id=op or new_op(), actor=ACTOR, line_id=line_id, qty=qty)

    @staticmethod
    def numbers(product: Product) -> dict:
        pa = ProductAvailability.objects.get(product=product)
        on_hand = sum(b.on_hand for b in StockBalance.objects.filter(product=product))
        return {"on_hand": on_hand, "sellable": pa.sellable, "reserved": pa.reserved, "available": pa.available}


@pytest.fixture
def world(transactional_db):
    w = World()
    yield w
    assert domain.check_invariants() == []


@pytest.fixture
def empty_db(transactional_db):
    yield
    assert domain.check_invariants() == []


@pytest.fixture
def owner_a_product(world):
    return Owner.objects.get(code="SYN-OWNER-A"), world.product_a
