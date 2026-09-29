"""Builds the synthetic .xlsx fixtures in this directory from scratch.

Run with the import-spike venv (has openpyxl):
    cd import-spike && uv run python ../fixtures/synthetic/import-samples/generate_samples.py

All data here is fabricated for T04 (see docs/import-contract.md). Re-running
this script overwrites the committed .xlsx files with the same bytes (openpyxl
output is deterministic for a fixed input), so it is safe to use as the single
source of truth for the fixtures instead of hand-editing spreadsheets.
"""

from __future__ import annotations

from pathlib import Path

import openpyxl

HERE = Path(__file__).parent

HEADERS = ["货主", "外部单号", "单据版本", "商品编码", "商品名称", "数量", "单位", "效期", "外部批号", "备注"]


def _write(path: Path, rows: list[list]) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "到货"
    ws.append(HEADERS)
    for row in rows:
        ws.append(row)
    wb.save(path)


def build_normal() -> None:
    rows = [
        ["DEMO-OWNER-A", "DOC-2026-001", "1", "00123", "虾仁 Shrimp", 10, "EA", "2027-01-15", "LOT-A", ""],
        ["DEMO-OWNER-A", "DOC-2026-001", "1", "00456", "带子 Scallop", 5, "EA", "2027-02-01", "LOT-B", ""],
    ]
    _write(HERE / "receiving_normal.xlsx", rows)


def build_revision() -> None:
    # Same external_doc_no as receiving_normal.xlsx but different content
    # (quantity corrected, version bumped) -> different file fingerprint.
    rows = [
        ["DEMO-OWNER-A", "DOC-2026-001", "2", "00123", "虾仁 Shrimp", 12, "EA", "2027-01-15", "LOT-A", "更正数量"],
        ["DEMO-OWNER-A", "DOC-2026-001", "2", "00456", "带子 Scallop", 5, "EA", "2027-02-01", "LOT-B", ""],
    ]
    _write(HERE / "receiving_revision.xlsx", rows)


def build_unit_confirmed() -> None:
    rows = [
        ["DEMO-OWNER-A", "DOC-2026-003", "1", "00500", "急冻带子 CS Pack", 2, "CS", "2027-04-01", "LOT-CS1", ""],
    ]
    _write(HERE / "receiving_unit_confirmed.xlsx", rows)


def build_bad_rows() -> None:
    rows = [
        # row 2: clean baseline row, must be postable
        ["DEMO-OWNER-A", "DOC-2026-002", "1", "00123", "虾仁 Shrimp", 10, "EA", "2027-01-15", "LOT-A", ""],
        # row 3: product code stored as a real number -> leading zeros at risk
        ["DEMO-OWNER-A", "DOC-2026-002", "1", 456, "扇贝 Scallop", 5, "EA", "2027-02-01", "LOT-B", ""],
        # row 4: unit has no confirmed conversion
        ["DEMO-OWNER-A", "DOC-2026-002", "1", "00789", "带子 Scallop2", 3, "箱", "2027-03-01", "LOT-C", ""],
        # row 5: expiry blank -> unknown, not invented, not blocking
        ["DEMO-OWNER-A", "DOC-2026-002", "1", "00999", "鱼柳 Fillet", 8, "EA", "", "LOT-D", ""],
        # row 6: genuinely ambiguous date (both parts <= 12)
        ["DEMO-OWNER-A", "DOC-2026-002", "1", "00111", "带鱼 Ribbonfish", 4, "EA", "03/04/2026", "LOT-E", ""],
        # row 7: non-ISO but determinable date (25 can only be a day)
        ["DEMO-OWNER-A", "DOC-2026-002", "1", "00222", "鱿鱼 Squid", 6, "EA", "25/12/2026", "LOT-F", ""],
        # row 8: remark contradicts the stated quantity
        ["DEMO-OWNER-A", "DOC-2026-002", "1", "00333", "龙虾 Lobster", 10, "EA", "2027-05-01", "LOT-G", "实际数量：7"],
        # rows 9-10: identical-looking rows -- must NOT be silently merged
        ["DEMO-OWNER-A", "DOC-2026-002", "1", "00444", "蟹 Crab", 2, "EA", "2027-06-01", "LOT-H", ""],
        ["DEMO-OWNER-A", "DOC-2026-002", "1", "00444", "蟹 Crab", 2, "EA", "2027-06-01", "LOT-H", ""],
    ]
    _write(HERE / "receiving_bad_rows.xlsx", rows)


if __name__ == "__main__":
    build_normal()
    build_revision()
    build_unit_confirmed()
    build_bad_rows()
    print("wrote receiving_normal.xlsx, receiving_revision.xlsx, receiving_unit_confirmed.xlsx, receiving_bad_rows.xlsx")
