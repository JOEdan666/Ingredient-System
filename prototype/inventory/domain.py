"""Domain commands for the T03 prototype (docs/domain-model.md, T02).

Every stock-changing command:

1. runs in one transaction (`_run`), keyed by a client-generated
   operation_id: same id + same payload returns the stored result without
   writing; same id + different payload is rejected (A05);
2. locks ProductAvailability rows first (ordered by owner, product), then
   StockBalance rows (ordered by id) -- the D09 lock order;
3. re-reads quantities under the lock and checks I1-I11;
4. writes append-only movements / reservation entries and updates the
   projections, then records the result on the Operation row.

Pages (views.py) only call these functions and the read functions in
queries.py; they never write rows themselves.

PROTOTYPE LIMITS: the prototype runs on SQLite, where Django's
select_for_update() is a no-op. The lock order is written as it would run
on PostgreSQL, but nothing here proves concurrency or locking (D09, A06).
Reversal/adjustment commands (I7 corrections) are not implemented.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from .models import (
    Allocation,
    Condition,
    LineCancellation,
    Location,
    Operation,
    Order,
    OrderLine,
    Owner,
    Product,
    ProductAvailability,
    ReceiptLine,
    ReceiptNotice,
    ReceiptNoticeLine,
    ReservationEntry,
    Shipment,
    ShipmentLine,
    StockBalance,
    StockLot,
    StockMovement,
)


class DomainError(Exception):
    """A command was rejected; nothing was written."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class OperationConflict(DomainError):
    pass


@dataclass(frozen=True)
class CommandResult:
    operation_id: str
    replayed: bool
    result: dict


# --------------------------------------------------------------------------
# Command runner: idempotency and transaction boundary
# --------------------------------------------------------------------------

