"""Named operators: demo names until real staff exist, then only active staff are accepted."""
import pytest
from django.urls import reverse

from inventory import domain, staff
from inventory.domain import DomainError
from inventory.models import Operation, Staff

DEMO = "员工甲（合成）"


def test_demo_names_offered_and_banner_shown_until_first_real_person(client, db):
    html = client.get(reverse("receiving")).content.decode()
    assert DEMO in html and "员工名单" in html and "操作人现在用的是演示名字" in html
    client.post(reverse("staff"), {"action": "add", "name": "陈大文"})
    html = client.get(reverse("receiving")).content.decode()
    assert "陈大文" in html and DEMO not in html and "操作人现在用的是演示名字" not in html


@pytest.mark.parametrize("name, code", [("", "missing_name"), ("   ", "missing_name"), ("乙" * 41, "too_long"),
                                        ("员工丁（合成）", "synthetic_name")])
def test_bad_names_refused(db, name, code):
    with pytest.raises(DomainError) as err:
        staff.add_staff(name)
    assert err.value.code == code and Staff.objects.count() == 0


def test_duplicate_and_reactivation(db):
    person = staff.add_staff(" 陈  大文 ")
    assert person.name == "陈 大文"  # whitespace tidied
    with pytest.raises(DomainError) as err:
        staff.add_staff("陈 大文")
    assert err.value.code == "duplicate"
    staff.add_staff("李小明")
    staff.set_active(person.pk, False)
    assert staff.add_staff("陈 大文").active is True and Staff.objects.count() == 2


def test_last_active_person_cannot_be_deactivated(db):
    only = staff.add_staff("陈大文")
    with pytest.raises(DomainError) as err:
        staff.set_active(only.pk, False)
    assert err.value.code == "last_staff" and Staff.objects.get().active


def test_real_mode_rejects_demo_and_deactivated_actor_and_writes_nothing(client, world):
    world.opening(10)
    chen = staff.add_staff("陈大文"); staff.add_staff("李小明")
    ops = Operation.objects.count()

    def accept(actor, number):
        return client.post(reverse("accept_order"), {"actor": actor, "operation_id": number, "owner": "SYN-OWNER-A",
                                                     "number": number, "product_1": "000777", "qty_1": "1"}, follow=True).content.decode()

    assert "不在员工名单" in accept(DEMO, "SYN-A")            # demo name no longer allowed
    assert "必须选择操作人" in accept("", "SYN-B")             # blank refused
    assert Operation.objects.count() == ops                    # nothing written
    assert "完成" in accept("陈大文", "SYN-C")                 # a listed person works
    staff.set_active(chen.pk, False)
    assert "不在员工名单" in accept("陈大文", "SYN-D")         # deactivated: refused
    assert Operation.objects.latest("created_at").actor == "陈大文"  # history keeps the name


def test_import_and_pallet_forms_also_check_the_actor(client, world):
    staff.add_staff("陈大文")
    world.opening(5)
    a = world.accept("SYN-ORD-1", 1).result["order_id"]
    html = client.post(reverse("pallet_sheet_form", args=[a]), {
        "ship_to": "合成", "address": "合成", "delivery_time": "上午", "pallet_count": "1", "orders": [a],
        "actor": DEMO}, follow=True).content.decode()
    assert "不在员工名单" in html
