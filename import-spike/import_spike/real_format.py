"""Read the two observed spreadsheet layouts into preview-only ImportLine records.

No customer values or inventory writes belong in this module. The workbook
shapes are documented in fixtures/synthetic/real-format/README.md.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import openpyxl

from .importer import ImportLine, RowError

STOCK_HEADERS = (
    "物料编码", "产品中文描述Product Description-Chinese", "规格型号",
    "仓库名称", "仓位", "有效期至", "库存量(主单位)",
)
INSPECTION_HEADERS = ("Item Number", "Description", "Item UOM", "Piece Per Case")
_STOCK_DATE = re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})$")


def _error(row: int, field: str, code: str, message: str) -> RowError:
    return RowError(row, field, code, message, "block")


def _quantity(raw: Any, row: int, errors: list[RowError], field: str = "quantity") -> int | None:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        errors.append(_error(row, field, "quantity_not_numeric", "数量必须是数值单元格，布尔值和空格都不是数量"))
        return None
    try:
        value = Decimal(str(raw))
        if not value.is_finite() or value < 0 or value != value.to_integral_value():
            raise ValueError
        return int(value)
    except (InvalidOperation, ValueError):
        errors.append(_error(row, field, "quantity_invalid", "数量必须是非负整数"))
        return None


def convert_to_ea(count: Any, unit: str, pieces_per_case: Any) -> int:
    """Convert an explicitly CS-labelled count; never apply to a 件 column."""
    errors: list[RowError] = []
    amount = _quantity(count, 0, errors)
    factor = _quantity(pieces_per_case, 0, errors, "piece_per_case")
    if errors or factor == 0 or unit not in ("CS", "EA"):
        raise ValueError("数量、单位或每箱件数无效")
    return amount * (factor if unit == "CS" else 1)


def _blank(raw: Any) -> bool:
    return raw is None or isinstance(raw, str) and not raw.strip()


def _expiry(raw: Any, row: int, errors: list[RowError], stock: bool) -> tuple[date | None, str]:
    if _blank(raw):
        return None, "unknown"
    if isinstance(raw, datetime):
        return raw.date(), "known"
    if isinstance(raw, date):
        return raw, "known"
    if stock and isinstance(raw, str):
        match = _STOCK_DATE.fullmatch(raw.strip())
        if match:
            try:
                return date(*(int(x) for x in match.groups())), "known"
            except ValueError:
                pass
    errors.append(_error(row, "expiry_raw", "expiry_ambiguous", "效期格式无法确认，需人工核对"))
    return None, "ambiguous"


def parse_stock_export(path: Path, *, owner: str, external_doc_no: str) -> list[ImportLine]:
    """Parse a stock snapshot; same-code rows remain separate source lines."""
    if not owner or not external_doc_no:
        raise ValueError("库存表没有货主/单号列，调用方必须明确提供货主与快照单号")
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook.active
        rows = sheet.iter_rows()
        headers = next(rows, None)
        if headers is None or tuple(c.value for c in headers[:7]) != STOCK_HEADERS:
            raise ValueError("库存表表头与已观察格式不一致")
        lines: list[ImportLine] = []
        for cells in rows:
            raw = {name: cells[i].value for i, name in enumerate(STOCK_HEADERS)}
            if all(_blank(v) for v in raw.values()):
                continue
            row = cells[0].row
            errors: list[RowError] = []
            code = raw[STOCK_HEADERS[0]]
            if not isinstance(code, str) or not code.strip():
                errors.append(_error(row, "code", "code_not_text", "商品编码必须是文本，数字单元格可能丢失前导零"))
            quantity = _quantity(raw[STOCK_HEADERS[6]], row, errors)
            expiry, status = _expiry(raw[STOCK_HEADERS[5]], row, errors, stock=True)
            warehouse = raw[STOCK_HEADERS[3]]
            if not isinstance(warehouse, str) or not warehouse.strip():
                errors.append(_error(row, "warehouse", "warehouse_missing", "仓库名称不能为空"))
                warehouse = None
            condition = "HOLD" if warehouse and warehouse.endswith(" NG") else "AVAILABLE"
            location = raw[STOCK_HEADERS[4]]
            if not _blank(location) and not isinstance(location, str):
                errors.append(_error(row, "location", "location_invalid", "仓位必须是文本"))
            if condition == "AVAILABLE" and _blank(location):
                errors.append(_error(row, "location", "location_missing", "正常库存缺少仓位，需人工核对"))
            lines.append(ImportLine(
                row_number=row, owner=owner, external_doc_no=external_doc_no, doc_version=None,
                code=code, name=raw[STOCK_HEADERS[1]], quantity=quantity,
                quantity_raw=raw[STOCK_HEADERS[6]], unit="EA", expiry_raw=raw[STOCK_HEADERS[5]],
                expiry_date=expiry, expiry_status=status, external_lot=None, remark=None,
                errors=errors, raw_values=raw, base_quantity=quantity, base_unit="EA",
                warehouse=warehouse, location=None if _blank(location) else location, condition=condition,
            ))
        return lines
    finally:
        workbook.close()


def parse_inspection_sheet(path: Path, *, owner: str, external_doc_no: str) -> list[ImportLine]:
    """Read header rows 4-5 and convert CS by its explicit Piece Per Case value."""
    if not owner or not external_doc_no:
        raise ValueError("调用方必须明确提供货主和单号")
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook["Data"] if "Data" in workbook else workbook.active
        if tuple(sheet.cell(5, i).value for i in range(1, 5)) != INSPECTION_HEADERS:
            raise ValueError("验货纸两行表头与已观察格式不一致")
        if sheet.cell(4, 6).value != "存倉數量 (件)" or sheet.cell(4, 7).value != "EXPIRY DATE":
            raise ValueError("验货纸上层表头与已观察格式不一致")
        lines: list[ImportLine] = []
        for cells in sheet.iter_rows(min_row=6):
            if all(_blank(c.value) for c in cells):
                continue
            # The observed sheet ends with a total row: text in column A,
            # a number in F, and no product fields. It is not an item line.
            if (isinstance(cells[0].value, str) and isinstance(cells[5].value, (int, float))
                    and all(_blank(cells[i].value) for i in (1, 2, 3, 6))):
                continue
            row = cells[0].row
            raw = {"item_number": cells[0].value, "description": cells[1].value,
                   "unit": cells[2].value, "piece_per_case": cells[3].value,
                   "stock_quantity_ea": cells[5].value, "expiry": cells[6].value,
                   "received": cells[7].value if len(cells) > 7 else None,
                   "over": cells[9].value if len(cells) > 9 else None,
                   "short": cells[10].value if len(cells) > 10 else None}
            errors: list[RowError] = []
            item = raw["item_number"]
            if isinstance(item, bool) or not isinstance(item, (str, int)) or _blank(item):
                errors.append(_error(row, "code", "code_invalid", "商品编号无法确认"))
            code = str(item) if item is not None else None
            unit = raw["unit"]
            if unit not in ("CS", "EA"):
                errors.append(_error(row, "unit", "unit_not_confirmed", "单位不是已观察到的 CS/EA，需人工确认"))
            pieces = _quantity(raw["piece_per_case"], row, errors, "piece_per_case")
            if pieces == 0:
                errors.append(_error(row, "piece_per_case", "factor_invalid", "每箱件数必须大于零"))
            stock_ea = _quantity(raw["stock_quantity_ea"], row, errors, "stock_quantity_ea")
            expiry, status = _expiry(raw["expiry"], row, errors, stock=False)
            for field in ("received", "over", "short"):
                if not _blank(raw[field]):
                    _quantity(raw[field], row, errors, field)
            # Both the stored and received quantity headers say 件 (pieces).
            # The Item UOM and Piece Per Case fields are kept for explicit
            # case-labelled quantities, but multiplying these columns would
            # silently inflate the customer's numbers.
            lines.append(ImportLine(
                row_number=row, owner=owner, external_doc_no=external_doc_no, doc_version=None,
                code=code, name=raw["description"], quantity=stock_ea,
                quantity_raw=raw["stock_quantity_ea"], unit="EA", expiry_raw=raw["expiry"],
                expiry_date=expiry, expiry_status=status, external_lot=None, remark=None,
                errors=errors, raw_values=raw, base_quantity=stock_ea, base_unit="EA",
            ))
            lines[-1].raw_values["received_ea"] = None if _blank(raw["received"]) else raw["received"]
        return lines
    finally:
        workbook.close()
