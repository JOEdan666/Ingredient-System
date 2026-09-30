"""Tables for the T03 prototype, following docs/domain-model.md (T02).

Quantities are integers in the product's base unit. All writes go through
inventory.domain; views never change these rows directly.

Posted rows (StockMovement, ReservationEntry, LineCancellation, Operation)
are append-only (I7): saving an existing row raises ImmutableRowError.
Balance/availability rows are projections that domain commands update and
check_invariants() rebuilds from the append-only rows.
"""
from django.db import models
from django.db.models import F, Q


class ImmutableRowError(Exception):
    pass


class AppendOnly(models.Model):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableRowError(f"{type(self).__name__} rows are append-only (I7)")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableRowError(f"{type(self).__name__} rows are append-only (I7)")


class Condition(models.TextChoices):
    PENDING_INSPECTION = "PENDING_INSPECTION", "待检"
    AVAILABLE = "AVAILABLE", "合格"
    HOLD = "HOLD", "冻结"
    DAMAGED = "DAMAGED", "不合格"


class Owner(models.Model):
    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.code


class Product(models.Model):
    owner = models.ForeignKey(Owner, on_delete=models.PROTECT)
    code = models.CharField(max_length=40)  # text: keeps leading zeros
    name_zh = models.CharField(max_length=100, blank=True)
    name_en = models.CharField(max_length=100, blank=True)
    base_unit = models.CharField(max_length=10, default="EA")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "code"], name="uniq_product_owner_code")]

    def __str__(self):
        return f"{self.owner.code}/{self.code}"


class ProductAvailability(models.Model):
    """One row per (owner, product): the shared lock point (I11)."""

    owner = models.ForeignKey(Owner, on_delete=models.PROTECT)
    product = models.OneToOneField(Product, on_delete=models.PROTECT, related_name="availability")
    sellable = models.IntegerField(default=0)
    reserved = models.IntegerField(default=0)
    row_version = models.IntegerField(default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(sellable__gte=0), name="pa_sellable_nonneg"),
            models.CheckConstraint(condition=Q(reserved__gte=0), name="pa_reserved_nonneg"),
            models.CheckConstraint(condition=Q(reserved__lte=F("sellable")), name="pa_reserved_le_sellable"),
        ]

    @property
    def available(self):
        return self.sellable - self.reserved


class Location(models.Model):
    class Kind(models.TextChoices):
        RECEIVING = "RECEIVING", "收货区（未上架）"
        STORAGE = "STORAGE", "货架"

    code = models.CharField(max_length=40, unique=True)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.STORAGE)
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.code


class StockLot(models.Model):
    """Internal lot identity: one per receipt line or opening line (D04)."""

    class Source(models.TextChoices):
        RECEIPT = "RECEIPT", "收货"
        OPENING = "OPENING", "期初导入"

    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    source_type = models.CharField(max_length=10, choices=Source.choices)
    source_ref = models.CharField(max_length=80)  # receipt line / import line identity
    external_lot = models.CharField(max_length=80, blank=True)  # blank = unknown, never invented
    expiry_date = models.DateField(null=True, blank=True)  # null = unknown

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["product", "source_type", "source_ref"], name="uniq_lot_source")
        ]

    def __str__(self):
        return f"L{self.pk}"


class StockBalance(models.Model):
    """Projection keyed by (owner, product, lot, location, condition)."""

    owner = models.ForeignKey(Owner, on_delete=models.PROTECT)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    lot = models.ForeignKey(StockLot, on_delete=models.PROTECT)
    location = models.ForeignKey(Location, on_delete=models.PROTECT)
    condition = models.CharField(max_length=20, choices=Condition.choices)
    on_hand = models.IntegerField(default=0)
    allocated = models.IntegerField(default=0)
    row_version = models.IntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "product", "lot", "location", "condition"], name="uniq_balance_key"
            ),
            models.CheckConstraint(condition=Q(on_hand__gte=0), name="bal_on_hand_nonneg"),
            models.CheckConstraint(condition=Q(allocated__gte=0), name="bal_allocated_nonneg"),
            models.CheckConstraint(condition=Q(allocated__lte=F("on_hand")), name="bal_allocated_le_on_hand"),
        ]

    @property
    def free(self):
        """Unallocated physical quantity on this key (not product-level available)."""
        return self.on_hand - self.allocated


class Operation(models.Model):
    """Idempotency record: one row per successful command (A05).

    Inserted first inside the command transaction (unique primary key, as in
    D09); `result` is filled in before commit. Domain code never changes a
    committed row. A rejected command rolls back, so it leaves no row.
    """

    operation_id = models.CharField(max_length=64, primary_key=True)
    command = models.CharField(max_length=40)
    payload_hash = models.CharField(max_length=64)
    result = models.JSONField(null=True)
    actor = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)


