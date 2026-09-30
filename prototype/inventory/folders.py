"""Group the product summary into brand folders for the inventory page (display only).

The brand is read from the start of the product name: a leading Latin word
("ADVANCE爱旺斯 …" -> "ADVANCE") or a short first word ("原食生鲜 …").
Anything else, and brands with only a couple of products, go to 「其他」.
Nothing here changes stock; it only arranges rows for reading.
"""

from __future__ import annotations

import re
from collections import defaultdict

OTHER = "其他"
MIN_FOLDER = 3  # smaller brands are merged into 「其他」 so nobody opens a folder for one item
_LATIN = re.compile(r"[A-Za-z][A-Za-z&'.-]*")


def brand_of(name: str) -> str:
    words = (name or "").split()
    if not words:
        return OTHER
    match = _LATIN.match(words[0])
    if match:
        return match.group(0).upper()
    return words[0] if len(words[0]) <= 6 else OTHER


def matches(summary: dict, query: str) -> bool:
    q = query.strip().lower()
    return not q or q in summary["product"].lower() or q in (summary["name"] or "").lower()


def build(summaries: list[dict], balances: list[dict], query: str = "") -> list[dict]:
    by_product = defaultdict(list)
    for b in balances:
        by_product[(b["owner"], b["product"])].append(b)
    groups = defaultdict(list)
    for s in summaries:
        groups[brand_of(s["name"])].append(s)
    merged = defaultdict(list)
    for brand, items in groups.items():
        merged[brand if len(items) >= MIN_FOLDER and brand != OTHER else OTHER].extend(items)
    folders = []
    for brand, items in merged.items():
        shown = [dict(s, balances=by_product.get((s["owner"], s["product"]), [])) for s in items if matches(s, query)]
        if not shown:
            continue
        folders.append({
            "brand": brand, "products": shown, "count": len(shown),
            "available": sum(s["available"] for s in shown),
            "not_sellable": sum(s["not_sellable"] for s in shown),
        })
    folders.sort(key=lambda f: (f["brand"] == OTHER, -f["count"], f["brand"]))
    return folders
