"""Inventory page as folders (approved acceptance sheet, 2026-09-30). One test per sheet line."""
import pytest
from django.urls import reverse

from inventory import domain, folders

from .conftest import ACTOR, new_op


@pytest.mark.parametrize("name, brand", [
    ("ADVANCE爱旺斯 农场鲜鸡 幼犬奶糕粮", "ADVANCE"),
    ("advance 小型犬粮", "ADVANCE"),
    ("原食生鲜 鸡肉猫粮10 lb.", "原食生鲜"),
    ("一个很长很长没有空格的商品名称", folders.OTHER),
    ("", folders.OTHER),
    (None, folders.OTHER),
])
def test_brand_is_read_from_the_name_start_or_goes_to_other(name, brand):
    assert folders.brand_of(name) == brand


def _catalog(world, brand_sizes):
    """Products under owner A named by brand; each gets 5 in stock at A-01."""
    owner = world.owner_a
    n = 0
    for brand, size in brand_sizes.items():
        for i in range(size):
            n += 1
            code = f"SYN-{n:03d}"
            domain.create_product(owner, code, name_zh=f"{brand} 合成商品{i}")
            domain.post_opening(operation_id=new_op(), actor=ACTOR, owner_code="SYN-OWNER-A", product_code=code,
                                source_ref=f"SYN-F-{n}", external_lot="", expiry_date="2027-01-01",
                                location_code="A-01", condition="AVAILABLE", qty=5)


def test_1_page_shows_closed_folders_with_counts_and_small_brands_merge_into_other(client, world):
    _catalog(world, {"ALPHA": 4, "BETA": 3, "TINY": 1})
    html = client.get(reverse("inventory")).content.decode()
    assert html.count('<details class="card folder">') == 3  # ALPHA, BETA, 其他 — all closed
    assert "📁 ALPHA" in html and "4 种商品" in html and "可用合计 <b>20</b>" in html
    assert "📁 TINY" not in html and "📁 其他" in html  # 1-product brand merged


def test_2_3_products_are_one_row_each_and_detail_is_a_full_row_below(client, world):
    _catalog(world, {"ALPHA": 3})
    html = client.get(reverse("inventory")).content.decode()
    assert html.count('<details class="prod">') >= 3  # closed product rows
    assert '<div class="pdetail">' in html and "A-01" in html and "2027-01-01" in html


def test_4_search_filters_products_and_opens_their_folder(client, world):
    _catalog(world, {"ALPHA": 3, "BETA": 3})
    html = client.get(reverse("inventory"), {"q": "SYN-005"}).content.decode()
    assert '<details class="card folder" open>' in html and "📁 BETA" in html and "📁 ALPHA" not in html
    assert "找到 1 种" in html
    html = client.get(reverse("inventory"), {"q": "不存在的东西"}).content.decode()
    assert "没有找到「不存在的东西」" in html


def test_5_not_sellable_is_shown_separately(client, world):
    _catalog(world, {"ALPHA": 3})
    domain.post_opening(operation_id=new_op(), actor=ACTOR, owner_code="SYN-OWNER-A", product_code="SYN-001",
                        source_ref="SYN-HOLD", external_lot="", expiry_date=None, location_code="A-01",
                        condition="HOLD", qty=7)
    html = client.get(reverse("inventory")).content.decode()
    assert "可用合计 <b>15</b>" in html and "另有不可售 7 件" in html


def test_batch_table_is_folded_unless_filtering(client, world):
    _catalog(world, {"ALPHA": 3})
    assert '<details class="card allbal">' in client.get(reverse("inventory")).content.decode()
    assert '<details class="card allbal" open>' in client.get(reverse("inventory"), {"location": "A-01"}).content.decode()
