"""Four prototype pages. Views parse forms and call inventory.domain /
inventory.queries only; no quantity logic lives here.
"""
import uuid

from django.contrib import messages
from django.core.management import call_command
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from . import domain, queries
from .domain import DomainError
from .models import Condition, LineCancellation, Location, OrderLine, Owner
from .synthetic import load_synthetic_fixture

SYNTHETIC_ACTORS = ["员工甲（合成）", "员工乙（合成）", "员工丙（合成）"]


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
