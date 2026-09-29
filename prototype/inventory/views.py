"""Four prototype pages. Views parse forms and call inventory.domain /
inventory.queries only; no quantity logic lives here.
"""
import uuid
from datetime import datetime

from django.contrib import messages
from django.core.management import call_command
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from . import domain, queries
from .domain import DomainError
from . import import_posting
from .import_preview import PreviewError, parse_upload, problem_summary, recheck
from .models import Condition, ImportBatch, LineCancellation, Location, OrderLine, Owner
from .synthetic import load_synthetic_fixture

SYNTHETIC_ACTORS = ["员工甲（合成）", "员工乙（合成）", "员工丙（合成）"]
MAX_UPLOAD_BYTES = 15 * 1024 * 1024


def _ctx(request, **extra):
    return {
        "actors": SYNTHETIC_ACTORS,
        "owners": Owner.objects.order_by("code"),
        "locations": Location.objects.filter(active=True).order_by("code"),
        "conditions": Condition.choices,
        "new_op": lambda: uuid.uuid4().hex,
        **extra,
    }


def _int(value, field):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise DomainError("bad_quantity", f"{field}必须是整数。")


def _line_in_order(order_id, raw_line_id):
    """The line id comes from a hidden form field; make sure it belongs to the
    order in the URL, so a tampered form cannot act on another order."""
    line_id = _int(raw_line_id, "订单行")
    if not OrderLine.objects.filter(pk=line_id, order_id=order_id).exists():
        raise DomainError("line_not_in_order", "这一行不属于当前订单，拒绝执行。")
    return line_id


def _submit(request, label, fn, **kwargs):
    """Run one domain command from a form and report the outcome."""
    try:
        res = fn(operation_id=request.POST.get("operation_id", ""), actor=request.POST.get("actor", ""), **kwargs)
    except DomainError as err:
        messages.error(request, f"{label}被拒绝：{err.message}")
        return None
    if res.replayed:
        messages.warning(request, f"{label}：同一操作编号重复提交，已返回第一次的结果，没有再执行一次。")
    else:
        messages.success(request, f"{label}完成。")
    return res


# 库存 ---------------------------------------------------------------------

def inventory_page(request):
    f = {k: request.GET.get(k, "").strip() for k in ("owner", "product", "lot", "expiry", "location", "condition")}
    show_zero = request.GET.get("show_zero") == "1"
    return render(request, "inventory/inventory.html", _ctx(
        request, f=f, show_zero=show_zero, expand=request.GET.get("expand") == "1",
        summaries=queries.product_summaries(owner=f["owner"], product=f["product"]),
        balances=queries.balance_rows(show_zero=show_zero, **f),
    ))


@require_POST
def move(request):
    try:
        _submit(request, "移位", domain.move_stock, balance_id=_int(request.POST.get("balance_id"), "库存记录"),
                qty=_int(request.POST.get("qty"), "移位数量"), to_location_code=request.POST.get("to_location", ""))
    except DomainError as err:
        messages.error(request, f"移位被拒绝：{err.message}")
    return redirect(request.POST.get("next") or "inventory")


@require_POST
def reset_synthetic(request):
    """Prototype convenience only: wipe the local SQLite data and reload the synthetic fixture."""
    call_command("flush", interactive=False, verbosity=0)
    result = load_synthetic_fixture()
    messages.success(request, f"已清空本地原型数据并重新载入合成数据（{result['rows']} 行期初）。")
    return redirect("inventory")


# 文件预览 -----------------------------------------------------------------

def import_preview_page(request):
    """Step 1: choose a file and an owner. The kind of file is detected from its content."""
    if request.method == "POST":
        upload = request.FILES.get("file")
        owner = (request.POST.get("owner_new") or "").strip() or (request.POST.get("owner") or "").strip()
        if upload is None:
            messages.error(request, "请先点「选择文件」选一个库存表、验货纸或 PDF 送货单。")
        elif upload.size > MAX_UPLOAD_BYTES:
            messages.error(request, "文件超过 15 MB，拒绝在原型中解析。")
        else:
            try:
                batch = parse_upload(upload, owner_code=owner, external_doc_no=request.POST.get("external_doc_no", ""))
            except PreviewError as err:
                messages.error(request, str(err))
            else:
                batch.save()
                return redirect("import_detail", batch_id=batch.pk)
    # Owners already in the system, plus owners typed for files not posted yet,
    # so a person never has to type the same owner twice.
    names = dict(Owner.objects.order_by("code").values_list("code", "name"))
    for code in ImportBatch.objects.values_list("owner_code", flat=True).distinct():
        names.setdefault(code, code)
    owners = [{"code": c, "name": n} for c, n in sorted(names.items())]
    return render(request, "inventory/import_preview.html", _ctx(
        request, owners=owners, default_owner=owners[0]["code"] if len(owners) == 1 else "",
        batches=[(b, import_posting.blocker_for(b)) for b in ImportBatch.objects.order_by("-pk")[:10]],
    ))


