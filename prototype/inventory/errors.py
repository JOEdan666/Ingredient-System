"""Unexpected-failure handling (T11): show the employee a code, keep a business-data-free record.

Only exceptions that reach the middleware are logged. Expected refusals (not enough stock, bad quantity,
unknown order) are answered by the views themselves with a 400/404 and never get here.
"""
from __future__ import annotations

import logging
import os
import traceback
import uuid

from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.http import Http404
from django.shortcuts import render

from .models import ErrorLog

log = logging.getLogger("inventory.errors")
KEEP = 1000  # newest rows kept; older ones are pruned so the table cannot grow without bound
LEAVE_TO_DJANGO = (Http404, PermissionDenied, SuspiciousOperation)  # already answered as 4xx by Django


def _location(exc: BaseException) -> str:
    frames = traceback.extract_tb(exc.__traceback__)
    if not frames:
        return ""
    mine = [f for f in frames if os.sep + "inventory" + os.sep in f.filename] or frames
    f = mine[-1]
    return f"{os.path.basename(f.filename)}:{f.lineno} {f.name}"[:120]


def record(request, exc: BaseException) -> str | None:
    """Write the log row; return its code, or None if the record could not be written."""
    try:
        row = ErrorLog.objects.create(
            code="E-" + uuid.uuid4().hex[:8].upper(), method=request.method[:10], path=request.path[:200],
            error_type=type(exc).__name__[:80], location=_location(exc))
        ErrorLog.objects.filter(pk__lte=row.pk - KEEP).delete()
        return row.code
    except Exception:  # the log must never hide the friendly page (database down, disk full, ...)
        log.exception("could not write ErrorLog")
        return None


class ErrorLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, LEAVE_TO_DJANGO):
            return None
        log.error("unhandled error on %s %s", request.method, request.path, exc_info=exception)
        code = record(request, exception)
        # real_staff=True only hides the demo-name banner on this page; the page never touches the database.
        return render(request, "inventory/error500.html", {"code": code, "real_staff": True}, status=500)
