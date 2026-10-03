"""Read-side queries for the prototype pages. No writes here.

Numbers follow D07 (docs/domain-model.md section 2):
  on_hand   = physical, all conditions and locations
  sellable  = on_hand in AVAILABLE condition (includes RECEIVING, not put away)
  reserved  = allocated-not-shipped + unallocated reservations of open lines
  available = sellable - reserved   <- shown by default (candidate, Q03)
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from django.db.models import Q, Sum

from .models import (
    Condition,
    LineCancellation,
    Order,
    OrderLine,
    ProductAvailability,
    ReceiptNotice,
    ReservationEntry,
    ShipmentLine,
    StockBalance,
    StockMovement,
)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def product_summaries(owner: str = "", product: str = "") -> list[dict]:
    qs = ProductAvailability.objects.select_related("owner", "product").order_by("owner__code", "product__code")
    if owner:
        qs = qs.filter(owner__code=owner)
    if product:
        qs = qs.filter(product__code__icontains=product)
    rows = []
    for pa in qs:
        balances = StockBalance.objects.filter(product=pa.product)
        on_hand = balances.aggregate(s=Sum("on_hand"))["s"] or 0
        allocated = balances.aggregate(s=Sum("allocated"))["s"] or 0
        unallocated = (OrderLine.objects.filter(product=pa.product).aggregate(s=Sum("qty_unallocated"))["s"] or 0)
        rows.append({
            "owner": pa.owner.code,
            "product": pa.product.code,
            "name": pa.product.name_zh,
            "unit": pa.product.base_unit,
            "available": pa.available,
            "on_hand": on_hand,
            "sellable": pa.sellable,
            "not_sellable": on_hand - pa.sellable,
            "reserved": pa.reserved,
            "reserved_allocated": allocated,
            "reserved_unallocated": unallocated,
        })
    return rows


def balance_rows(*, owner="", product="", lot="", expiry="", location="", condition="", show_zero=False) -> list[dict]:
    qs = StockBalance.objects.select_related("owner", "product", "lot", "location").order_by(
        "owner__code", "product__code", "lot__expiry_date", "lot_id", "location__code", "condition"
    )
    if owner:
        qs = qs.filter(owner__code=owner)
    if product:
        qs = qs.filter(product__code__icontains=product)
    if lot:
        lot_q = Q(lot__external_lot__icontains=lot)
        if lot.upper().startswith("L") and lot[1:].isdigit():
            lot_q |= Q(lot_id=int(lot[1:]))
        qs = qs.filter(lot_q)
    exp = _parse_date(expiry)
    if exp:
        qs = qs.filter(lot__expiry_date=exp)
    if location:
        qs = qs.filter(location__code=location)
    if condition:
        qs = qs.filter(condition=condition)
    if not show_zero:
        qs = qs.filter(on_hand__gt=0)
    rows = []
    for b in qs:
        sellable = b.condition == Condition.AVAILABLE
        rows.append({
            "id": b.pk,
            "owner": b.owner.code,
            "product": b.product.code,
            "name": b.product.name_zh,
            "unit": b.product.base_unit,
            "lot": f"L{b.lot_id}",
            "external_lot": b.lot.external_lot or "未知",
            "lot_source": f"{b.lot.get_source_type_display()} {b.lot.source_ref}",
            "expiry": b.lot.expiry_date,
            "location": b.location.code,
            "location_kind": b.location.get_kind_display(),
            "condition": b.condition,
            "condition_label": b.get_condition_display(),
            "on_hand": b.on_hand,
            "allocated": b.allocated,
            "free": b.free if sellable else 0,
            "free_physical": b.free,
            "sellable": sellable,
        })
    return rows


def notices() -> list[dict]:
    result = []
    for n in ReceiptNotice.objects.select_related("owner").prefetch_related("lines__product").order_by("-pk"):
        lines = []
        for line in n.lines.order_by("line_no"):
            receipts = list(line.receipts.select_related("lot").order_by("pk"))
            received = sum(r.qty_received for r in receipts)
            lines.append({
                "id": line.pk,
                "line_no": line.line_no,
                "product": line.product.code,
                "qty_expected": line.qty_expected,
                "expiry": line.expiry_date,
                "external_lot": line.external_lot,
                "received": received,
                "difference": received - line.qty_expected,
                "receipts": [
                    {"qty": r.qty_received, "condition": r.get_condition_display(), "location": r.location_code,
                     "lot": f"L{r.lot_id}", "expiry": r.lot.expiry_date, "actor": r.actor, "at": r.created_at}
                    for r in receipts
                ],
            })
        first = min((r for l in lines for r in l["receipts"]), key=lambda r: r["at"], default=None)
        result.append({"id": n.pk, "owner": n.owner.code, "number": n.number, "created_by": n.created_by,
                       "created_at": n.created_at, "lines": lines,
                       "total_expected": sum(l["qty_expected"] for l in lines),
                       "total_received": sum(l["received"] for l in lines),
                       "received": first is not None,
                       "received_by": first["actor"] if first else "", "received_at": first["at"] if first else None})
    return result


def line_numbers(line: OrderLine) -> dict:
    allocs = list(line.allocations.all())
    shipped = sum(a.qty_shipped for a in allocs)
    open_alloc = sum(a.qty_open for a in allocs)
    return {
        "ordered": line.qty_ordered,
        "shipped": shipped,
        "allocated_open": open_alloc,
        "unallocated": line.qty_unallocated,
        "cancelled": line.qty_cancelled,
        "cancellable": line.qty_unallocated + open_alloc,
    }


def order_list() -> list[dict]:
    rows = []
    for o in Order.objects.select_related("owner").prefetch_related("lines__allocations").order_by("-pk"):
        totals = defaultdict(int)
        for line in o.lines.all():
            for k, v in line_numbers(line).items():
                totals[k] += v
        rows.append({"id": o.pk, "owner": o.owner.code, "number": o.number, "created_by": o.created_by,
                     "created_at": o.created_at, **totals})
    return rows


def order_detail(order_id: int) -> dict | None:
    o = Order.objects.select_related("owner").filter(pk=order_id).first()
    if o is None:
        return None
    lines = []
    for line in o.lines.select_related("product").order_by("line_no"):
        candidates = []
        if line.qty_unallocated:
            qs = StockBalance.objects.select_related("lot", "location").filter(
                owner=o.owner, product=line.product, condition=Condition.AVAILABLE, on_hand__gt=0
            ).order_by("lot__expiry_date", "location__code")
            if line.requested_expiry:
                qs = qs.filter(lot__expiry_date=line.requested_expiry)
            candidates = [
                {"id": b.pk, "lot": f"L{b.lot_id}", "external_lot": b.lot.external_lot or "未知",
                 "expiry": b.lot.expiry_date, "location": b.location.code,
                 "location_kind": b.location.get_kind_display(), "free": b.free}
                for b in qs if b.free > 0
            ]
        allocations = [
            {"id": a.pk, "lot": f"L{a.balance.lot_id}", "expiry": a.expiry_date, "location": a.location_code,
             "allocated": a.qty_allocated, "shipped": a.qty_shipped, "released": a.qty_released,
             "open": a.qty_open, "by": a.created_by, "at": a.created_at}
            for a in line.allocations.select_related("balance").order_by("pk")
        ]
        lines.append({"id": line.pk, "line_no": line.line_no, "product": line.product.code, "source_line": line.source_line,
                      "requested_expiry": line.requested_expiry, "numbers": line_numbers(line),
                      "candidates": candidates, "allocations": allocations})
    return {"id": o.pk, "owner": o.owner.code, "number": o.number, "source_ref": o.source_ref,
            "created_by": o.created_by, "created_at": o.created_at, "lines": lines}


def order_history(number: str) -> list[dict]:
    """A09: from an order number to expiry, location, quantity, actor and time."""
    result = []
    for o in Order.objects.select_related("owner").filter(number=number).order_by("owner__code"):
        shipped = []
        for sl in (ShipmentLine.objects.select_related("movement", "allocation__balance__lot", "allocation__order_line",
                                                       "shipment")
                   .filter(shipment__order=o).order_by("pk")):
            lot = sl.allocation.balance.lot
            shipped.append({
                "line_no": sl.allocation.order_line.line_no,
                "lot": f"L{lot.pk}",
                "external_lot": lot.external_lot or "未知",
                "lot_source": f"{lot.get_source_type_display()} {lot.source_ref}",
                "expiry": lot.expiry_date,
                "location": sl.movement.location_code,  # snapshot at shipping time
                "qty": sl.qty,
                "actor": sl.movement.actor,
                "at": sl.movement.created_at,
                "business_date": sl.movement.business_date,
            })
        events = []
        for e in (ReservationEntry.objects.select_related("order_line", "allocation")
                  .filter(order_line__order=o).order_by("created_at", "pk")):
            events.append({
                "at": e.created_at, "actor": e.actor, "line_no": e.order_line.line_no, "kind": e.get_kind_display(),
                "qty": e.qty, "location": e.allocation.location_code if e.allocation else "（未选货位）",
                "expiry": e.allocation.expiry_date if e.allocation else e.order_line.requested_expiry,
                "operation": e.operation_id,
            })
        for c in LineCancellation.objects.select_related("order_line").filter(order_line__order=o):
            events.append({
                "at": c.created_at, "actor": c.actor, "line_no": c.order_line.line_no,
                "kind": f"逐行取消（{c.get_reason_display()}）", "qty": -c.qty, "location": "", "expiry": None,
                "operation": c.operation_id,
            })
        for m in StockMovement.objects.select_related("balance__lot").filter(
            kind=StockMovement.Kind.SHIP, source_doc=o.number, balance__owner=o.owner
        ):
            events.append({
                "at": m.created_at, "actor": m.actor, "line_no": int(m.source_line or 0),
                "kind": "实物发出（库存流水）", "qty": m.qty, "location": m.location_code,
                "expiry": m.balance.lot.expiry_date, "operation": m.operation_id,
            })
        events.sort(key=lambda e: (e["at"], e["operation"]))
        lines = [{"line_no": line.line_no, "product": line.product.code, "requested_expiry": line.requested_expiry,
                  "source_line": line.source_line,
                  **line_numbers(line)} for line in o.lines.select_related("product").order_by("line_no")]
        result.append({"owner": o.owner.code, "number": o.number, "source_ref": o.source_ref,
                       "created_by": o.created_by, "created_at": o.created_at, "lines": lines,
                       "shipped": shipped, "events": events})
    return result


def pending_inspection() -> list[dict]:
    return balance_rows(condition=Condition.PENDING_INSPECTION)
