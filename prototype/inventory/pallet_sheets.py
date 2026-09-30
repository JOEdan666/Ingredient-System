"""Pallet header sheets (板头纸): a printable label per pallet for one delivery.

Layout follows the customer's Word sample (structure only, no values):
收貨客戶 (large, centred) / 送貨地址 / 送貨時間 / 訂單編號 (one pallet may carry
several orders, printed "A & B") / 共N板 (i/N).  This module only stores
what a person typed; it never reads or writes stock (acceptance: repeated
export does not affect inventory).
"""

from __future__ import annotations

from django.db import transaction

from .domain import DomainError
from .models import Order, PalletSheet

MAX_PALLETS = 99
MAX_ORDER_NUMBERS_LEN = 200


def _text(value, field: str, max_len: int) -> str:
    text = " ".join((value or "").split())
    if not text:
        raise DomainError("missing_field", f"请填写{field}。")
    if len(text) > max_len:
        raise DomainError("too_long", f"{field}最多 {max_len} 个字。")
    return text


def create_sheet(*, order_ids, ship_to, address, delivery_time, pallet_count, actor) -> PalletSheet:
    if not actor:
        raise DomainError("missing_actor", "必须选择操作人。")
    ids = sorted({int(i) for i in order_ids})
    if not ids:
        raise DomainError("no_orders", "至少选择一张订单。")
    orders = list(Order.objects.select_related("owner").filter(pk__in=ids).order_by("number"))
    if len(orders) != len(ids):
        raise DomainError("unknown_order", "选中的订单有不存在的，请刷新页面重选。")
    owners = {o.owner_id for o in orders}
    if len(owners) != 1:
        raise DomainError("mixed_owner", "一张板头纸只能放同一个货主的订单。")
    order_numbers = " & ".join(o.number for o in orders)
    if len(order_numbers) > MAX_ORDER_NUMBERS_LEN:
        raise DomainError(
            "order_numbers_too_long",
            f"所选订单编号合并后超过 {MAX_ORDER_NUMBERS_LEN} 个字，请减少订单数量。",
        )
    try:
        count = int(pallet_count)
    except (TypeError, ValueError):
        raise DomainError("bad_count", "板数必须是整数。")
    if not 1 <= count <= MAX_PALLETS:
        raise DomainError("bad_count", f"板数要在 1 到 {MAX_PALLETS} 之间。")
    with transaction.atomic():
        sheet = PalletSheet.objects.create(
            owner=orders[0].owner,
            order_numbers=order_numbers,
            ship_to=_text(ship_to, "收貨客戶", 100),
            address=_text(address, "送貨地址", 200),
            delivery_time=_text(delivery_time, "送貨時間", 60),
            pallet_count=count,
            created_by=actor,
        )
        sheet.orders.set(orders)
    return sheet


def pages(sheet: PalletSheet) -> list[dict]:
    """One page per pallet, numbered i of N."""
    return [{"index": i, "total": sheet.pallet_count} for i in range(1, sheet.pallet_count + 1)]


def suggestions(owner_id: int) -> dict:
    """Values typed before for this owner, newest first, to avoid retyping."""
    previous = PalletSheet.objects.filter(owner_id=owner_id).order_by("-pk")
    seen = {"ship_to": [], "address": [], "delivery_time": []}
    for sheet in previous[:50]:
        for key in seen:
            value = getattr(sheet, key)
            if value not in seen[key]:
                seen[key].append(value)
    return seen