class ReceiptNotice(models.Model):
    """Advance notice (预告). Never creates stock (I9)."""

    owner = models.ForeignKey(Owner, on_delete=models.PROTECT)
    number = models.CharField(max_length=40)
    created_by = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "number"], name="uniq_notice_number")]


class ReceiptNoticeLine(models.Model):
    notice = models.ForeignKey(ReceiptNotice, on_delete=models.PROTECT, related_name="lines")
    line_no = models.IntegerField()
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    qty_expected = models.IntegerField()
    expiry_date = models.DateField(null=True, blank=True)
    external_lot = models.CharField(max_length=80, blank=True)


class ReceiptLine(AppendOnly):
    """Actual receipt (实收) of one notice line (or ad hoc); creates one StockLot."""

    notice_line = models.ForeignKey(ReceiptNoticeLine, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="receipts")
    operation = models.ForeignKey(Operation, on_delete=models.PROTECT)
    lot = models.OneToOneField(StockLot, on_delete=models.PROTECT)
    qty_received = models.IntegerField()
    condition = models.CharField(max_length=20, choices=Condition.choices)
    location_code = models.CharField(max_length=40)
    actor = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)


class Order(models.Model):
    owner = models.ForeignKey(Owner, on_delete=models.PROTECT)
    number = models.CharField(max_length=40)
    source_ref = models.CharField(max_length=120, blank=True)  # e.g. synthetic PDF file/page
    created_by = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "number"], name="uniq_order_number")]

    def __str__(self):
        return self.number


class OrderLine(models.Model):
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="lines")
    line_no = models.IntegerField()
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    qty_ordered = models.IntegerField()
    requested_expiry = models.DateField(null=True, blank=True)
    source_line = models.CharField(max_length=40, blank=True)  # row in the imported source document (A09)
    # Projections of ReservationEntry / LineCancellation, checked by check_invariants().
    qty_unallocated = models.IntegerField(default=0)
    qty_cancelled = models.IntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["order", "line_no"], name="uniq_order_line"),
            models.CheckConstraint(condition=Q(qty_ordered__gt=0), name="line_qty_pos"),
            models.CheckConstraint(condition=Q(qty_unallocated__gte=0), name="line_unalloc_nonneg"),
            models.CheckConstraint(condition=Q(qty_cancelled__gte=0), name="line_cancel_nonneg"),
        ]


class Allocation(models.Model):
    order_line = models.ForeignKey(OrderLine, on_delete=models.PROTECT, related_name="allocations")
    balance = models.ForeignKey(StockBalance, on_delete=models.PROTECT, related_name="allocations")
    qty_allocated = models.IntegerField()
    qty_shipped = models.IntegerField(default=0)
    qty_released = models.IntegerField(default=0)
    # Snapshots so history survives master-data changes (A09, D03).
    location_code = models.CharField(max_length=40)
    expiry_date = models.DateField(null=True, blank=True)
    created_by = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(qty_shipped__gte=0) & Q(qty_released__gte=0)
                & Q(qty_allocated__gte=F("qty_shipped") + F("qty_released")),
                name="alloc_open_nonneg",
            )
        ]

    @property
    def qty_open(self):
        return self.qty_allocated - self.qty_shipped - self.qty_released


class ReservationEntry(AppendOnly):
    """Append-only reservation ledger. Product reserved = sum(qty).

    allocation is null for the line's unallocated (product-level) reservation.
    """

    class Kind(models.TextChoices):
        RESERVE = "RESERVE", "接单占用（未选货位）"
        CONVERT = "CONVERT", "转为具体分配"
        ALLOCATE = "ALLOCATE", "分配到批次/货位"
        CONSUME = "CONSUME", "发货消耗"
        RELEASE = "RELEASE", "取消释放"

    operation = models.ForeignKey(Operation, on_delete=models.PROTECT)
    order_line = models.ForeignKey(OrderLine, on_delete=models.PROTECT, related_name="reservation_entries")
    allocation = models.ForeignKey(Allocation, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="entries")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    qty = models.IntegerField()  # signed
    actor = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)


class StockMovement(AppendOnly):
    class Kind(models.TextChoices):
        OPENING = "OPENING", "期初"
        RECEIPT = "RECEIPT", "收货"
        MOVE_OUT = "MOVE_OUT", "移出"
        MOVE_IN = "MOVE_IN", "移入"
        CONDITION_OUT = "CONDITION_OUT", "状态转出"
        CONDITION_IN = "CONDITION_IN", "状态转入"
        SHIP = "SHIP", "发货"

    operation = models.ForeignKey(Operation, on_delete=models.PROTECT)
    kind = models.CharField(max_length=15, choices=Kind.choices)
    balance = models.ForeignKey(StockBalance, on_delete=models.PROTECT, related_name="movements")
    qty = models.IntegerField()  # signed, base unit
    location_code = models.CharField(max_length=40)  # snapshot
    condition = models.CharField(max_length=20, choices=Condition.choices)  # snapshot
    source_doc = models.CharField(max_length=80, blank=True)
    source_line = models.CharField(max_length=40, blank=True)
    actor = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)  # UTC
    business_date = models.DateField()  # Asia/Hong_Kong


