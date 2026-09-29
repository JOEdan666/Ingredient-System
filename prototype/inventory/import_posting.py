"""Post a confirmed ImportBatch through the domain commands (never directly).

One batch = one database transaction: either every line is posted or
nothing is.  Candidate mapping (recorded in docs/HANDOFF.md, not customer-
confirmed):

- 库存表 -> opening balance (post_opening), once per owner: a stock snapshot
  posted on top of existing stock would count the same goods twice.
- 验货纸 -> receipt notice (create_notice).  The observed sheet's received
  column is empty, so it is expected goods, not received stock (AGENTS.md:
  expected arrival is not received stock).  Staff confirm the actual count
  on the 收货 page.
- PDF 送货单 -> accepted order (accept_order), which reserves available stock.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from . import domain
from .domain import DomainError
from .import_preview import recheck, refresh_line
from .models import ImportBatch, Location, Owner, Product, StockMovement

NG_LOCATION_PREFIX = "NG:"


def _owner(code: str) -> Owner:
    owner = Owner.objects.filter(code=code).first()
    return owner or domain.create_owner(code, code)


def _product(owner: Owner, line: dict) -> Product:
    product = Product.objects.filter(owner=owner, code=line["code"]).first()
    return product or domain.create_product(owner, line["code"], name_zh=(line.get("name") or "")[:100])


def _location_code(line: dict) -> str:
    """Stock rows keep their 仓位.  On-hold rows (warehouse ending in NG) have no
    仓位 in the observed file, so they go to one location per NG warehouse."""
    if line.get("location"):
        return line["location"][:40]
    return (NG_LOCATION_PREFIX + (line.get("warehouse") or "未知"))[:40]


def _location(code: str) -> Location:
    location = Location.objects.filter(code=code).first()
    return location or domain.create_location(code)


def confirm_units(batch: ImportBatch, choices: dict[int, tuple[str, int | None]], actor: str) -> int:
    """Resolve unit_needs_confirmation rows from a person's explicit choice.

    choices: {row: ("EA", None) | ("CS", pieces_per_case)}.  Returns rows resolved.
    """
    if not actor:
        raise DomainError("missing_actor", "必须选择操作人：单位确认要记下是谁确认的。")
    if batch.status != ImportBatch.Status.PREVIEW:
        raise DomainError("already_posted", "这份文件已经入账，不能再改。")
    resolved = 0
    for line in batch.lines:
        if line["row"] not in choices or not any(e["code"] == "unit_needs_confirmation" for e in line["errors"]):
            continue
        unit, per_case = choices[line["row"]]
        printed = line.get("printed_qty")
        if not isinstance(printed, int) or printed <= 0:
            raise DomainError("bad_quantity", f"第 {line['row']} 行没有可用的印刷数量，无法换算。")
        if unit == "EA":
            line["qty"] = printed
            note = f"{actor} 确认：数量栏 {printed} 按件"
        elif unit == "CS":
            if not isinstance(per_case, int) or per_case <= 0:
                raise DomainError("bad_quantity", f"第 {line['row']} 行选了按箱，必须填每箱件数（正整数）。")
            line["qty"] = printed * per_case
            note = f"{actor} 确认：数量栏 {printed} 按箱 × 每箱 {per_case} 件"
        else:
            continue
        line["unit"] = "EA"
        line["unit_note"] = note
        line["errors"] = [e for e in line["errors"] if e["code"] != "unit_needs_confirmation"]
        refresh_line(line)
        resolved += 1
    if resolved:
        batch.save(update_fields=["lines"])
    return resolved


def blocker_for(batch: ImportBatch) -> str | None:
    """A reason the whole batch cannot be posted that no line edit can fix; shown before confirming."""
    if batch.status == ImportBatch.Status.POSTED:
        return None
    twin = ImportBatch.objects.filter(file_sha256=batch.file_sha256, status=ImportBatch.Status.POSTED).exclude(pk=batch.pk).first()
    if twin is not None:
        when = timezone.localtime(twin.posted_at)
        return f"同一个文件已经在 {when:%Y-%m-%d %H:%M} 入账过（导入记录 #{twin.pk}），拒绝重复入账。"
    if batch.kind == ImportBatch.Kind.STOCK and StockMovement.objects.filter(balance__owner__code=batch.owner_code).exists():
        return (f"货主 {batch.owner_code} 已经有库存记录。库存表只能在开始使用时作为期初导入一次，"
                "否则同一批货会被算两次。如果这是另一家客户的库存表，请返回上一步选别的货主。")
    return None


def _check_postable(batch: ImportBatch):
    if batch.status == ImportBatch.Status.POSTED:
        raise DomainError("already_posted", "这份文件已经入账过了，不会再入一次。")
    if not batch.ready:
        raise DomainError("not_ready", f"还有 {batch.blocked_count} 行需要人工处理，整份不能入账。")
    reason = blocker_for(batch)
    if reason:
        raise DomainError("blocked", reason)


EXPORT_BASIS = {
    "physical": "仓库实物数（未扣未出货订单）",
    "net": "已扣掉未出货订单",
}


def stock_snapshot_for(owner_code: str) -> ImportBatch | None:
    return (ImportBatch.objects.filter(owner_code=owner_code, kind=ImportBatch.Kind.STOCK,
                                       status=ImportBatch.Status.POSTED).order_by("pk").first())


def order_needs_cutover_check(batch: ImportBatch) -> str | None:
    """A PDF order dated on/before the owner's stock snapshot may already be inside
    that snapshot's numbers; posting it again would deduct it twice (AGENTS.md:
    do not replay deducted orders).  Returns the question a person must answer."""
    if batch.kind != ImportBatch.Kind.PDF_ORDER:
        return None
    snap = stock_snapshot_for(batch.owner_code)
    if snap is None or snap.snapshot_at is None:
        return None
    snap_day = timezone.localtime(snap.snapshot_at).date()
    if batch.doc_date is not None and batch.doc_date > snap_day:
        return None
    printed = batch.doc_date.isoformat() if batch.doc_date else "（单据上没有可读的日期）"
    return (f"这张单据日期 {printed} 不晚于库存表导出日 {snap_day}。如果它在导出时已经发货或已从客户系统库存里扣掉，"
            "再接单会重复扣减。")


def post_batch(batch_id: int, actor: str, *, snapshot_at=None, export_basis: str = "",
               confirm_not_in_snapshot: bool = False) -> dict:
    if not actor:
        raise DomainError("missing_actor", "必须选择操作人。")
    with transaction.atomic():
        batch = ImportBatch.objects.select_for_update().get(pk=batch_id)
        recheck(batch)
        _check_postable(batch)
        owner = _owner(batch.owner_code)
        op = f"imp{batch.pk}"
        if batch.kind == ImportBatch.Kind.STOCK:
            # Cutover boundary (Q05 is unanswered): a person states when the sheet
            # was exported and what its numbers mean; it is recorded, never guessed.
            if snapshot_at is None:
                raise DomainError("missing_snapshot", "请填写这份库存表是什么时候从客户系统导出的（期初的时间点）。")
            if timezone.is_naive(snapshot_at):
                snapshot_at = timezone.make_aware(snapshot_at)
            if snapshot_at > timezone.now():
                raise DomainError("bad_snapshot", "导出时间不能晚于现在。")
            if export_basis not in EXPORT_BASIS:
                raise DomainError("missing_basis", "请选择表里的数字是「仓库实物数」还是「已扣掉未出货订单」。")
            if export_basis == "net":
                raise DomainError(
                    "net_export",
                    "表里的数已经扣掉了未出货订单：用它建期初，之后再导入这些订单会重复扣减。"
                    "目前只支持用仓库实物数建期初，请从客户系统导出实物库存后再导入。",
                )
            batch.snapshot_at = snapshot_at
            batch.export_basis = export_basis
            posted = 0
            for line in batch.lines:
                _product(owner, line)
                location = _location(_location_code(line))
                domain.post_opening(
                    operation_id=f"{op}r{line['row']}", actor=actor, owner_code=owner.code,
                    product_code=line["code"], source_ref=f"IMP{batch.pk}:{line['row']}", external_lot="",
                    expiry_date=line["expiry"], location_code=location.code, condition=line["condition"],
                    qty=line["qty"], source_doc=f"{batch.external_doc_no} 导出于 {timezone.localtime(snapshot_at):%Y-%m-%d %H:%M}"[:80],
                )
                posted += 1
            result = {"kind": "stock", "lines": posted,
                      "snapshot_at": timezone.localtime(snapshot_at).strftime("%Y-%m-%d %H:%M"),
                      "export_basis": EXPORT_BASIS[export_basis],
                      "sellable": sum(l["qty"] for l in batch.lines if l["condition"] == "AVAILABLE"),
                      "hold": sum(l["qty"] for l in batch.lines if l["condition"] != "AVAILABLE")}
        elif batch.kind == ImportBatch.Kind.INSPECTION:
            for line in batch.lines:
                _product(owner, line)
            res = domain.create_notice(
                operation_id=op, actor=actor, owner_code=owner.code, number=batch.external_doc_no,
                lines=[{"product": l["code"], "qty": l["qty"], "expiry": l["expiry"], "external_lot": ""}
                       for l in batch.lines],
            )
            result = {"kind": "inspection", "notice_id": res.result["notice_id"], "lines": len(batch.lines),
                      "qty": sum(l["qty"] for l in batch.lines)}
        else:
            question = order_needs_cutover_check(batch)
            if question and not confirm_not_in_snapshot:
                raise DomainError("cutover_unconfirmed", question + "请核对后勾选确认再入账。")
            res = domain.accept_order(
                operation_id=op, actor=actor, owner_code=owner.code, number=batch.external_doc_no,
                lines=[{"product": l["code"], "qty": l["qty"], "requested_expiry": l["expiry"],
                        "source_line": f"序号{l['seq']}" if l.get("seq") else f"第{l['row']}行"} for l in batch.lines],
                source_ref=f"导入#{batch.pk} {batch.file_name} sha256:{batch.file_sha256[:12]}"[:120],
            )
            result = {"kind": "pdf_order", "order_id": res.result["order_id"], "lines": len(batch.lines),
                      "qty": sum(l["qty"] for l in batch.lines),
                      "cutover_confirmed_by": actor if question else None}
        batch.status = ImportBatch.Status.POSTED
        batch.posted_at = timezone.now()
        batch.posted_by = actor
        batch.result = result
        batch.save(update_fields=["status", "posted_at", "posted_by", "result", "snapshot_at", "export_basis"])
        problems = domain.check_invariants()
        if problems:
            raise DomainError("invariant", "入账后库存规则检查不通过，已全部撤销：" + "；".join(problems[:3]))
    return result
