"""Rebuild item lines from the text pypdf extracts from a delivery/packing list.

Preview only: nothing here writes stock. The observed layout is documented in
fixtures/synthetic/real-format/README.md and docs/import-contract.md section 10.

pypdf emits the page bottom-up, so item lines arrive in descending Seq order
and the quantity column is a separate run of lines that does not sit next to
its item. On the two locally checked real files, pairing the k-th quantity
line with the k-th item line (both in extraction order) matched every net
weight, while pairing each item with the quantity line directly above it did
not. The pairing is still only trusted when the counts agree, the Seq numbers
are 1..n, and the printed totals equal the sums; otherwise the whole document
is blocked for a person to read instead of guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .importer import ImportLine, RowError

_MONTHS = {m: i for i, m in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), start=1)}
_DATE = re.compile(r"^(\d{1,2})-([A-Za-z]{3})-(\d{2})$")
# SIZE is a few number/abbreviation tokens (1.5kg, 12 x 5.5 oz.); anything
# else before the unit means the unit column was not where we expect it.
_SIZE_TOKEN = r"(?:\d+(?:\.\d+)?[A-Za-z]*\.?|x|[A-Za-z]{1,3}\.)"
_ITEM = re.compile(rf"^(\d+) (\d{{5,}}) ({_SIZE_TOKEN}(?: {_SIZE_TOKEN}){{0,3}}) (EA|CS) (.*)$")
_ITEM_LIKE = re.compile(r"^\d+ \d{5,} ")
_QTY = re.compile(r"^(\d+) ([A-Z]{2,4}) (\d+\.\d+)(?: (\S+))?$")
_TOTALS = re.compile(r"^(\d+) (\d+\.\d+)$")
_OLD_CODE = re.compile(r"\(\s*Old\s+Code\s+(\w+)\s*\)")
_SIZE_KG = re.compile(r"^(\d+(?:\.\d+)?)kg$")
_DOC_NO = re.compile(r"INV No\.\s*(\S+)")
_DOC_DATE = re.compile(r"Date:\s*(\S+)")
_CUST = re.compile(r"Cust#:\s*(\S+)")
# Lines that end a wrapped description. Address and contact lines are not
# parsed at all: their Chinese text comes out of pypdf garbled.
_STOP_PREFIXES = ("Seq ", "Description ", "Delivery", "Attn:", "Cust#", "Messrs.", "INV No.",
                  "Tel:", "Total :", "Page ")
# Every observed wrap is a single extra line; more than that is not trusted.
_MAX_CONTINUATION = 1


@dataclass
class PdfOrderPreview:
    owner: str
    external_doc_no: str | None
    doc_date: date | None
    customer_ref: str | None
    lines: list[ImportLine]
    batch_errors: list[RowError] = field(default_factory=list)

    @property
    def postable(self) -> bool:
        return not self.batch_errors and bool(self.lines) and all(line.postable for line in self.lines)


def _block(row: int, field_name: str, code: str, message: str) -> RowError:
    return RowError(row, field_name, code, message, "block")


def parse_short_date(raw: str | None) -> date | None:
    """`1-Jul-27` -> date(2027, 7, 1); anything else -> None (never guessed)."""
    match = _DATE.fullmatch(raw or "")
    if not match or match.group(2) not in _MONTHS:
        return None
    try:
        return date(2000 + int(match.group(3)), _MONTHS[match.group(2)], int(match.group(1)))
    except ValueError:
        return None


def _header(lines: list[str], errors: list[RowError]) -> tuple[str | None, date | None, str | None]:
    found: dict[str, str] = {}
    for text in lines:
        for key, pattern in (("doc_no", _DOC_NO), ("date", _DOC_DATE), ("cust", _CUST)):
            match = pattern.search(text)
            if match and key not in found:
                found[key] = match.group(1)
    if "doc_no" not in found:
        errors.append(_block(0, "external_doc_no", "doc_no_missing", "找不到 INV No. 单号"))
    doc_date = parse_short_date(found.get("date"))
    if doc_date is None:
        errors.append(_block(0, "doc_date", "doc_date_unclear", "单据日期缺失或格式无法确认"))
    return found.get("doc_no"), doc_date, found.get("cust")


def parse_pdf_order_text(text: str, *, owner: str) -> PdfOrderPreview:
    """Parse extracted text into preview lines sorted by Seq; never posts stock."""
    if not owner:
        raise ValueError("送货单没有货主栏，调用方必须明确提供货主")
    # Real extractions carry trailing spaces at wrap points.
    source = [line.strip() for line in text.splitlines()]
    batch_errors: list[RowError] = []
    doc_no, doc_date, cust = _header(source, batch_errors)

    items: list[dict] = []  # extraction order
    quantities: list[tuple[int, re.Match]] = []
    totals: re.Match | None = None
    current: dict | None = None
    for number, text_line in enumerate(source, start=1):
        item = _ITEM.fullmatch(text_line)
        qty = _QTY.fullmatch(text_line)
        if item:
            current = {"row": number, "match": item, "continuation": []}
            items.append(current)
            continue
        if _ITEM_LIKE.match(text_line):
            batch_errors.append(_block(number, "line", "item_line_unrecognized",
                                       "像商品行但单位或栏位无法识别，需人工核对"))
            current = None
        elif qty:
            quantities.append((number, qty))
            current = None
        elif _TOTALS.fullmatch(text_line):
            if totals is not None:
                batch_errors.append(_block(number, "totals", "totals_repeated", "出现多个合计行"))
            totals = _TOTALS.fullmatch(text_line)
            current = None
        elif current is not None and text_line and not text_line.startswith(_STOP_PREFIXES):
            current["continuation"].append(text_line)
        else:
            current = None

    if not items:
        batch_errors.append(_block(0, "*", "no_item_lines", "没有识别到商品行"))
    seqs = [int(i["match"].group(1)) for i in items]
    if len(quantities) != len(items):
        batch_errors.append(_block(0, "quantity", "line_count_mismatch",
                                   f"数量行 {len(quantities)} 条、商品行 {len(items)} 条，不能配对"))
    if any(a <= b for a, b in zip(seqs, seqs[1:])):
        batch_errors.append(_block(0, "seq", "order_unrecognized",
                                   "商品行不是已观察到的倒序，配对规则不适用"))
    if sorted(seqs) != list(range(1, len(seqs) + 1)):
        batch_errors.append(_block(0, "seq", "seq_gap", "序号不是从 1 连续编号，可能漏行"))
    paired = len(quantities) == len(items) and not any(e.code == "order_unrecognized" for e in batch_errors)

    lines: list[ImportLine] = []
    for index, info in enumerate(items):
        lines.append(_build_line(info, quantities[index] if paired else None, owner, doc_no))
    lines.sort(key=lambda line: line.raw_values["seq"])

    if totals is None:
        batch_errors.append(_block(0, "totals", "totals_missing", "找不到合计行，无法核对配对"))
    elif paired:
        qty_sum = sum(int(q.group(1)) for _, q in quantities)
        net_sum = sum(Decimal(q.group(3)) for _, q in quantities)
        if qty_sum != int(totals.group(1)) or net_sum != Decimal(totals.group(2)):
            batch_errors.append(_block(0, "totals", "totals_mismatch",
                                       f"各行合计 {qty_sum} / {net_sum} 与单据合计不一致"))
    if batch_errors:
        # A line is only as trustworthy as the document it was paired in.
        for line in lines:
            line.errors.append(_block(line.row_number, "*", "document_blocked", "整单未通过结构核对"))
    return PdfOrderPreview(owner, doc_no, doc_date, cust, lines, batch_errors)


def _build_line(info: dict, quantity: tuple[int, re.Match] | None, owner: str,
                doc_no: str | None) -> ImportLine:
    row = info["row"]
    item = info["match"]
    errors: list[RowError] = []
    if len(info["continuation"]) > _MAX_CONTINUATION:
        errors.append(_block(row, "name", "description_unclear", "描述跨了多行，可能混入其它文字，需人工核对"))
    joined = " ".join([item.group(5), *info["continuation"]]).strip()
    old = _OLD_CODE.search(joined)
    if old:
        description = (joined[:old.start()] + joined[old.end():]).strip()
    else:
        description = joined
        if re.search(r"\(\s*Old\b", joined):
            errors.append(_block(row, "old_code", "old_code_unclear", "旧编码写法无法确认"))
    size, item_unit = item.group(3), item.group(4)
    raw = {"seq": int(item.group(1)), "item_line": row, "size": size, "item_unit": item_unit,
           "description_raw": joined, "old_code": old.group(1) if old else None,
           "quantity_line": None, "net_weight": None}

    count = unit = expiry_raw = expiry = None
    status = "unknown"
    base = None
    if quantity is None:
        errors.append(_block(row, "quantity", "quantity_unpaired", "数量行无法可靠配对，需人工核对"))
    else:
        q_row, q = quantity
        count, unit, expiry_raw = int(q.group(1)), q.group(2), q.group(4)
        raw["quantity_line"] = q_row
        raw["net_weight"] = Decimal(q.group(3))
        if expiry_raw is not None:
            expiry = parse_short_date(expiry_raw)
            status = "known" if expiry else "ambiguous"
            if expiry is None:
                errors.append(_block(q_row, "expiry_raw", "expiry_ambiguous", "指定效期格式无法确认"))
        if unit == item_unit == "EA":
            base = count
        else:
            # The Quantity column is headed "EA/Pack" and prints EA even for
            # CS items; whether that means cans or cases is Q04.
            errors.append(_block(q_row, "unit", "unit_needs_confirmation",
                                 f"商品单位 {item_unit}、数量栏单位 {unit}，换算需人工确认"))
        size_kg = _SIZE_KG.fullmatch(size)
        if size_kg and unit == "EA" and raw["net_weight"] != count * Decimal(size_kg.group(1)):
            errors.append(_block(q_row, "net_weight", "net_weight_mismatch",
                                 "净重不等于数量×规格，配对或数值可能有误"))
    return ImportLine(
        row_number=row, owner=owner, external_doc_no=doc_no, doc_version=None,
        code=item.group(2), name=description, quantity=count, quantity_raw=count, unit=unit,
        expiry_raw=expiry_raw, expiry_date=expiry, expiry_status=status, external_lot=None,
        remark=None, errors=errors, raw_values=raw, base_quantity=base,
        base_unit="EA" if base is not None else None,
    )