class Shipment(AppendOnly):
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="shipments")
    operation = models.OneToOneField(Operation, on_delete=models.PROTECT)
    actor = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)


class ShipmentLine(AppendOnly):
    shipment = models.ForeignKey(Shipment, on_delete=models.PROTECT, related_name="lines")
    allocation = models.ForeignKey(Allocation, on_delete=models.PROTECT, related_name="shipment_lines")
    qty = models.IntegerField()
    movement = models.OneToOneField(StockMovement, on_delete=models.PROTECT)


class LineCancellation(AppendOnly):
    class Reason(models.TextChoices):
        UNPAID = "UNPAID", "客户未付款"
        CUSTOMER_REQUEST = "CUSTOMER_REQUEST", "客户要求"
        OTHER = "OTHER", "其他"

    order_line = models.ForeignKey(OrderLine, on_delete=models.PROTECT, related_name="cancellations")
    operation = models.ForeignKey(Operation, on_delete=models.PROTECT)
    qty = models.IntegerField()
    reason = models.CharField(max_length=20, choices=Reason.choices)
    actor = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)


class ImportBatch(models.Model):
    """One uploaded file: parsed lines kept for human confirmation, then posted once.

    Lives only in the local prototype database (never in the repository).
    The uploaded file itself is not kept; only the parsed lines and its hash.
    """

    class Kind(models.TextChoices):
        STOCK = "stock", "库存表（期初库存）"
        INSPECTION = "inspection", "验货纸（收货预告）"
        PDF_ORDER = "pdf_order", "PDF 送货单（出库订单）"

    class Status(models.TextChoices):
        PREVIEW = "PREVIEW", "待确认"
        POSTED = "POSTED", "已入账"

    kind = models.CharField(max_length=20, choices=Kind.choices)
    file_name = models.CharField(max_length=200)
    file_sha256 = models.CharField(max_length=64)
    owner_code = models.CharField(max_length=40)
    external_doc_no = models.CharField(max_length=80, blank=True)
    doc_date = models.DateField(null=True, blank=True)  # date printed on a PDF order
    # Cutover boundary for a stock snapshot (Q05), stated by a person when posting.
    snapshot_at = models.DateTimeField(null=True, blank=True)
    export_basis = models.CharField(max_length=20, blank=True)
    lines = models.JSONField(default=list)
    batch_errors = models.JSONField(default=list)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PREVIEW)
    created_at = models.DateTimeField(auto_now_add=True)
    posted_at = models.DateTimeField(null=True, blank=True)
    posted_by = models.CharField(max_length=40, blank=True)
    result = models.JSONField(null=True, blank=True)

    @property
    def recognized(self):
        return len(self.lines)

    @property
    def postable_count(self):
        return sum(1 for line in self.lines if line["postable"])

    @property
    def blocked_count(self):
        return self.recognized - self.postable_count

    @property
    def problem_count(self):
        return self.blocked_count + len(self.batch_errors)

    @property
    def ready(self):
        return bool(self.lines) and not self.batch_errors and self.blocked_count == 0


class PalletSheet(models.Model):
    """A set of pallet header sheets (板头纸) for one delivery.

    Everything printed is stored as typed (a snapshot), so a reprint shows the
    same text even if an order or customer record changes later.  Creating or
    printing a sheet never touches stock.
    """

    owner = models.ForeignKey(Owner, on_delete=models.PROTECT)
    orders = models.ManyToManyField(Order, related_name="pallet_sheets")
    order_numbers = models.CharField(max_length=200)  # printed text, e.g. "A & B"
    ship_to = models.CharField(max_length=100)  # 收貨客戶
    address = models.CharField(max_length=200)  # 送貨地址
    delivery_time = models.CharField(max_length=60)  # 送貨時間, free text as on the paper form
    pallet_count = models.PositiveSmallIntegerField()
    created_by = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(pallet_count__gte=1) & Q(pallet_count__lte=99),
                                              name="pallet_count_1_99")]


class Staff(models.Model):
    """Named operators for the actor drop-down (local database only, never committed).

    While the table is empty the prototype offers the synthetic demo names;
    once at least one active person exists, only active staff are accepted.
    Names are kept when someone leaves (active=False) because posted rows
    already carry them.
    """

    name = models.CharField(max_length=40, unique=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ErrorLog(models.Model):
    """One row per unexpected failure (T11). Deliberately holds NO business data: only the page address
    without its query string, the error class and where it was raised. The exception message is never
    stored because it can quote products, customers or quantities.
    """

    code = models.CharField(max_length=20, unique=True)  # shown to the employee, e.g. E-7F3A9C21
    created_at = models.DateTimeField(auto_now_add=True)
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=200)
    error_type = models.CharField(max_length=80)
    location = models.CharField(max_length=120, blank=True)  # file:line function of the innermost frame
