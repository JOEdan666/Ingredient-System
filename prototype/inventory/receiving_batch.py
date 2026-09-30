"""Receive a whole receipt notice (预告) in one confirmation.

Every line is checked first; if any line is wrong nothing is written and the
caller gets one message per line.  Otherwise each line with a quantity goes
through domain.confirm_receipt inside one transaction, so a failure on line
40 also undoes lines 1-39.  A quantity of 0 means "did not arrive" and posts
nothing for that line.
"""

from __future__ import annotations

from datetime import date

from django.db import transaction

from . import domain
from .domain import DomainError
from .models import Location, ReceiptLine, ReceiptNotice


class LineErrors(DomainError):
    """Some lines are invalid; `errors` maps line id -> message. Nothing was written."""

    def __init__(self, errors: dict[int, str]):
        super().__init__("line_errors", f"有 {len(errors)} 行需要改，整张单没有入库。")
        self.errors = errors


def _qty(raw) -> int:
    text = (raw or "").strip()
    if not text.isdigit():
        raise ValueError("实收数量必须是 0 或正整数（0 表示没到货）")
    return int(text)


def _expiry(raw):
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"效期「{text}」看不懂")


def receive_notice(*, notice_id: int, actor: str, default_location: str, condition: str, rows: dict) -> dict:
    """rows: {line_id: {"qty": str, "location": str, "expiry": str, "lot": str}}."""
    notice = ReceiptNotice.objects.filter(pk=notice_id).first()
    if notice is None:
        raise DomainError("unknown_notice", "这张预告不存在。")
    lines = list(notice.lines.select_related("product").order_by("line_no"))
    if ReceiptLine.objects.filter(notice_line__notice=notice).exists():
        raise DomainError("already_received", f"预告 {notice.number} 已经收过货了，不能整张再收一次。")
    known_locations = set(Location.objects.filter(active=True).values_list("code", flat=True))

    errors: dict[int, str] = {}
    plan = []
    for line in lines:
        row = rows.get(line.pk, {})
        try:
            qty = _qty(row.get("qty"))
            expiry = _expiry(row.get("expiry"))
            location = (row.get("location") or "").strip() or (default_location or "").strip()
            if qty and not location:
                raise ValueError("没有选货位（上方「统一货位」或这一行的货位）")
            if qty and location not in known_locations:
                raise ValueError(f"货位「{location}」不存在或已停用")
        except ValueError as err:
            errors[line.pk] = str(err)
            continue
        if qty:
            plan.append((line, qty, expiry, location, (row.get("lot") or "").strip()))
    if errors:
        raise LineErrors(errors)
    if not plan:
        raise DomainError("nothing_received", "每一行实收都是 0，没有东西可以入库。")

    posted = 0
    with transaction.atomic():
        for line, qty, expiry, location, lot in plan:
            try:
                domain.confirm_receipt(
                    operation_id=f"rcv-n{notice.pk}-l{line.pk}", actor=actor, notice_line_id=line.pk, qty=qty,
                    expiry_date=expiry, external_lot=lot, location_code=location, condition=condition,
                )
            except DomainError as err:
                raise LineErrors({line.pk: err.message})  # rolls back every line already posted
            posted += qty
    return {"lines": len(plan), "qty": posted, "skipped": len(lines) - len(plan),
            "short": sum(max(0, l.qty_expected - q) for l, q, *_ in plan)
                     + sum(l.qty_expected for l in lines if l.pk not in {p[0].pk for p in plan})}
