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
from .receiving_batch import LineErrors
from . import allocation_batch, folders, import_posting, pallet_sheets, receiving_batch, staff
from .import_preview import PreviewError, parse_upload, problem_summary, recheck
from .models import Allocation, Condition, ImportBatch, LineCancellation, Location, Order, OrderLine, Owner, PalletSheet, Staff
from .synthetic import load_synthetic_fixture

MAX_UPLOAD_BYTES = 15 * 1024 * 1024


def _ctx(request, **extra):
    return {
        "actors": staff.actor_choices(),
        "real_staff": staff.real_mode(),
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
        res = fn(operation_id=request.POST.get("operation_id", ""),
                 actor=staff.check_actor(request.POST.get("actor", "")), **kwargs)
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
    q = request.GET.get("q", "").strip()
    summaries = queries.product_summaries(owner=f["owner"], product=f["product"])
    balances = queries.balance_rows(show_zero=show_zero, **f)
    folder_list = folders.build(summaries, queries.balance_rows(owner=f["owner"], product=f["product"]), q)
    return render(request, "inventory/inventory.html", _ctx(
        request, f=f, q=q, show_zero=show_zero, expand=request.GET.get("expand") == "1",
        folders=folder_list, product_total=len(summaries), folder_hits=sum(x["count"] for x in folder_list),
        balances=balances, filtering=any(f.values()) or show_zero,
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
        done = import_posting.confirm_units(batch, choices, staff.check_actor(request.POST.get("actor", "")))
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
            batch_id, staff.check_actor(request.POST.get("actor", "")), snapshot_at=snapshot_at,
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

def receiving_page(request, *, open_notice=None, posted=None, errors=None, status=200):
    locations = [l.code for l in Location.objects.filter(active=True).order_by("code")]
    notices = queries.notices()
    posted, errors = posted or {}, errors or {}
    for n in notices:
        mine = n["id"] == open_notice
        n["open"] = mine
        n["attention"], n["normal"] = [], []
        for l in n["lines"]:
            get = (lambda f, d, lid=l["id"]: posted.get(f"{f}_{lid}", d)) if mine else (lambda f, d, lid=None: d)
            l["f_qty"] = get("qty", str(l["qty_expected"]))
            l["f_loc"] = get("loc", "")
            l["f_expiry"] = get("expiry", l["expiry"].isoformat() if l["expiry"] else "")
            l["f_lot"] = get("lot", l["external_lot"])
            l["error"] = errors.get(l["id"], "")
            l["f_diff"] = int(l["f_qty"]) - l["qty_expected"] if l["f_qty"].strip().isdigit() else None
            ok = not l["error"] and l["f_diff"] == 0 and not l["f_loc"]
            (n["normal"] if ok else n["attention"]).append(l)
        n["f_default_location"] = posted.get("default_location") if mine and posted else None
    return render(request, "inventory/receiving.html", _ctx(
        request, notices=notices, pending=queries.pending_inspection(),
        open_notice=open_notice, posted=posted or {}, row_errors=errors or {},
        default_location="RECEIVING" if "RECEIVING" in locations else (locations[0] if locations else ""),
    ), status=status)


@require_POST
def receive_notice(request, notice_id):
    """Whole-notice receipt: every line checked first; one confirmation posts them all or none."""
    rows = {}
    for key, value in request.POST.items():
        field, _, line_id = key.rpartition("_")
        if field in ("qty", "loc", "expiry", "lot") and line_id.isdigit():
            rows.setdefault(int(line_id), {})[{"loc": "location"}.get(field, field)] = value
    try:
        result = receiving_batch.receive_notice(
            notice_id=notice_id, actor=staff.check_actor(request.POST.get("actor", "")),
            default_location=request.POST.get("default_location", ""),
            condition=request.POST.get("condition", ""), rows=rows)
    except receiving_batch.LineErrors as err:
        messages.error(request, f"整张单没有入库：{err.message}")
        return receiving_page(request, open_notice=notice_id, posted=request.POST, errors=err.errors, status=400)
    except DomainError as err:
        messages.error(request, f"整张单没有入库：{err.message}")
        return receiving_page(request, open_notice=notice_id, posted=request.POST, status=400)
    msg = f"整张单已入库：{result['lines']} 行，共 {result['qty']} 件。"
    if result["skipped"]:
        msg += f"另有 {result['skipped']} 行实收为 0（没到货），未入库。"
    messages.success(request, msg)
    return redirect("receiving")


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


def pallet_sheet_form(request, order_id):
    """Fill in and generate pallet header sheets (板头纸) for this order; never touches stock."""
    order = Order.objects.select_related("owner").filter(pk=order_id).first()
    if order is None:
        raise Http404("订单不存在")
    if request.method == "POST":
        try:
            sheet = pallet_sheets.create_sheet(
                order_ids=request.POST.getlist("orders"), ship_to=request.POST.get("ship_to"),
                address=request.POST.get("address"), delivery_time=request.POST.get("delivery_time"),
                pallet_count=request.POST.get("pallet_count"), actor=staff.check_actor(request.POST.get("actor", "")),
            )
        except (DomainError, ValueError) as err:
            messages.error(request, f"板头纸没有生成：{getattr(err, 'message', err)}")
        else:
            return redirect("pallet_sheet_print", sheet_id=sheet.pk)
    last = order.pallet_sheets.order_by("-pk").first()
    form = {
        "orders": set(map(int, request.POST.getlist("orders"))) or {order.pk},
        "ship_to": request.POST.get("ship_to", last.ship_to if last else ""),
        "address": request.POST.get("address", last.address if last else ""),
        "delivery_time": request.POST.get("delivery_time", last.delivery_time if last else ""),
        "pallet_count": request.POST.get("pallet_count", last.pallet_count if last else 1),
    }
    return render(request, "inventory/pallet_sheet_form.html", _ctx(
        request, order=order, form=form, suggest=pallet_sheets.suggestions(order.owner_id),
        same_owner_orders=Order.objects.filter(owner=order.owner).order_by("-pk")[:20],
        max_pallets=pallet_sheets.MAX_PALLETS,
    ))


def pallet_sheet_print(request, sheet_id):
    sheet = PalletSheet.objects.filter(pk=sheet_id).first()
    if sheet is None:
        raise Http404("板头纸不存在")
    back = sheet.orders.order_by("pk").first()
    return render(request, "inventory/pallet_sheet_print.html",
                  {"sheet": sheet, "pages": pallet_sheets.pages(sheet), "back": back})


def order_page(request, order_id, *, posted=None, errors=None, status=200, ship_posted=False, ship_errors=None):
    detail = queries.order_detail(order_id)
    if detail is None:
        raise Http404("订单不存在")
    alloc_posted = None if ship_posted else posted  # a failed shipment must not blank the allocation form
    errors, attention, ready, short = errors or {}, [], [], 0
    for l in detail["lines"]:
        need = l["numbers"]["unallocated"]
        if not need:
            continue
        suggested = allocation_batch.prefill(l)
        for c in l["candidates"]:
            key = f"pick_{l['id']}_{c['id']}"
            c["value"] = alloc_posted.get(key, "") if alloc_posted is not None else (str(suggested[c["id"]]) if c["id"] in suggested else "")
        entered = sum(int(c["value"]) for c in l["candidates"] if str(c["value"]).strip().isdigit())
        l["need"], l["entered"], l["gap"], l["error"] = need, entered, need - entered, errors.get(l["id"], "")
        l["prefilled"] = bool(suggested) and alloc_posted is None
        (ready if l["gap"] == 0 and not l["error"] else attention).append(l)
        short += l["gap"] > 0
    ship_rows, ship_attention, ship_ready = _ship_rows(detail, posted if ship_posted else None, ship_errors or {})
    remaining = sum(max(0, l["numbers"]["ordered"] - l["numbers"]["cancelled"] - l["numbers"]["shipped"])
                    for l in detail["lines"])
    return render(request, "inventory/order.html", _ctx(
        request, order=detail, reasons=LineCancellation.Reason.choices,
        sheets=PalletSheet.objects.filter(orders__pk=order_id).order_by("-pk"),
        attention=attention, ready=ready, short=short,
        all_allocated=not attention and not ready,
        ship_attention=ship_attention, ship_ready=ship_ready, ship_open=bool(ship_rows),
        remaining=remaining, all_shipped=remaining == 0,
    ), status=status)


def _ship_rows(detail, posted, errors):
    """One row per allocation that still has goods to ship; default = ship everything allocated."""
    rows = []
    for l in detail["lines"]:
        for a in l["allocations"]:
            if not a["open"]:
                continue
            key = f"ship_{a['id']}"
            value = posted.get(key, "") if posted is not None else str(a["open"])
            row = dict(a, line_no=l["line_no"], product=l["product"], key=key, value=value,
                       error=errors.get(a["id"], ""))
            row["left"] = a["open"] - int(value) if str(value).strip().isdigit() else None
            rows.append(row)
    attention = [r for r in rows if r["error"] or r["left"] != 0]
    ready = [r for r in rows if not (r["error"] or r["left"] != 0)]
    return rows, attention, ready


@require_POST
def allocate(request, order_id):
    """Whole-order allocation: one save for every line (all or nothing)."""
    entries = {}
    for key, value in request.POST.items():
        parts = key.split("_")
        if len(parts) == 3 and parts[0] == "pick" and parts[1].isdigit() and parts[2].isdigit():
            entries.setdefault(int(parts[1]), {})[int(parts[2])] = value
    try:
        result = allocation_batch.allocate_order(
            order_id=order_id, actor=staff.check_actor(request.POST.get("actor", "")),
            operation_id=request.POST.get("operation_id", ""), entries=entries)
    except LineErrors as err:
        messages.error(request, f"整张订单没有保存：{err.message}")
        return order_page(request, order_id, posted=request.POST, errors=err.errors, status=400)
    except DomainError as err:
        messages.error(request, f"整张订单没有保存：{err.message}")
        return order_page(request, order_id, posted=request.POST, status=400)
    messages.success(request, f"分配已保存：{result['lines']} 行，共 {result['qty']} 件。")
    return redirect("order_detail", order_id=order_id)


@require_POST
def ship(request, order_id):
    """Whole-order shipment: every row checked first, then one domain.ship call (one transaction)."""
    open_allocs = {a.pk: a for a in Allocation.objects.filter(order_line__order_id=order_id)}
    items, errors = [], {}
    for key, value in request.POST.items():
        if not key.startswith("ship_"):
            continue
        raw_id, text = key[5:], value.strip()
        if not raw_id.isdigit() or int(raw_id) not in open_allocs:
            messages.error(request, "整张订单没有发货：有一项分配不属于这张订单。")
            return order_page(request, order_id, posted=request.POST, status=400, ship_posted=True)
        a = open_allocs[int(raw_id)]
        if text == "" or text == "0":
            continue
        if not text.isdigit():
            errors[a.pk] = "发货数量必须是 0 或正整数"
        elif int(text) > a.qty_open:
            errors[a.pk] = f"多发了 {int(text) - a.qty_open}（这项只分配了 {a.qty_open} 件未发）"
        else:
            items.append({"allocation_id": a.pk, "qty": int(text)})
    if errors:
        messages.error(request, f"整张订单没有发货：有 {len(errors)} 项需要改。")
        return order_page(request, order_id, posted=request.POST, status=400, ship_posted=True, ship_errors=errors)
    if not items:
        messages.error(request, "整张订单没有发货：每一项都是 0，没有东西可以发。")
        return order_page(request, order_id, posted=request.POST, status=400, ship_posted=True)
    try:
        res = domain.ship(operation_id=request.POST.get("operation_id", ""),
                          actor=staff.check_actor(request.POST.get("actor", "")), order_id=order_id, items=items)
    except DomainError as err:
        messages.error(request, f"整张订单没有发货：{err.message}")
        return order_page(request, order_id, posted=request.POST, status=400, ship_posted=True)
    total = sum(i["qty"] for i in items)
    if res.replayed:
        messages.warning(request, "同一张发货单重复提交，已按第一次的结果处理，没有再发一次。")
    else:
        messages.success(request, f"发货完成：{len(items)} 项，共 {total} 件。")
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


# 员工名单 -----------------------------------------------------------------

def staff_page(request):
    """Add or deactivate the named operators shown in every 操作人 drop-down."""
    if request.method == "POST":
        try:
            if request.POST.get("action") == "add":
                person = staff.add_staff(request.POST.get("name", ""))
                messages.success(request, f"已添加「{person.name}」。")
            else:
                person = staff.set_active(int(request.POST.get("staff_id", "0")), request.POST.get("action") == "activate")
                messages.success(request, f"已{'恢复' if person.active else '停用'}「{person.name}」。")
        except (DomainError, ValueError) as err:
            messages.error(request, f"没有改成：{getattr(err, 'message', err)}")
        return redirect("staff")
    return render(request, "inventory/staff.html", _ctx(request, people=Staff.objects.order_by("-active", "name")))