def import_detail(request, batch_id):
    """Step 2: look at what was read, fix units if needed, then confirm posting."""
    batch = ImportBatch.objects.filter(pk=batch_id).first()
    if batch is None:
        raise Http404
    recheck(batch)
    return render(request, "inventory/import_detail.html", _ctx(
        request, batch=batch, problems=problem_summary(batch),
        unit_rows=[l for l in batch.lines if any(e["code"] == "unit_needs_confirmation" for e in l["errors"])],
        owner_exists=Owner.objects.filter(code=batch.owner_code).exists(),
        blocker=import_posting.blocker_for(batch),
        cutover_question=import_posting.order_needs_cutover_check(batch),
        export_basis=import_posting.EXPORT_BASIS,
    ))


@require_POST
def import_units(request, batch_id):
    batch = ImportBatch.objects.filter(pk=batch_id).first()
    if batch is None:
        raise Http404
    choices = {}
    for line in batch.lines:
        unit = request.POST.get(f"unit_{line['row']}", "")
        if unit in ("EA", "CS"):
            raw = request.POST.get(f"per_case_{line['row']}", "").strip()
            per_case = int(raw) if raw.isdigit() else None
            choices[line["row"]] = (unit, per_case)
    try:
        done = import_posting.confirm_units(batch, choices, request.POST.get("actor", ""))
    except DomainError as err:
        messages.error(request, f"单位确认被拒绝：{err.message}")
    else:
        if done:
            messages.success(request, f"已确认 {done} 行的单位。")
        else:
            messages.error(request, "没有选择任何单位：请在每一行选「按件」或「按箱」。")
    return redirect("import_detail", batch_id=batch_id)


@require_POST
def import_post(request, batch_id):
    snapshot_at = None
    raw = request.POST.get("snapshot_at", "").strip()
    if raw:
        try:
            snapshot_at = datetime.fromisoformat(raw)
        except ValueError:
            messages.error(request, f"导出时间「{raw}」看不懂，请用日期时间选择器填写。")
            return redirect("import_detail", batch_id=batch_id)
    try:
        result = import_posting.post_batch(
            batch_id, request.POST.get("actor", ""), snapshot_at=snapshot_at,
            export_basis=request.POST.get("export_basis", ""),
            confirm_not_in_snapshot=request.POST.get("confirm_not_in_snapshot") == "1",
        )
    except ImportBatch.DoesNotExist:
        raise Http404
    except DomainError as err:
        messages.error(request, f"入账被拒绝，什么都没有写入：{err.message}")
    else:
        messages.success(request, f"入账完成：{result['lines']} 行已写入。")
    return redirect("import_detail", batch_id=batch_id)


@require_POST
def reset_empty(request):
    """Prototype convenience only: wipe the local SQLite data so real files start from nothing."""
    call_command("flush", interactive=False, verbosity=0)
    messages.success(request, "已清空本机原型数据。现在可以从库存表开始导入真实文件。")
    return redirect("import_preview")


# 收货 ---------------------------------------------------------------------

def receiving_page(request):
    return render(request, "inventory/receiving.html", _ctx(
        request, notices=queries.notices(), pending=queries.pending_inspection(),
    ))


@require_POST
def create_notice(request):
    lines = []
    for i in range(1, 4):
        code = request.POST.get(f"product_{i}", "").strip()
        if not code:
            continue
        lines.append({"product": code, "qty": request.POST.get(f"qty_{i}", ""),
                      "expiry": request.POST.get(f"expiry_{i}", "") or None,
                      "external_lot": request.POST.get(f"lot_{i}", "").strip()})
    try:
        for line in lines:
            line["qty"] = _int(line["qty"], "预告数量")
        _submit(request, "新建预告", domain.create_notice, owner_code=request.POST.get("owner", ""),
                number=request.POST.get("number", "").strip(), lines=lines)
    except DomainError as err:
        messages.error(request, f"新建预告被拒绝：{err.message}")
    return redirect("receiving")


