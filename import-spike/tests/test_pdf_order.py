from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from import_spike.pdf_order import parse_pdf_order_text, parse_short_date

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "fixtures" / "synthetic" / "real-format" / "pdf_order_extracted_text_synthetic.txt"


def _text() -> str:
    return SAMPLE.read_text(encoding="utf-8")


def _codes(errors) -> set[str]:
    return {e.code for e in errors}


def test_lines_are_reordered_by_seq_and_paired_with_their_quantities():
    result = parse_pdf_order_text(_text(), owner="SYN-OWNER")
    assert result.batch_errors == []
    assert [line.raw_values["seq"] for line in result.lines] == [1, 2, 3]
    assert [line.code for line in result.lines] == ["9270501", "900202", "900201"]
    seq3 = result.lines[2]
    assert (seq3.quantity, seq3.unit, seq3.raw_values["net_weight"]) == (4, "EA", Decimal("6.00"))
    assert seq3.expiry_date == date(2027, 7, 1) and type(seq3.expiry_date) is date
    assert seq3.base_quantity == 4 and seq3.postable
    assert result.lines[1].expiry_date == date(2027, 8, 8) and result.lines[1].postable


def test_header_keeps_only_doc_no_date_and_customer_ref():
    result = parse_pdf_order_text(_text(), owner="SYN-OWNER")
    assert (result.external_doc_no, result.doc_date, result.customer_ref) == (
        "SYN26090001", date(2026, 9, 23), "SYN-C001")
    stored = repr(result)
    assert "中文地址" not in stored and "Pet Shop" not in stored


def test_wrapped_description_and_old_code():
    lines = parse_pdf_order_text(_text(), owner="SYN-OWNER").lines
    assert lines[0].name == "SYN Cat Cans Turkey Recipe - Cans 5.5oz"
    assert lines[0].raw_values["size"] == "12 x 5.5 oz."
    assert lines[1].name == "SYN CAT RENAL 1.5KG"
    assert lines[1].raw_values["old_code"] == "900299"


def test_case_item_with_ea_quantity_is_not_converted():
    line = parse_pdf_order_text(_text(), owner="SYN-OWNER").lines[0]
    assert (line.quantity, line.unit, line.raw_values["item_unit"]) == (4, "EA", "CS")
    assert line.base_quantity is None
    assert not line.postable and "unit_needs_confirmation" in _codes(line.errors)


def test_trailing_spaces_from_real_extraction_are_ignored():
    padded = "\n".join(line + "  " for line in _text().splitlines())
    assert repr(parse_pdf_order_text(padded, owner="SYN-OWNER")) == repr(
        parse_pdf_order_text(_text(), owner="SYN-OWNER"))


def test_extra_quantity_line_blocks_the_document_instead_of_guessing():
    text = _text().replace("Code 900299)\n", "Code 900299)\n2 CS 9.00 11-Sep-28\n")
    result = parse_pdf_order_text(text, owner="SYN-OWNER")
    assert "line_count_mismatch" in _codes(result.batch_errors)
    assert all(line.quantity is None and not line.postable for line in result.lines)
    assert not result.postable


def test_totals_mismatch_blocks_the_document():
    result = parse_pdf_order_text(_text().replace("10 21.00", "11 21.00"), owner="SYN-OWNER")
    assert "totals_mismatch" in _codes(result.batch_errors) and not result.postable


def test_missing_totals_blocks_the_document():
    result = parse_pdf_order_text(_text().replace("10 21.00\n", ""), owner="SYN-OWNER")
    assert "totals_missing" in _codes(result.batch_errors)


def test_net_weight_that_does_not_match_size_is_flagged():
    text = _text().replace("2 EA 3.00 8-Aug-27", "2 EA 4.00 8-Aug-27").replace("10 21.00", "10 22.00")
    result = parse_pdf_order_text(text, owner="SYN-OWNER")
    assert result.batch_errors == []
    assert "net_weight_mismatch" in _codes(result.lines[1].errors)


@pytest.mark.parametrize("raw", ["31-Feb-27", "1-Jly-27", "2027-07-01"])
def test_unclear_expiry_is_not_guessed(raw):
    result = parse_pdf_order_text(_text().replace("1-Jul-27", raw), owner="SYN-OWNER")
    line = result.lines[2]
    assert line.expiry_date is None and line.expiry_status == "ambiguous" and not line.postable


def test_short_date_parsing():
    assert parse_short_date("1-Jul-27") == date(2027, 7, 1)
    assert parse_short_date("12-Nov-27") == date(2027, 11, 12)
    assert parse_short_date("") is None


def test_seq_gap_blocks_the_document():
    result = parse_pdf_order_text(_text().replace("3 900201", "4 900201"), owner="SYN-OWNER")
    assert "seq_gap" in _codes(result.batch_errors)


def test_unexpected_order_is_not_paired():
    text = _text().replace("3 900201", "0 900201")
    result = parse_pdf_order_text(text, owner="SYN-OWNER")
    assert "order_unrecognized" in _codes(result.batch_errors)
    assert all(line.quantity is None for line in result.lines)


def test_unknown_item_unit_blocks_the_document():
    text = _text().replace("1.5kg EA SYN CAT SENIOR", "1.5kg BAG SYN CAT SENIOR")
    result = parse_pdf_order_text(text, owner="SYN-OWNER")
    assert "item_line_unrecognized" in _codes(result.batch_errors)
    assert not result.postable


def test_owner_is_required():
    with pytest.raises(ValueError):
        parse_pdf_order_text(_text(), owner="")
