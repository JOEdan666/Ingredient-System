"""File import: upload -> preview -> confirm -> posted through the domain layer.

Synthetic real-format fixtures only (fixtures/synthetic/real-format/).  A
newcomer path is tested first: the page's default controls, no document
type chosen by hand.
"""
from datetime import date, datetime
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from inventory import domain, import_posting
from inventory.domain import DomainError
from inventory.models import (
    ImportBatch, Order, Owner, Product, ProductAvailability, ReceiptNotice, ReceiptNoticeLine, StockBalance,
    StockMovement,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic" / "real-format"
ACTOR = "员工甲（合成）"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def upload(client, name, *, owner="", owner_new="SYN-IMPORT-OWNER", as_name=None):
    data = SimpleUploadedFile(as_name or name, (FIXTURES / name).read_bytes(), content_type=XLSX)
    return client.post(reverse("import_preview"), {"file": data, "owner": owner, "owner_new": owner_new}, follow=True)


SNAPSHOT = {"snapshot_at": "2026-09-01T09:00", "export_basis": "physical"}


def confirm(client, batch, **extra):
    data = {"actor": ACTOR, "operation_id": "x", **(SNAPSHOT if batch.kind == ImportBatch.Kind.STOCK else {}), **extra}
    return client.post(reverse("import_post", args=[batch.pk]), data, follow=True)


@pytest.fixture
def empty(db):
    yield
    assert domain.check_invariants() == []


def test_newcomer_stock_upload_detects_kind_and_posts_opening_stock(client, empty):
    resp = upload(client, "stock_export_synthetic.xlsx")
    html = resp.content.decode()
    batch = ImportBatch.objects.get()
    assert batch.kind == ImportBatch.Kind.STOCK and batch.ready
    assert "确认入账" in html and "库存表（期初库存）" in html
    assert StockMovement.objects.count() == 0  # preview writes nothing

    html = confirm(client, batch).content.decode()
    assert "入账完成" in html
    batch.refresh_from_db()
    assert batch.status == ImportBatch.Status.POSTED
    assert StockMovement.objects.filter(kind="OPENING").count() == batch.recognized
    assert sum(b.on_hand for b in StockBalance.objects.all()) == sum(l["qty"] for l in batch.lines)
    held = sum(l["qty"] for l in batch.lines if l["condition"] == "HOLD")
    assert held > 0  # the fixture has NG rows; they must not become sellable
    assert sum(pa.sellable for pa in ProductAvailability.objects.all()) == batch.result["sellable"]
    assert sum(b.on_hand for b in StockBalance.objects.filter(condition="HOLD")) == held


def test_same_file_or_second_snapshot_for_owner_is_refused_before_and_at_posting(client, empty):
    upload(client, "stock_export_synthetic.xlsx")
    confirm(client, ImportBatch.objects.get())
    movements = StockMovement.objects.count()

    html = upload(client, "stock_export_synthetic.xlsx", owner="SYN-IMPORT-OWNER", owner_new="").content.decode()
    again = ImportBatch.objects.latest("pk")
    assert "拒绝重复入账" in html  # shown before the person clicks confirm
    html = confirm(client, again).content.decode()
    assert "入账被拒绝，什么都没有写入" in html

    # Same owner, different file bytes: still refused (would count stock twice).
    html = upload(client, "stock_export_synthetic.xlsx", owner_new="SYN-IMPORT-OWNER", as_name="other-name.xlsx").content.decode()
    assert "拒绝重复入账" in html or "已经有库存记录" in html
    assert StockMovement.objects.count() == movements


def test_inspection_sheet_becomes_notice_not_stock(client, empty):
    upload(client, "inspection_sheet_synthetic.xlsx")
    batch = ImportBatch.objects.get()
    assert batch.kind == ImportBatch.Kind.INSPECTION
    html = confirm(client, batch).content.decode()
    assert "收货预告" in html and "没有" in html
    notice = ReceiptNotice.objects.get()
    assert ReceiptNoticeLine.objects.filter(notice=notice).count() == batch.recognized
    assert StockMovement.objects.count() == 0  # expected arrival is not received stock


def test_missing_owner_is_explained_and_nothing_saved(client, empty):
    html = upload(client, "stock_export_synthetic.xlsx", owner_new="").content.decode()
    assert "请选择货主" in html
    assert ImportBatch.objects.count() == 0


def test_unrecognised_spreadsheet_is_rejected_in_plain_words(client, empty, tmp_path):
    import openpyxl
    path = tmp_path / "random.xlsx"
    wb = openpyxl.Workbook(); wb.active["A1"] = "not a known header"; wb.save(path)
    resp = client.post(reverse("import_preview"), {
        "file": SimpleUploadedFile("random.xlsx", path.read_bytes(), content_type=XLSX), "owner_new": "SYN-X"})
    assert "认不出这是哪种表格" in resp.content.decode()
    assert ImportBatch.objects.count() == 0


def _pdf_batch(owner, lines, **kw):
    batch = ImportBatch.objects.create(kind=ImportBatch.Kind.PDF_ORDER, file_name="syn.pdf", file_sha256=kw.get("sha", "a" * 64),
                                       owner_code=owner, external_doc_no=kw.get("doc", "SYN-INV-1"), lines=lines)
    return batch


def _line(row, code, qty, errors=()):
    return {"row": row, "code": code, "name": "合成", "qty": qty, "printed_qty": qty, "unit": "EA", "expiry": None,
            "location": None, "warehouse": None, "condition": None, "errors": list(errors), "postable": not errors}


def test_pdf_order_reserves_and_rolls_back_whole_order_when_short(world):
    world.opening(10)
    ok = _pdf_batch("SYN-OWNER-A", [_line(1, "000777", 4)])
    import_posting.post_batch(ok.pk, ACTOR)
    assert world.numbers(world.product_a)["reserved"] == 4

    short = _pdf_batch("SYN-OWNER-A", [_line(1, "000777", 1), _line(2, "000777", 99)], sha="b" * 64, doc="SYN-INV-2")
    with pytest.raises(DomainError):
        import_posting.post_batch(short.pk, ACTOR)
    short.refresh_from_db()
    assert short.status == ImportBatch.Status.PREVIEW
    assert Order.objects.count() == 1
    assert world.numbers(world.product_a)["reserved"] == 4


def test_unit_confirmation_requires_explicit_choice_and_records_who(world):
    world.opening(100)
    unit_err = {"code": "unit_needs_confirmation", "message": "换算需人工确认"}
    batch = _pdf_batch("SYN-OWNER-A", [_line(1, "000777", None, [unit_err]) | {"printed_qty": 3}])
    with pytest.raises(DomainError):
        import_posting.post_batch(batch.pk, ACTOR)
    with pytest.raises(DomainError):
        import_posting.confirm_units(batch, {1: ("CS", None)}, ACTOR)  # case without pieces-per-case
    batch.refresh_from_db()
    assert not batch.ready
    assert import_posting.confirm_units(batch, {1: ("CS", 12)}, ACTOR) == 1
    batch.refresh_from_db()
    assert batch.ready and batch.lines[0]["qty"] == 36 and ACTOR in batch.lines[0]["unit_note"]
    import_posting.post_batch(batch.pk, ACTOR)
    assert world.numbers(world.product_a)["reserved"] == 36


def test_failure_midway_through_stock_import_writes_nothing(empty):
    lines = [_line(1, "SYN-1", 5) | {"condition": "AVAILABLE", "location": "SYN-L1"},
             _line(2, "SYN-2", 5) | {"condition": "NOT-A-CONDITION", "location": "SYN-L1"}]
    batch = ImportBatch.objects.create(kind=ImportBatch.Kind.STOCK, file_name="s.xlsx", file_sha256="c" * 64,
                                       owner_code="SYN-NEW", external_doc_no="S", lines=lines)
    with pytest.raises(DomainError) as err:
        import_posting.post_batch(batch.pk, ACTOR, snapshot_at=datetime(2026, 9, 1, 9), export_basis="physical")
    assert err.value.code == "unknown_condition"  # failed on line 2, after line 1 was written
    assert StockMovement.objects.count() == 0
    assert not Owner.objects.filter(code="SYN-NEW").exists()
    assert not Product.objects.filter(code="SYN-1").exists()
    batch.refresh_from_db()
    assert batch.status == ImportBatch.Status.PREVIEW


def test_pdf_upload_marks_products_not_in_system(client, world, monkeypatch):
    text = (FIXTURES / "pdf_order_extracted_text_synthetic.txt").read_text(encoding="utf-8")

    class FakePage:
        def extract_text(self):
            return text

    class FakeReader:
        def __init__(self, path):
            self.pages = [FakePage()]

    monkeypatch.setattr("inventory.import_preview.PdfReader", FakeReader)
    resp = client.post(reverse("import_preview"), {
        "file": SimpleUploadedFile("syn.pdf", b"%PDF-synthetic", content_type="application/pdf"),
        "owner": "SYN-OWNER-A"}, follow=True)
    html = resp.content.decode()
    batch = ImportBatch.objects.get()
    assert batch.kind == ImportBatch.Kind.PDF_ORDER and batch.external_doc_no
    assert "还没有商品" in html and "怎么办" in html
    assert "暂不能入账" in html


# --- review 2026-09-30 (e0b901e) findings -------------------------------------------------

def _stock_batch(owner="SYN-CUT", sha="d" * 64):
    lines = [_line(1, "SYN-P1", 10) | {"condition": "AVAILABLE", "location": "SYN-L1"}]
    return ImportBatch.objects.create(kind=ImportBatch.Kind.STOCK, file_name="s.xlsx", file_sha256=sha,
                                      owner_code=owner, external_doc_no="S", lines=lines)


def test_stock_posting_requires_stated_cutover_and_refuses_net_export(empty):
    batch = _stock_batch()
    for kwargs, code in [({}, "missing_snapshot"),
                         ({"snapshot_at": datetime(2026, 9, 1, 9)}, "missing_basis"),
                         ({"snapshot_at": datetime(2026, 9, 1, 9), "export_basis": "net"}, "net_export"),
                         ({"snapshot_at": datetime(2099, 1, 1), "export_basis": "physical"}, "bad_snapshot")]:
        with pytest.raises(DomainError) as err:
            import_posting.post_batch(batch.pk, ACTOR, **kwargs)
        assert err.value.code == code
    assert StockMovement.objects.count() == 0
    import_posting.post_batch(batch.pk, ACTOR, snapshot_at=datetime(2026, 9, 1, 9), export_basis="physical")
    batch.refresh_from_db()
    assert batch.snapshot_at is not None and batch.export_basis == "physical"
    assert "导出于 2026-09-01 09:00" in StockMovement.objects.get().source_doc


def test_order_dated_on_or_before_snapshot_needs_explicit_confirmation(empty):
    import_posting.post_batch(_stock_batch().pk, ACTOR, snapshot_at=datetime(2026, 9, 1, 9), export_basis="physical")
    old = _pdf_batch("SYN-CUT", [_line(1, "SYN-P1", 2)], sha="e" * 64, doc="SYN-OLD")
    old.doc_date = date(2026, 8, 31); old.save()
    with pytest.raises(DomainError) as err:
        import_posting.post_batch(old.pk, ACTOR)
    assert err.value.code == "cutover_unconfirmed"
    assert Order.objects.count() == 0
    import_posting.post_batch(old.pk, ACTOR, confirm_not_in_snapshot=True)
    old.refresh_from_db()
    assert old.result["cutover_confirmed_by"] == ACTOR

    new = _pdf_batch("SYN-CUT", [_line(1, "SYN-P1", 2)], sha="f" * 64, doc="SYN-NEW")
    new.doc_date = date(2026, 9, 2); new.save()
    import_posting.post_batch(new.pk, ACTOR)  # dated after the snapshot: no question


def test_pdf_uploaded_before_products_exist_clears_after_stock_import(client, empty):
    lines = [_line(1, "SYN-P1", 2, [{"code": "product_unknown", "message": "x"}])]
    pdf = _pdf_batch("SYN-CUT", lines, sha="9" * 64)
    assert not pdf.ready
    import_posting.post_batch(_stock_batch().pk, ACTOR, snapshot_at=datetime(2026, 9, 1, 9), export_basis="physical")
    html = client.get(reverse("import_detail", args=[pdf.pk])).content.decode()
    pdf.refresh_from_db()
    assert pdf.ready and "还没有商品" not in html and "确认入账" in html


def test_order_lines_keep_source_row_and_file_identity(client, world):
    world.opening(10)
    batch = _pdf_batch("SYN-OWNER-A", [_line(17, "000777", 1) | {"seq": 1}, _line(4, "000777", 2)])
    import_posting.post_batch(batch.pk, ACTOR)
    order = Order.objects.get()
    assert f"导入#{batch.pk}" in order.source_ref and "sha256:" in order.source_ref
    assert [l.source_line for l in order.lines.order_by("line_no")] == ["序号1", "第4行"]
    html = client.get(reverse("history"), {"number": order.number}).content.decode()
    assert "原件序号1" in html and "原件第4行" in html


def test_unit_confirmation_without_actor_is_refused(world):
    unit_err = {"code": "unit_needs_confirmation", "message": "换算需人工确认"}
    batch = _pdf_batch("SYN-OWNER-A", [_line(1, "000777", None, [unit_err]) | {"printed_qty": 3}])
    with pytest.raises(DomainError) as err:
        import_posting.confirm_units(batch, {1: ("EA", None)}, "")
    assert err.value.code == "missing_actor"
    batch.refresh_from_db()
    assert not batch.ready


def test_duplicate_file_summary_does_not_claim_postable(client, empty):
    upload(client, "stock_export_synthetic.xlsx")
    confirm(client, ImportBatch.objects.get())
    html = upload(client, "stock_export_synthetic.xlsx", owner="SYN-IMPORT-OWNER", owner_new="").content.decode()
    assert "不能入账" in html and "可以确认入账" not in html and ">确认入账</button>" not in html
