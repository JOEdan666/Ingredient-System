"""Real pytest run against the synthetic .xlsx fixtures in fixtures/synthetic/import-samples/.

Covers T04's acceptance scope:
- A05 重复导入和提交重试幂等：exact duplicate / revision detection, preview has no
  side effects, commit rejects a non-postable batch.
- A07 日期编码单位与缺失信息：leading-zero codes, unknown unit conversions,
  ambiguous vs. unknown expiry dates.
- A08 预览无副作用与库存快照区别：preview never mutates the ledger; duplicate-looking
  rows inside one file are flagged, never silently merged; a remark that
  contradicts the stated quantity is never auto-applied.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from import_spike.importer import commit_batch, preview

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLES = REPO_ROOT / "fixtures" / "synthetic" / "import-samples"


@pytest.fixture
def unit_conversions() -> dict:
    return json.loads((REPO_ROOT / "fixtures" / "synthetic" / "unit-conversions.json").read_text())


@pytest.fixture
def empty_ledger() -> list[dict]:
    return []


def _line(result, row_number):
    return next(ln for ln in result.lines if ln.row_number == row_number)


# ---- A05: duplicate / revision / idempotent retry --------------------------------


def test_new_batch_is_postable_and_classified_new(unit_conversions, empty_ledger):
    result = preview(SAMPLES / "receiving_normal.xlsx", empty_ledger, unit_conversions)
    assert result.classification == "new"
    assert result.postable
    assert [ln.code for ln in result.lines] == ["00123", "00456"]


def test_preview_has_no_side_effects_and_is_repeatable(unit_conversions, empty_ledger):
    before = list(empty_ledger)
    for _ in range(3):
        result = preview(SAMPLES / "receiving_normal.xlsx", empty_ledger, unit_conversions)
        assert result.classification == "new"
    assert empty_ledger == before  # preview() never wrote to the ledger it was given


def test_exact_duplicate_upload_is_detected_and_not_postable(unit_conversions, empty_ledger):
    first = preview(SAMPLES / "receiving_normal.xlsx", empty_ledger, unit_conversions)
    ledger = commit_batch(first, empty_ledger, accepted_at="2026-09-29T00:00:00Z")
    assert len(ledger) == 1

    second = preview(SAMPLES / "receiving_normal.xlsx", ledger, unit_conversions)
    assert second.classification == "exact_duplicate"
    assert second.duplicate_of_fingerprint == first.fingerprint
    assert not second.postable

    # Retrying commit on the duplicate must not add a second ledger entry or
    # silently succeed (A05: same operation submitted twice only counts once).
    with pytest.raises(ValueError):
        commit_batch(second, ledger, accepted_at="2026-09-29T00:05:00Z")


def test_revision_is_flagged_not_silently_superseded(unit_conversions, empty_ledger):
    original = preview(SAMPLES / "receiving_normal.xlsx", empty_ledger, unit_conversions)
    ledger = commit_batch(original, empty_ledger, accepted_at="2026-09-29T00:00:00Z")

    revised = preview(SAMPLES / "receiving_revision.xlsx", ledger, unit_conversions)
    assert revised.fingerprint != original.fingerprint
    assert revised.classification == "revision"
    assert revised.duplicate_of_fingerprint == original.fingerprint
    assert not revised.postable  # needs a human decision, not an automatic supersede

    # The original ledger entry must still be there, untouched, after a
    # revision was merely previewed (not committed).
    assert ledger == [
        {
            "fingerprint": original.fingerprint,
            "owner": "DEMO-OWNER-A",
            "external_doc_no": "DOC-2026-001",
            "doc_version": "1",
            "accepted_at": "2026-09-29T00:00:00Z",
        }
    ]


def test_commit_rejects_non_postable_batch_and_does_not_grow_ledger(unit_conversions, empty_ledger):
    result = preview(SAMPLES / "receiving_bad_rows.xlsx", empty_ledger, unit_conversions)
    assert not result.postable
    with pytest.raises(ValueError):
        commit_batch(result, empty_ledger, accepted_at="2026-09-29T00:00:00Z")
    assert empty_ledger == []


# ---- A07: codes, units, dates -----------------------------------------------------


def test_leading_zero_code_is_preserved_as_text(unit_conversions, empty_ledger):
    result = preview(SAMPLES / "receiving_normal.xlsx", empty_ledger, unit_conversions)
    line = _line(result, 2)
    assert line.code == "00123"
    assert isinstance(line.code, str)
    assert line.postable


def test_code_stored_as_number_is_blocked_not_silently_cast(unit_conversions, empty_ledger):
    result = preview(SAMPLES / "receiving_bad_rows.xlsx", empty_ledger, unit_conversions)
    line = _line(result, 3)
    assert line.code == 456  # not silently turned back into a string with guessed zeros
    assert not line.postable
    assert any(e.code == "code_not_text" for e in line.errors)


def test_unconfirmed_unit_blocks_posting(unit_conversions, empty_ledger):
    result = preview(SAMPLES / "receiving_bad_rows.xlsx", empty_ledger, unit_conversions)
    line = _line(result, 4)
    assert not line.postable
    assert any(e.code == "unit_not_confirmed" for e in line.errors)


def test_confirmed_unit_conversion_allows_posting(unit_conversions, empty_ledger):
    result = preview(SAMPLES / "receiving_unit_confirmed.xlsx", empty_ledger, unit_conversions)
    assert result.postable
    assert result.lines[0].unit == "CS"


def test_missing_expiry_is_recorded_as_unknown_not_invented(unit_conversions, empty_ledger):
    result = preview(SAMPLES / "receiving_bad_rows.xlsx", empty_ledger, unit_conversions)
    line = _line(result, 5)
    assert line.expiry_date is None
    assert line.expiry_status == "unknown"
    assert line.postable  # unknown expiry is allowed; it is just not invented


def test_genuinely_ambiguous_date_is_not_guessed(unit_conversions, empty_ledger):
    result = preview(SAMPLES / "receiving_bad_rows.xlsx", empty_ledger, unit_conversions)
    line = _line(result, 6)  # "03/04/2026": both parts <= 12
    assert line.expiry_date is None
    assert line.expiry_status == "ambiguous"
    assert not line.postable


def test_non_iso_but_determinable_date_is_flagged_with_a_guess(unit_conversions, empty_ledger):
    result = preview(SAMPLES / "receiving_bad_rows.xlsx", empty_ledger, unit_conversions)
    line = _line(result, 7)  # "25/12/2026": 25 can only be a day
    assert line.expiry_date == date(2026, 12, 25)
    assert line.expiry_status == "ambiguous"
    assert not line.postable  # still needs a human to confirm before posting


# ---- A08: preview side effects, duplicate rows, remark override -------------------


def test_duplicate_looking_rows_are_kept_separate_not_merged(unit_conversions, empty_ledger):
    result = preview(SAMPLES / "receiving_bad_rows.xlsx", empty_ledger, unit_conversions)
    row9, row10 = _line(result, 9), _line(result, 10)
    assert row9.quantity == 2 and row10.quantity == 2  # not merged into one row of 4
    assert any(e.code == "duplicate_looking_rows" for e in row9.errors)
    assert any(e.code == "duplicate_looking_rows" for e in row10.errors)
    # a suspected-duplicate row is a warning, not a hard block on its own
    assert row9.postable and row10.postable


def test_remark_quantity_override_is_not_auto_applied(unit_conversions, empty_ledger):
    result = preview(SAMPLES / "receiving_bad_rows.xlsx", empty_ledger, unit_conversions)
    line = _line(result, 8)
    assert line.quantity == 10  # stated quantity kept, not silently replaced by the remark's 7
    assert not line.postable
    assert any(e.code == "remark_override_conflict" for e in line.errors)