@require_POST
def confirm_receipt(request):
    try:
        _submit(request, "实收", domain.confirm_receipt,
                notice_line_id=_int(request.POST.get("notice_line_id"), "预告行"),
                qty=_int(request.POST.get("qty"), "实收数量"),
                expiry_date=request.POST.get("expiry") or None,
                external_lot=request.POST.get("external_lot", "").strip(),
                location_code=request.POST.get("location", ""),
                condition=request.POST.get("condition", ""))
    except DomainError as err:
        messages.error(request, f"实收被拒绝：{err.message}")
    return redirect("receiving")


@require_POST
def change_condition(request):
    try:
        _submit(request, "改状态", domain.change_condition,
                balance_id=_int(request.POST.get("balance_id"), "库存记录"),
                qty=_int(request.POST.get("qty"), "数量"), to_condition=request.POST.get("to_condition", ""))
    except DomainError as err:
        messages.error(request, f"改状态被拒绝：{err.message}")
    return redirect(request.POST.get("next") or "receiving")


# 出库 ---------------------------------------------------------------------

def outbound_page(request):
    return render(request, "inventory/outbound.html", _ctx(request, orders=queries.order_list()))


@require_POST
def accept_order(request):
    lines = []
    try:
        for i in range(1, 4):
            code = request.POST.get(f"product_{i}", "").strip()
            if not code:
                continue
            lines.append({"product": code, "qty": _int(request.POST.get(f"qty_{i}"), "订购数量"),
                          "requested_expiry": request.POST.get(f"expiry_{i}", "") or None})
        res = _submit(request, "接单", domain.accept_order, owner_code=request.POST.get("owner", ""),
                      number=request.POST.get("number", "").strip(), lines=lines,
                      source_ref=request.POST.get("source_ref", "").strip())
    except DomainError as err:
        messages.error(request, f"接单被拒绝：{err.message}")
        res = None
    if res:
        return redirect("order_detail", order_id=res.result["order_id"])
    return redirect("outbound")


def order_page(request, order_id):
    detail = queries.order_detail(order_id)
    if detail is None:
        raise Http404("订单不存在")
    return render(request, "inventory/order.html", _ctx(request, order=detail, reasons=LineCancellation.Reason.choices))


@require_POST
def allocate(request, order_id):
    picks = []
    try:
        for key, value in request.POST.items():
            if key.startswith("pick_") and value.strip():
                q = _int(value, "分配数量")
                if q:
                    picks.append({"balance_id": _int(key[5:], "库存记录编号"), "qty": q})
        _submit(request, "分配批次/货位", domain.allocate_line,
                line_id=_line_in_order(order_id, request.POST.get("line_id")), picks=picks)
    except DomainError as err:
        messages.error(request, f"分配被拒绝：{err.message}")
    return redirect("order_detail", order_id=order_id)


@require_POST
def ship(request, order_id):
    items = []
    try:
        for key, value in request.POST.items():
            if key.startswith("ship_") and value.strip():
                q = _int(value, "发货数量")
                if q:
                    items.append({"allocation_id": _int(key[5:], "分配记录编号"), "qty": q})
        _submit(request, "发货", domain.ship, order_id=order_id, items=items)
    except DomainError as err:
        messages.error(request, f"发货被拒绝：{err.message}")
    return redirect("order_detail", order_id=order_id)


@require_POST
def cancel_line(request, order_id):
    raw = request.POST.get("qty", "").strip()
    try:
        _submit(request, "逐行取消", domain.cancel_line, line_id=_line_in_order(order_id, request.POST.get("line_id")),
                qty=_int(raw, "取消数量") if raw else None, reason=request.POST.get("reason", ""))
    except DomainError as err:
        messages.error(request, f"取消被拒绝：{err.message}")
    return redirect("order_detail", order_id=order_id)


# 历史查询 -----------------------------------------------------------------

def history_page(request):
    number = request.GET.get("number", "").strip()
    return render(request, "inventory/history.html", _ctx(
        request, number=number, results=queries.order_history(number) if number else None,
    ))