def _payload_hash(command: str, payload: dict) -> str:
    text = json.dumps({"command": command, "payload": payload}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _replay(operation_id: str, command: str, digest: str) -> CommandResult | None:
    existing = Operation.objects.filter(pk=operation_id).first()
    if existing is None:
        return None
    if existing.command != command or existing.payload_hash != digest:
        raise OperationConflict(
            "operation_conflict",
            f"操作编号 {operation_id} 已用于另一份内容，拒绝执行。",
        )
    return CommandResult(operation_id, True, existing.result)


def _run(operation_id: str, command: str, payload: dict, actor: str, fn) -> CommandResult:
    if not operation_id or len(operation_id) > 64:
        raise DomainError("bad_operation_id", "缺少或无效的操作编号（operation_id）。")
    if not actor:
        raise DomainError("missing_actor", "必须填写操作人。")
    digest = _payload_hash(command, payload)
    try:
        with transaction.atomic():
            replay = _replay(operation_id, command, digest)
            if replay is not None:
                return replay
            # Insert first (D09): a concurrent duplicate on PostgreSQL waits on
            # the primary key and then fails with IntegrityError.
            op = Operation.objects.create(
                operation_id=operation_id, command=command, payload_hash=digest, actor=actor
            )
            result = fn(op)
            op.result = result
            op.save(update_fields=["result"])
    except IntegrityError:
        # Either a duplicate operation_id committed first, or a database
        # constraint fired (a bug: domain checks should have caught it).
        replay = _replay(operation_id, command, digest)
        if replay is not None:
            return replay
        raise
    return CommandResult(operation_id, False, result)


def _business_date() -> date:
    return timezone.localdate()  # settings.TIME_ZONE = Asia/Hong_Kong (D04)


# --------------------------------------------------------------------------
# Lock helpers (D09 order: availability rows, then balance rows)
# --------------------------------------------------------------------------

def _lock_availability(product_ids) -> dict[int, ProductAvailability]:
    ids = sorted(set(product_ids))
    rows = list(
        ProductAvailability.objects.select_for_update()
        .filter(product_id__in=ids)
        .order_by("owner_id", "product_id")
    )
    if len(rows) != len(ids):
        raise DomainError("availability_missing", "商品缺少可用汇总行，拒绝执行（数据错误）。")
    return {r.product_id: r for r in rows}


def _lock_balances(balance_ids) -> dict[int, StockBalance]:
    ids = sorted(set(balance_ids))
    rows = list(
        StockBalance.objects.select_for_update()
        .select_related("lot", "location", "owner", "product")
        .filter(pk__in=ids)
        .order_by("pk")
    )
    if len(rows) != len(ids):
        raise DomainError("balance_missing", "库存记录不存在。")
    return {r.pk: r for r in rows}


def _ensure_balance(owner, product, lot, location, condition) -> int:
    """Create the balance row if needed, WITHOUT locking it, so the caller can
    lock source and destination together in one sorted step (T02 §5)."""
    balance, _ = StockBalance.objects.get_or_create(
        owner=owner, product=product, lot=lot, location=location, condition=condition
    )
    return balance.pk


def _balance_for(owner, product, lot, location, condition) -> StockBalance:
    balance, _ = StockBalance.objects.get_or_create(
        owner=owner, product=product, lot=lot, location=location, condition=condition
    )
    return _lock_balances([balance.pk])[balance.pk]


def _save(*rows):
    for row in rows:
        if hasattr(row, "row_version"):
            row.row_version += 1
        row.save()


def _parse_condition(value: str) -> str:
    normalized = (value or "").strip().upper()
    if normalized not in Condition.values:
        # Never treat an unknown condition as available (AGENTS.md).
        raise DomainError("unknown_condition", f"未知的库存状态「{value}」，不能入账。")
    return normalized


def _positive_int(value, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise DomainError("bad_quantity", f"{field}必须是正整数。")
    return value


def _as_date(value, field: str) -> date | None:
    """Expiry is a plain date (no timezone, D04). None/blank means unknown."""
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        # Never guess an ambiguous date (AGENTS.md).
        raise DomainError("bad_date", f"{field}「{value}」不是 YYYY-MM-DD 格式的日期。")


def _get_location(code: str) -> Location:
    try:
        location = Location.objects.get(code=code)
    except Location.DoesNotExist:
        raise DomainError("unknown_location", f"货位「{code}」不存在。")
    if not location.active:
        raise DomainError("inactive_location", f"货位「{code}」已停用。")
    return location


def _get_product(owner: Owner, code: str) -> Product:
    try:
        return Product.objects.get(owner=owner, code=code)
    except Product.DoesNotExist:
        # Codes are resolved inside the owner: another owner's product with the
        # same code is never used (I3, A03).
        raise DomainError("unknown_product", f"货主 {owner.code} 没有商品「{code}」。")


def _get_owner(code: str) -> Owner:
    try:
        return Owner.objects.get(code=code)
    except Owner.DoesNotExist:
        raise DomainError("unknown_owner", f"货主「{code}」不存在。")


def _movement(op, kind, balance, qty, actor, source_doc="", source_line=""):
    return StockMovement.objects.create(
        operation=op,
        kind=kind,
        balance=balance,
        qty=qty,
        location_code=balance.location.code,
        condition=balance.condition,
        source_doc=source_doc,
        source_line=source_line,
        actor=actor,
        business_date=_business_date(),
    )


def _expiry_shortfalls(product_id: int) -> list[str]:
    """Expiry-level check (I8 companion to I11), run after writes.

    For every expiry that open order lines explicitly request, unallocated
    available stock of that expiry must cover their unallocated reservations.
    """
    requested = (
        OrderLine.objects.filter(product_id=product_id, requested_expiry__isnull=False, qty_unallocated__gt=0)
        .values("requested_expiry")
        .annotate(need=Sum("qty_unallocated"))
    )
    problems = []
    for row in requested:
        free = 0
        for b in StockBalance.objects.filter(
            product_id=product_id, condition=Condition.AVAILABLE, lot__expiry_date=row["requested_expiry"]
        ):
            free += b.free
        if free < row["need"]:
            problems.append(
                f"效期 {row['requested_expiry']} 的未分配占用 {row['need']} 超过该效期未分配的合格库存 {free}"
            )
    return problems


def _assert_after_write(product_ids, lines=()):
    """Re-check I11, expiry coverage and I4 inside the transaction."""
    for pa in ProductAvailability.objects.filter(product_id__in=set(product_ids)):
        if pa.reserved > pa.sellable or pa.reserved < 0 or pa.sellable < 0:
            raise DomainError("i11", f"占用 {pa.reserved} 超过可售实物 {pa.sellable}（I11），拒绝执行。")
    for pid in set(product_ids):
        problems = _expiry_shortfalls(pid)
        if problems:
            raise DomainError("expiry_shortfall", "；".join(problems) + "。拒绝执行。")
    for line in lines:
        line.refresh_from_db()
        problem = _line_conservation_problem(line)
        if problem:
            raise DomainError("i4", problem)


def _line_conservation_problem(line: OrderLine) -> str | None:
    shipped = 0
    open_alloc = 0
    for a in line.allocations.all():
        shipped += a.qty_shipped
        open_alloc += a.qty_open
    total = shipped + open_alloc + line.qty_unallocated + line.qty_cancelled
    if total != line.qty_ordered:
        return (
            f"订单行 {line.order.number}#{line.line_no} 数量不守恒（I4）："
            f"订购 {line.qty_ordered} ≠ 已发 {shipped} + 已分配未发 {open_alloc} "
            f"+ 未分配占用 {line.qty_unallocated} + 已取消 {line.qty_cancelled}"
        )
    return None


# --------------------------------------------------------------------------
# Master data (not stock-changing; no operation_id)
# --------------------------------------------------------------------------

@transaction.atomic
def create_owner(code: str, name: str) -> Owner:
    return Owner.objects.create(code=code, name=name)


@transaction.atomic
def create_product(owner: Owner, code: str, name_zh: str = "", name_en: str = "", base_unit: str = "EA") -> Product:
    """Create the product and its ProductAvailability row in one transaction."""
    if not isinstance(code, str) or not code:
        raise DomainError("bad_product_code", "商品编码必须是非空文本。")
    product = Product.objects.create(owner=owner, code=code, name_zh=name_zh, name_en=name_en, base_unit=base_unit)
    ProductAvailability.objects.create(owner=owner, product=product)
    return product


def create_location(code: str, kind: str = Location.Kind.STORAGE) -> Location:
    return Location.objects.create(code=code, kind=kind)


# --------------------------------------------------------------------------
# Stock-in: opening balance, notice, receipt, inspection, move
# --------------------------------------------------------------------------

def post_opening(*, operation_id, actor, owner_code, product_code, source_ref, external_lot, expiry_date,
                 location_code, condition, qty, source_doc="") -> CommandResult:
    """Post one opening-balance line as an OPENING movement (D08; unverified count)."""
    payload = dict(owner=owner_code, product=product_code, source_ref=source_ref, external_lot=external_lot,
                   expiry=expiry_date, location=location_code, condition=condition, qty=qty, source_doc=source_doc)

    def fn(op):
        owner = _get_owner(owner_code)
        product = _get_product(owner, product_code)
        location = _get_location(location_code)
        cond = _parse_condition(condition)
        _positive_int(qty, "期初数量")
        expiry = _as_date(expiry_date, "效期")
        pas = _lock_availability([product.pk]) if cond == Condition.AVAILABLE else {}
        lot, created = StockLot.objects.get_or_create(
            product=product, source_type=StockLot.Source.OPENING, source_ref=source_ref,
            defaults=dict(external_lot=external_lot or "", expiry_date=expiry),
        )
        if not created and (lot.external_lot != (external_lot or "") or lot.expiry_date != expiry):
            raise DomainError("lot_mismatch", f"来源行 {source_ref} 的批号或效期与已导入的不一致，拒绝合并。")
        balance = _balance_for(owner, product, lot, location, cond)
        _movement(op, StockMovement.Kind.OPENING, balance, qty, actor, source_doc, source_ref)
        balance.on_hand += qty
        _save(balance)
        if cond == Condition.AVAILABLE:
            pa = pas[product.pk]
            pa.sellable += qty
            _save(pa)
        return {"balance_id": balance.pk, "lot_id": lot.pk}

    return _run(operation_id, "post_opening", payload, actor, fn)


def create_notice(*, operation_id, actor, owner_code, number, lines) -> CommandResult:
    """Advance notice (预告). Writes no stock movement (I9, A01)."""
    payload = dict(owner=owner_code, number=number, lines=lines)

    def fn(op):
        owner = _get_owner(owner_code)
        if not number:
            raise DomainError("bad_number", "预告单号不能为空。")
        if ReceiptNotice.objects.filter(owner=owner, number=number).exists():
            raise DomainError("duplicate_notice", f"预告单号 {number} 已存在。")
        if not lines:
            raise DomainError("no_lines", "预告至少要有一行。")
        notice = ReceiptNotice.objects.create(owner=owner, number=number, created_by=actor)
        for i, line in enumerate(lines, start=1):
            ReceiptNoticeLine.objects.create(
                notice=notice, line_no=i, product=_get_product(owner, line["product"]),
                qty_expected=_positive_int(line["qty"], "预告数量"),
                expiry_date=_as_date(line.get("expiry"), "预告效期"), external_lot=line.get("external_lot") or "",
            )
        return {"notice_id": notice.pk}

    return _run(operation_id, "create_notice", payload, actor, fn)


def confirm_receipt(*, operation_id, actor, notice_line_id, qty, expiry_date, external_lot, location_code,
                    condition) -> CommandResult:
    """Actual receipt (实收): new StockLot + RECEIPT movement.

    condition is PENDING_INSPECTION (待检) or AVAILABLE (合格). Stock received
    as AVAILABLE into a RECEIVING location is sellable before put-away.
    """
    payload = dict(notice_line=notice_line_id, qty=qty, expiry=expiry_date, external_lot=external_lot,
                   location=location_code, condition=condition)

    def fn(op):
        try:
            nline = ReceiptNoticeLine.objects.select_related("notice__owner", "product").get(pk=notice_line_id)
        except ReceiptNoticeLine.DoesNotExist:
            raise DomainError("unknown_notice_line", "预告行不存在。")
        cond = _parse_condition(condition)
        if cond not in (Condition.PENDING_INSPECTION, Condition.AVAILABLE):
            raise DomainError("bad_receipt_condition", "实收只能记为待检或合格。")
        _positive_int(qty, "实收数量")
        owner, product = nline.notice.owner, nline.product
        location = _get_location(location_code)
        pas = _lock_availability([product.pk]) if cond == Condition.AVAILABLE else {}
        lot = StockLot.objects.create(
            product=product, source_type=StockLot.Source.RECEIPT, source_ref=f"RCV:{operation_id}",
            external_lot=external_lot or "", expiry_date=_as_date(expiry_date, "实收效期"),
        )
        balance = _balance_for(owner, product, lot, location, cond)
        _movement(op, StockMovement.Kind.RECEIPT, balance, qty, actor,
                  nline.notice.number, str(nline.line_no))
        balance.on_hand += qty
        _save(balance)
        if cond == Condition.AVAILABLE:
            pa = pas[product.pk]
            pa.sellable += qty
            _save(pa)
        ReceiptLine.objects.create(notice_line=nline, operation=op, lot=lot, qty_received=qty, condition=cond,
                                   location_code=location.code, actor=actor)
        return {"balance_id": balance.pk, "lot_id": lot.pk}

    return _run(operation_id, "confirm_receipt", payload, actor, fn)


def change_condition(*, operation_id, actor, balance_id, qty, to_condition) -> CommandResult:
    """Inspection result or hold: CONDITION_OUT + CONDITION_IN at the same location."""
    payload = dict(balance=balance_id, qty=qty, to=to_condition)

    def fn(op):
        target = _parse_condition(to_condition)
        _positive_int(qty, "数量")
        src_peek = StockBalance.objects.filter(pk=balance_id).first()
        if src_peek is None:
            raise DomainError("balance_missing", "库存记录不存在。")
        if src_peek.condition == target:
            raise DomainError("same_condition", "目标状态与当前状态相同。")
        touches_sellable = Condition.AVAILABLE in (src_peek.condition, target)
        pas = _lock_availability([src_peek.product_id]) if touches_sellable else {}
        dst_id = _ensure_balance(src_peek.owner, src_peek.product, src_peek.lot, src_peek.location, target)
        locked = _lock_balances([balance_id, dst_id])  # one sorted step: no A->B / B->A deadlock
        src, dst = locked[balance_id], locked[dst_id]
        if src.condition != src_peek.condition:
            # condition is part of a balance row's key and is never updated;
            # this guards the pre-lock decision above if that ever changes.
            raise DomainError("stale_condition", "库存状态在加锁前后不一致，请重试。")
        if qty > src.free:
            raise DomainError("insufficient_free", f"可改状态的数量只有 {src.free}（已分配的部分不能改，I2/I10）。")
        _movement(op, StockMovement.Kind.CONDITION_OUT, src, -qty, actor)
        _movement(op, StockMovement.Kind.CONDITION_IN, dst, qty, actor)
        src.on_hand -= qty
        dst.on_hand += qty
        _save(src, dst)
        if touches_sellable:
            pa = pas[src.product_id]
            pa.sellable += qty if target == Condition.AVAILABLE else -qty
            if pa.reserved > pa.sellable:
                raise DomainError("i11", f"改状态后可售 {pa.sellable} 小于占用 {pa.reserved}（I11），拒绝执行。")
            _save(pa)
            _assert_after_write([src.product_id])
        return {"from_balance_id": src.pk, "to_balance_id": dst.pk}

    return _run(operation_id, "change_condition", payload, actor, fn)


def move_stock(*, operation_id, actor, balance_id, qty, to_location_code) -> CommandResult:
    """Move unallocated stock between locations (I5). Allocated stock is refused (I10)."""
    payload = dict(balance=balance_id, qty=qty, to=to_location_code)

    def fn(op):
        _positive_int(qty, "移位数量")
        to_location = _get_location(to_location_code)
        src_peek = StockBalance.objects.filter(pk=balance_id).first()
        if src_peek is None:
            raise DomainError("balance_missing", "库存记录不存在。")
        if src_peek.location_id == to_location.pk:
            raise DomainError("same_location", "目标货位与来源货位相同。")
        dst_id = _ensure_balance(src_peek.owner, src_peek.product, src_peek.lot, to_location, src_peek.condition)
        locked = _lock_balances([balance_id, dst_id])  # one sorted step: no A->B / B->A deadlock
        src, dst = locked[balance_id], locked[dst_id]
        if qty > src.free:
            raise DomainError(
                "insufficient_free",
                f"可移动的数量只有 {src.free}；已被订单分配的库存不能移位（I10），请先改分配。",
            )
        _movement(op, StockMovement.Kind.MOVE_OUT, src, -qty, actor)
        _movement(op, StockMovement.Kind.MOVE_IN, dst, qty, actor)
        src.on_hand -= qty
        dst.on_hand += qty
        _save(src, dst)
        return {"from_balance_id": src.pk, "to_balance_id": dst.pk}

    return _run(operation_id, "move_stock", payload, actor, fn)


# --------------------------------------------------------------------------
# Orders: accept (reserve), allocate, ship, cancel line
# --------------------------------------------------------------------------

def accept_order(*, operation_id, actor, owner_code, number, lines, source_ref="") -> CommandResult:
    """Accept an order: reserves at product level immediately (D07, plan A of 3.1).

    lines: [{"product": code, "qty": int, "requested_expiry": date|None}]
    Rejected when product-level available is insufficient (I11); backorders
    are not allowed until the business confirms otherwise.
    """
    payload = dict(owner=owner_code, number=number, lines=lines, source_ref=source_ref)

    def fn(op):
        owner = _get_owner(owner_code)
        if not number:
            raise DomainError("bad_number", "订单号不能为空。")
        if not lines:
            raise DomainError("no_lines", "订单至少要有一行。")
        resolved = []
        need = defaultdict(int)
        for line in lines:
            product = _get_product(owner, line["product"])
            q = _positive_int(line["qty"], "订购数量")
            resolved.append((product, q, _as_date(line.get("requested_expiry"), "指定效期")))
            need[product.pk] += q
        pas = _lock_availability(need.keys())
        if Order.objects.filter(owner=owner, number=number).exists():
            raise DomainError("duplicate_order", f"货主 {owner.code} 的订单号 {number} 已存在。")
        for pid, q in need.items():
            pa = pas[pid]
            if pa.available < q:
                raise DomainError(
                    "insufficient_available",
                    f"商品 {pa.product.code} 可用只有 {pa.available}，订单需要 {q}（I11），拒绝接单。",
                )
        order = Order.objects.create(owner=owner, number=number, source_ref=source_ref, created_by=actor)
        created = []
        for i, (product, q, expiry) in enumerate(resolved, start=1):
            ol = OrderLine.objects.create(order=order, line_no=i, product=product, qty_ordered=q,
                                          requested_expiry=expiry, qty_unallocated=q,
                                          source_line=str(lines[i - 1].get("source_line") or "")[:40])
            ReservationEntry.objects.create(operation=op, order_line=ol, kind=ReservationEntry.Kind.RESERVE,
                                            qty=q, actor=actor)
            created.append(ol)
        for pid, q in need.items():
            pas[pid].reserved += q
            _save(pas[pid])
        _assert_after_write(need.keys(), created)
        return {"order_id": order.pk, "line_ids": [ol.pk for ol in created]}

    return _run(operation_id, "accept_order", payload, actor, fn)


def allocate_line(*, operation_id, actor, line_id, picks) -> CommandResult:
    """Employee chooses lot/location quantities for a line (A02).

    picks: [{"balance_id": int, "qty": int}]. Converts the line's unallocated
    reservation into allocations; product-level reserved is unchanged.
    """
    payload = dict(line=line_id, picks=picks)

    def fn(op):
        try:
            line = OrderLine.objects.select_related("order__owner", "product").get(pk=line_id)
        except OrderLine.DoesNotExist:
            raise DomainError("unknown_line", "订单行不存在。")
        if not picks:
            raise DomainError("no_picks", "请至少选择一个批次/货位。")
        ids = [p["balance_id"] for p in picks]
        if len(ids) != len(set(ids)):
            raise DomainError("duplicate_pick", "同一库存记录不能在一次分配里出现两次。")
        _lock_availability([line.product_id])
        balances = _lock_balances(ids)
        line.refresh_from_db()  # re-read under lock
        total = 0
        for p in picks:
            q = _positive_int(p["qty"], "分配数量")
            b = balances[p["balance_id"]]
            if b.owner_id != line.order.owner_id or b.product_id != line.product_id:
                raise DomainError("i3", "只能分配同一货主、同一商品的库存（I3）。")
            if b.condition != Condition.AVAILABLE:
                raise DomainError("i2_condition",
                                  f"{b.location.code} 的这批货状态是「{b.get_condition_display()}」，不能分配（I2）。")
            if line.requested_expiry and b.lot.expiry_date != line.requested_expiry:
                raise DomainError("i8", f"订单指定效期 {line.requested_expiry}，所选批次效期为 "
                                        f"{b.lot.expiry_date or '未知'}，不能改用（I8）。")
            if q > b.free:
                raise DomainError("i2_free", f"{b.location.code} 可分配只有 {b.free}，要分配 {q}（I2）。")
            total += q
        if total > line.qty_unallocated:
            raise DomainError("i4", f"本行未分配的占用只有 {line.qty_unallocated}，要分配 {total}（I4）。")
        result = []
        for p in picks:
            b, q = balances[p["balance_id"]], p["qty"]
            alloc = Allocation.objects.create(order_line=line, balance=b, qty_allocated=q,
                                              location_code=b.location.code, expiry_date=b.lot.expiry_date,
                                              created_by=actor)
            ReservationEntry.objects.create(operation=op, order_line=line, kind=ReservationEntry.Kind.CONVERT,
                                            qty=-q, actor=actor)
            ReservationEntry.objects.create(operation=op, order_line=line, allocation=alloc,
                                            kind=ReservationEntry.Kind.ALLOCATE, qty=q, actor=actor)
            b.allocated += q
            _save(b)
            result.append(alloc.pk)
        line.qty_unallocated -= total
        line.save(update_fields=["qty_unallocated"])
        _assert_after_write([line.product_id], [line])
        return {"allocation_ids": result}

    return _run(operation_id, "allocate_line", payload, actor, fn)


def ship(*, operation_id, actor, order_id, items) -> CommandResult:
    """Ship allocated quantities: SHIP movement + CONSUME entry in one transaction (I6).

    Physical stock and reservation fall together, so available does not
    change again (D07: shipping never deducts available a second time).
    items: [{"allocation_id": int, "qty": int}]
    """
    payload = dict(order=order_id, items=items)

    def fn(op):
        try:
            order = Order.objects.get(pk=order_id)
        except Order.DoesNotExist:
            raise DomainError("unknown_order", "订单不存在。")
        if not items:
            raise DomainError("no_items", "请至少填写一项发货数量。")
        ids = [i["allocation_id"] for i in items]
        if len(ids) != len(set(ids)):
            raise DomainError("duplicate_item", "同一分配不能在一次发货里出现两次。")
        allocs = {a.pk: a for a in Allocation.objects.select_related("order_line").filter(pk__in=ids)}
        if len(allocs) != len(ids) or any(a.order_line.order_id != order.pk for a in allocs.values()):
            raise DomainError("unknown_allocation", "分配不属于这张订单。")
        product_ids = {a.order_line.product_id for a in allocs.values()}
        pas = _lock_availability(product_ids)
        balances = _lock_balances([a.balance_id for a in allocs.values()])
        shipment = Shipment.objects.create(order=order, operation=op, actor=actor)
        lines = set()
        for item in items:
            a = allocs[item["allocation_id"]]
            a.refresh_from_db()
            q = _positive_int(item["qty"], "发货数量")
            if q > a.qty_open:
                raise DomainError("i4", f"这项分配未发数量只有 {a.qty_open}，要发 {q}。")
            b = balances[a.balance_id]
            mv = _movement(op, StockMovement.Kind.SHIP, b, -q, actor, order.number, str(a.order_line.line_no))
            ShipmentLine.objects.create(shipment=shipment, allocation=a, qty=q, movement=mv)
            ReservationEntry.objects.create(operation=op, order_line=a.order_line, allocation=a,
                                            kind=ReservationEntry.Kind.CONSUME, qty=-q, actor=actor)
            a.qty_shipped += q
            a.save(update_fields=["qty_shipped"])
            b.on_hand -= q
            b.allocated -= q
            if b.on_hand < 0 or b.allocated < 0:
                raise DomainError("i1", "发货后库存为负（I1），拒绝执行。")
            pa = pas[a.order_line.product_id]
            pa.sellable -= q
            pa.reserved -= q
            lines.add(a.order_line)
        _save(*balances.values(), *pas.values())
        _assert_after_write(product_ids, lines)
        return {"shipment_id": shipment.pk}

    return _run(operation_id, "ship", payload, actor, fn)


def cancel_line(*, operation_id, actor, line_id, qty=None, reason=LineCancellation.Reason.UNPAID) -> CommandResult:
    """Cancel the not-yet-shipped part of one order line (A10).

    Releases the unallocated reservation first, then open allocations in
    creation order. qty=None cancels everything still cancellable. Shipped
    quantity can never be cancelled. A second cancel with a new operation_id
    when nothing is left is rejected and changes nothing.
    """
    payload = dict(line=line_id, qty=qty, reason=reason)

    def fn(op):
        if reason not in LineCancellation.Reason.values:
            raise DomainError("bad_reason", "请选择取消原因。")
        try:
            line = OrderLine.objects.select_related("order").get(pk=line_id)
        except OrderLine.DoesNotExist:
            raise DomainError("unknown_line", "订单行不存在。")
        pas = _lock_availability([line.product_id])
        allocs = list(line.allocations.order_by("pk"))
        balances = _lock_balances([a.balance_id for a in allocs]) if allocs else {}
        line.refresh_from_db()
        for a in allocs:
            a.refresh_from_db()
        remaining = line.qty_unallocated + sum(a.qty_open for a in allocs)
        if remaining == 0:
            raise DomainError("nothing_to_cancel", "这一行已无可取消数量（已发出的不能取消）。")
        want = remaining if qty is None else _positive_int(qty, "取消数量")
        if want > remaining:
            raise DomainError("too_much", f"这一行最多还能取消 {remaining}。")
        left = want
        take = min(left, line.qty_unallocated)
        if take:
            ReservationEntry.objects.create(operation=op, order_line=line, kind=ReservationEntry.Kind.RELEASE,
                                            qty=-take, actor=actor)
            line.qty_unallocated -= take
            left -= take
        for a in allocs:
            if not left:
                break
            take = min(left, a.qty_open)
            if not take:
                continue
            ReservationEntry.objects.create(operation=op, order_line=line, allocation=a,
                                            kind=ReservationEntry.Kind.RELEASE, qty=-take, actor=actor)
            a.qty_released += take
            a.save(update_fields=["qty_released"])
            b = balances[a.balance_id]
            b.allocated -= take
            _save(b)
            left -= take
        line.qty_cancelled += want
        line.save(update_fields=["qty_unallocated", "qty_cancelled"])
        pa = pas[line.product_id]
        pa.reserved -= want
        _save(pa)
        LineCancellation.objects.create(order_line=line, operation=op, qty=want, reason=reason, actor=actor)
        _assert_after_write([line.product_id], [line])
        return {"cancelled": want}

    return _run(operation_id, "cancel_line", payload, actor, fn)


# --------------------------------------------------------------------------
# Reconciliation: rebuild projections from append-only rows (I1-I11)
# --------------------------------------------------------------------------

def check_invariants() -> list[str]:
    """Return a list of violations; empty means consistent.

    Also usable as the restore/upgrade reconciliation check in
    docs/deployment.md 5.3 once ported to T06.
    """
    problems = []
    for b in StockBalance.objects.select_related("lot", "location", "product"):
        mv = b.movements.aggregate(s=Sum("qty"))["s"] or 0
        if mv != b.on_hand:
            problems.append(f"余额 {b.pk}: on_hand {b.on_hand} ≠ 流水合计 {mv}")
        if b.on_hand < 0:
            problems.append(f"余额 {b.pk}: on_hand 为负（I1）")
        open_alloc = sum(a.qty_open for a in b.allocations.all())
        if open_alloc != b.allocated:
            problems.append(f"余额 {b.pk}: allocated {b.allocated} ≠ 未发分配合计 {open_alloc}")
        if b.allocated > b.on_hand:
            problems.append(f"余额 {b.pk}: 占用超过实物（I2）")
        if b.allocated and b.condition != Condition.AVAILABLE:
            problems.append(f"余额 {b.pk}: 非合格库存被占用（I2）")
    for a in Allocation.objects.select_related("order_line__order", "balance__lot"):
        line = a.order_line
        if a.balance.owner_id != line.order.owner_id or a.balance.product_id != line.product_id:
            problems.append(f"分配 {a.pk}: 货主或商品不一致（I3）")
        if line.requested_expiry and a.balance.lot.expiry_date != line.requested_expiry:
            problems.append(f"分配 {a.pk}: 效期与订单指定不一致（I8）")
        entries = a.entries.aggregate(s=Sum("qty"))["s"] or 0
        if entries != a.qty_open:
            problems.append(f"分配 {a.pk}: 占用流水合计 {entries} ≠ 未发 {a.qty_open}")
        shipped = a.shipment_lines.aggregate(s=Sum("qty"))["s"] or 0
        if shipped != a.qty_shipped:
            problems.append(f"分配 {a.pk}: 发货行合计 {shipped} ≠ 已发 {a.qty_shipped}")
    for line in OrderLine.objects.select_related("order"):
        unalloc = line.reservation_entries.filter(allocation__isnull=True).aggregate(s=Sum("qty"))["s"] or 0
        if unalloc != line.qty_unallocated:
            problems.append(f"订单行 {line.pk}: 未分配占用 {line.qty_unallocated} ≠ 流水合计 {unalloc}")
        cancelled = line.cancellations.aggregate(s=Sum("qty"))["s"] or 0
        if cancelled != line.qty_cancelled:
            problems.append(f"订单行 {line.pk}: 已取消 {line.qty_cancelled} ≠ 取消记录合计 {cancelled}")
        problem = _line_conservation_problem(line)
        if problem:
            problems.append(problem)
    for pa in ProductAvailability.objects.select_related("product"):
        sellable = (StockBalance.objects.filter(product=pa.product, condition=Condition.AVAILABLE)
                    .aggregate(s=Sum("on_hand"))["s"] or 0)
        reserved = (ReservationEntry.objects.filter(order_line__product=pa.product)
                    .aggregate(s=Sum("qty"))["s"] or 0)
        if sellable != pa.sellable:
            problems.append(f"商品 {pa.product}: sellable {pa.sellable} ≠ 合格实物合计 {sellable}")
        if reserved != pa.reserved:
            problems.append(f"商品 {pa.product}: reserved {pa.reserved} ≠ 占用流水合计 {reserved}")
        if pa.reserved > pa.sellable:
            problems.append(f"商品 {pa.product}: 占用超过可售（I11）")
        problems.extend(f"商品 {pa.product}: {p}" for p in _expiry_shortfalls(pa.product_id))
    for sl in ShipmentLine.objects.select_related("movement", "shipment"):
        consume = ReservationEntry.objects.filter(operation=sl.shipment.operation, allocation=sl.allocation,
                                                  kind=ReservationEntry.Kind.CONSUME).aggregate(s=Sum("qty"))["s"]
        if sl.movement.qty != -sl.qty or consume != -sl.qty:
            problems.append(f"发货行 {sl.pk}: SHIP 流水与 CONSUME 占用不一致（I6）")
    pair_kinds = {
        StockMovement.Kind.MOVE_OUT, StockMovement.Kind.MOVE_IN,
        StockMovement.Kind.CONDITION_OUT, StockMovement.Kind.CONDITION_IN,
    }
    sums = defaultdict(int)
    for m in StockMovement.objects.filter(kind__in=pair_kinds).select_related("balance"):
        sums[(m.operation_id, m.balance.lot_id)] += m.qty
    for (op_id, lot_id), total in sums.items():
        if total:
            problems.append(f"操作 {op_id}: 批次 {lot_id} 移位/改状态增减之和 {total} ≠ 0（I5）")
    return problems
