"""Allocate a whole order in one save (整张订单一次选货位).

Every entered quantity is checked first; if any line is wrong nothing is
written.  Otherwise each line with quantities goes through
domain.allocate_line (which re-checks stock under its own rules) inside one
transaction, so a failure on the last line also undoes the earlier ones.
A line may be left short (not enough stock yet); that is shown, not refused.
"""

from __future__ import annotations

from django.db import transaction

from . import domain
from .domain import DomainError
from .models import Order
from .receiving_batch import LineErrors


def prefill(line: dict) -> dict[int, int]:
    """Suggest quantities only when there is no real choice to make.

    The order names an expiry, exactly one matching batch/location exists, and
    it can cover the whole line.  Anything else is left for the employee
    (the business rule is that staff choose lots and locations; no FEFO).
    """
    need = line["numbers"]["unallocated"]
    cands = line["candidates"]
    if need and line["requested_expiry"] and len(cands) == 1 and cands[0]["free"] >= need:
        return {cands[0]["id"]: need}
    return {}


def _qty(raw) -> int:
    text = (raw or "").strip()
    if text == "":
        return 0
    if not text.isdigit():
        raise ValueError("分配数量必须是 0 或正整数")
    return int(text)


def allocate_order(*, order_id: int, actor: str, operation_id: str, entries: dict) -> dict:
    """entries: {line_id: {balance_id: raw_qty}} from the form."""
    order = Order.objects.filter(pk=order_id).first()
    if order is None:
        raise DomainError("unknown_order", "订单不存在。")
    lines = {l.pk: l for l in order.lines.all()}
    errors: dict[int, str] = {}
    plan = []
    for line_id, picks in entries.items():
        line = lines.get(line_id)
        if line is None:
            raise DomainError("line_not_in_order", "有一行不属于这张订单，拒绝执行。")
        try:
            parsed = [{"balance_id": b, "qty": _qty(q)} for b, q in picks.items()]
        except ValueError as err:
            errors[line_id] = str(err)
            continue
        parsed = [p for p in parsed if p["qty"]]
        total = sum(p["qty"] for p in parsed)
        if total > line.qty_unallocated:
            errors[line_id] = f"多填了 {total - line.qty_unallocated}（这一行还需分配 {line.qty_unallocated}）"
            continue
        if parsed:
            plan.append((line, parsed))
    if errors:
        raise LineErrors(errors)
    if not plan:
        raise DomainError("nothing_allocated", "一个数量都没填，没有东西可以保存。")
    with transaction.atomic():
        for line, parsed in plan:
            try:
                domain.allocate_line(operation_id=f"{operation_id}-l{line.pk}"[:64], actor=actor,
                                     line_id=line.pk, picks=parsed)
            except DomainError as err:
                raise LineErrors({line.pk: err.message})  # undoes lines already saved
    return {"lines": len(plan), "qty": sum(p["qty"] for _, ps in plan for p in ps)}
