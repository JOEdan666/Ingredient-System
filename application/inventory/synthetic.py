"""Load fixtures/synthetic/stock.json (SYNTHETIC ONLY, never real opening stock).

Each fixture row is posted as an OPENING movement through the domain layer,
so the prototype starts from the same rules the pages use.
"""
import json
from pathlib import Path

from django.conf import settings

from . import domain
from .models import Location, Owner, Product

SYNTHETIC_ACTOR = "synthetic-loader"

# Synthetic master data that the fixture file does not carry.
SYNTHETIC_LOCATIONS = [
    ("RECEIVING", Location.Kind.RECEIVING),
    ("A-01", Location.Kind.STORAGE),
    ("B-01", Location.Kind.STORAGE),
    ("C-01", Location.Kind.STORAGE),
]


def load_synthetic_fixture(path: Path | None = None) -> dict:
    path = Path(path or settings.SYNTHETIC_FIXTURE)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("synthetic") is not True:
        raise ValueError(f"{path} is not marked synthetic; refusing to load it.")
    for code, kind in SYNTHETIC_LOCATIONS:
        Location.objects.get_or_create(code=code, defaults={"kind": kind})
    posted = 0
    for i, row in enumerate(data["stock"], start=1):
        owner, _ = Owner.objects.get_or_create(code=row["owner"], defaults={"name": f"合成货主 {row['owner']}"})
        if not Product.objects.filter(owner=owner, code=row["sku"]).exists():
            domain.create_product(owner, row["sku"], name_zh=f"合成商品 {row['sku']}", base_unit=row["unit"])
        domain.post_opening(
            operation_id=f"synthetic-opening-{path.name}-{i}",
            actor=SYNTHETIC_ACTOR,
            owner_code=row["owner"],
            product_code=row["sku"],
            source_ref=row["receipt_line"],
            external_lot=row.get("lot") or "",
            expiry_date=row.get("expiry"),
            location_code=row["location"],
            condition=row["condition"],
            qty=row["quantity"],
            source_doc=f"fixtures/synthetic/{path.name}",
        )
        posted += 1
    return {"rows": posted, "order": data.get("order")}
