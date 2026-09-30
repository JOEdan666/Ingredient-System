"""Operator names for the actor drop-down and the check that an actor is allowed."""

from __future__ import annotations

from django.db import IntegrityError

from .domain import DomainError
from .models import Staff

SYNTHETIC_ACTORS = ["员工甲（合成）", "员工乙（合成）", "员工丙（合成）"]
MAX_NAME = 40


def real_mode() -> bool:
    return Staff.objects.filter(active=True).exists()


def actor_choices() -> list[str]:
    """Active staff, or the synthetic demo names while nobody has been added."""
    names = list(Staff.objects.filter(active=True).order_by("name").values_list("name", flat=True))
    return names or list(SYNTHETIC_ACTORS)


def check_actor(actor: str) -> str:
    """Return the actor if allowed; refuse anything else so history names a real person."""
    actor = (actor or "").strip()
    if not actor:
        raise DomainError("missing_actor", "必须选择操作人。")
    if actor not in actor_choices():
        raise DomainError("unknown_actor", f"「{actor}」不在员工名单里（或已停用），请重新选择操作人。")
    return actor


def add_staff(name: str) -> Staff:
    name = " ".join((name or "").split())
    if not name:
        raise DomainError("missing_name", "请填写员工姓名。")
    if len(name) > MAX_NAME:
        raise DomainError("too_long", f"姓名最多 {MAX_NAME} 个字。")
    if "（合成）" in name:
        raise DomainError("synthetic_name", "名字里带「（合成）」的是演示用的，请填真实姓名。")
    existing = Staff.objects.filter(name=name).first()
    if existing:
        if existing.active:
            raise DomainError("duplicate", f"「{name}」已经在名单里了。")
        existing.active = True
        existing.save(update_fields=["active"])
        return existing
    try:
        return Staff.objects.create(name=name)
    except IntegrityError:
        raise DomainError("duplicate", f"「{name}」已经在名单里了。")


def set_active(staff_id: int, active: bool) -> Staff:
    person = Staff.objects.filter(pk=staff_id).first()
    if person is None:
        raise DomainError("unknown_staff", "这个员工不存在。")
    if not active and person.active and Staff.objects.filter(active=True).count() == 1:
        raise DomainError("last_staff", "这是名单里最后一位在岗员工，停用后就没人能操作了。请先添加别人。")
    person.active = active
    person.save(update_fields=["active"])
    return person
