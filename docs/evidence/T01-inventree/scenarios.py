"""T01 evaluation: run Ingredient-System acceptance scenarios against InvenTree 1.5.6 models/serializers.

Synthetic data only. Run with: python manage.py shell < scenarios.py
"""
import datetime
from decimal import Decimal as D

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError as DjValidationError
from rest_framework.exceptions import ValidationError as DrfValidationError

from company.models import Company
from order.models import SalesOrder, SalesOrderLineItem, SalesOrderShipment, SalesOrderAllocation
from order.serializers import SalesOrderShipmentAllocationSerializer
from part.models import Part
from stock.models import StockItem, StockLocation, StockItemTracking
from stock.status_codes import StockStatus

RESULTS = []


def rec(case, claim, ok, detail=''):
    RESULTS.append((case, claim, 'PASS' if ok else 'FAIL', detail))
    print(f"[{case}] {'OK ' if ok else 'NO '} {claim} {detail}")


user, _ = User.objects.get_or_create(username='eval', defaults={'is_superuser': True, 'is_staff': True})
cust, _ = Company.objects.get_or_create(name='DEMO-CUSTOMER', defaults={'is_customer': True})
locA, _ = StockLocation.objects.get_or_create(name='A-01')
locB, _ = StockLocation.objects.get_or_create(name='B-01')
locR, _ = StockLocation.objects.get_or_create(name='RECEIVING')
locC, _ = StockLocation.objects.get_or_create(name='C-01')

n = [0]


def new_part(ipn):
    n[0] += 1
    return Part.objects.create(name=f'DEMO {ipn} #{n[0]}', IPN=ipn, salable=True, component=False)


def new_so(part, qty):
    so = SalesOrder.objects.create(customer=cust, reference=f'SO-{9000 + n[0]}-{SalesOrder.objects.count()}')
    line = SalesOrderLineItem.objects.create(order=so, part=part, quantity=qty)
    ship = SalesOrderShipment.objects.create(order=so, reference=f'S{SalesOrderShipment.objects.count() + 1}')
    so.issue_order()
    return so, line, ship


def allocate(so, line, ship, item, qty):
    s = SalesOrderShipmentAllocationSerializer(
        data={'items': [{'line_item': line.pk, 'stock_item': item.pk, 'quantity': str(qty)}], 'shipment': ship.pk},
        context={'order': so, 'request': None},
    )
    try:
        s.is_valid(raise_exception=True)
        s.save()
        return True, ''
    except (DrfValidationError, DjValidationError) as e:
        return False, str(e)[:120]


def state(part):
    part.refresh_from_db()
    return (part.total_stock, part.allocation_count(), part.available_stock)


# ---------- A10 / D07: on-hand 100, order 20, ship, cancel ----------
p = new_part('000123')
rec('fixture', 'IPN keeps leading zeros as text', Part.objects.get(pk=p.pk).IPN == '000123')
it = StockItem.objects.create(part=p, location=locA, quantity=100, batch='DEMO-LOT-1',
                              expiry_date=datetime.date(2027, 9, 2))
so, line, ship = new_so(p, 20)
ok, msg = allocate(so, line, ship, it, 20)
rec('A10', 'allocate 20 of 100', ok, msg)
rec('A10/D07', 'after allocation: on-hand 100, allocated 20, available 80', state(p) == (100, 20, 80), str(state(p)))
ship.complete_shipment(user)
rec('A10/D07', 'after shipping 20: on-hand 80, allocated 0, available 80 (no double deduction)',
    state(p) == (80, 0, 80), str(state(p)))

# Cancel before shipment
p2 = new_part('000124')
it2 = StockItem.objects.create(part=p2, location=locA, quantity=100)
so2, line2, ship2 = new_so(p2, 20)
allocate(so2, line2, ship2, it2, 20)
so2.cancel_order()
rec('A10', 'cancel before ship releases allocation: available back to 100', state(p2) == (100, 0, 100), str(state(p2)))
second = so2.can_cancel
rec('A10', 'second cancel is refused (order no longer open)', second is False, f'can_cancel={second}')
left = SalesOrderAllocation.objects.filter(line__order=so2).count()
rec('A10/D07', 'cancelled order keeps an allocation/reversal record per line', left > 0,
    f'allocations remaining after cancel={left} (deleted)')

# Partial ship 8, then cancel remaining 12
p3 = new_part('000125')
it3 = StockItem.objects.create(part=p3, location=locA, quantity=100)
so3, line3, ship3a = new_so(p3, 20)
ship3b = SalesOrderShipment.objects.create(order=so3, reference='S-B')
allocate(so3, line3, ship3a, it3, 8)
allocate(so3, line3, ship3b, it3, 12)
ship3a.complete_shipment(user)
rec('A10', 'after partial ship 8: on-hand 92, allocated 12, available 80', state(p3) == (92, 12, 80), str(state(p3)))
so3.refresh_from_db()
so3.cancel_order()
rec('A10', 'cancel remaining 12: on-hand 92, available 92 (not 100)', state(p3) == (92, 0, 92), str(state(p3)))

# Per-line cancel: is there a per-line cancel action?
rec('A10', 'per-line cancel action exists on SalesOrderLineItem',
    any(hasattr(SalesOrderLineItem, a) for a in ('cancel', 'cancel_line', 'cancel_order')),
    'no per-line cancel method; only whole-order cancel or edit/delete line')

# ---------- A02: multi-location allocation, ship, move ----------
p4 = new_part('000126')
a = StockItem.objects.create(part=p4, location=locA, quantity=6, batch='DEMO-LOT-1')
b = StockItem.objects.create(part=p4, location=locB, quantity=8, batch='DEMO-LOT-1')
so4, line4, ship4 = new_so(p4, 10)
allocate(so4, line4, ship4, a, 6)
allocate(so4, line4, ship4, b, 4)
rec('A02', 'employee-chosen A6 + B4: available = 4', state(p4)[2] == 4, str(state(p4)))
ship4.complete_shipment(user)
rec('A02', 'after ship: on-hand 4 (B), allocated 0, available 4', state(p4) == (4, 0, 4), str(state(p4)))
remaining = StockItem.objects.filter(part=p4, quantity__gt=0, customer=None, sales_order=None)
rec('A02', 'remaining stock only at B-01', [(i.location.name, i.quantity) for i in remaining] == [('B-01', 4)],
    str([(i.location.name, float(i.quantity)) for i in remaining]))
b.refresh_from_db()
b.move(locC, 'reorganise', user, quantity=2)
after = sorted((i.location.name, float(i.quantity)) for i in StockItem.objects.filter(part=p4, customer=None, sales_order=None))
rec('A02', 'move 2 of B4 to C-01 conserves total 4', state(p4)[0] == 4, str(after))
trk = StockItemTracking.objects.filter(item__part=p4).count()
rec('A04', 'stock tracking history recorded for ship/move', trk > 0, f'tracking rows={trk}')

# ---------- A04: rename location after shipment; history shows source? ----------
shipped = StockItem.objects.filter(part=p4, customer=cust)
names_before = [i.location.name if i.location else None for i in shipped]
rec('A04', 'shipped stock keeps a location snapshot', any(names_before), f'shipped item locations={names_before}')

# ---------- A06 (sequential proxy): over-allocation rejected ----------
p5 = new_part('000127')
it5 = StockItem.objects.create(part=p5, location=locA, quantity=5)
soA, lA, sA = new_so(p5, 4)
soB, lB, sB = new_so(p5, 4)
okA, _ = allocate(soA, lA, sA, it5, 4)
okB, msgB = allocate(soB, lB, sB, it5, 4)
rec('A06', 'available 5: second allocation of 4 rejected', okA and not okB, msgB)

# ---------- A01: receiving / unaccepted stock ----------
p6 = new_part('000128')
q = StockItem.objects.create(part=p6, location=locR, quantity=3, status=StockStatus.QUARANTINED.value)
rec('A01', 'quarantined (pending inspection) stock excluded from on-hand', state(p6)[0] == 0, str(state(p6)))
so6, l6, s6 = new_so(p6, 3)
ok6, msg6 = allocate(so6, l6, s6, q, 3)
rec('A01', 'quarantined stock cannot be allocated', not ok6, msg6 or 'allocation ACCEPTED')
ok_r = StockItem.objects.create(part=p6, location=locR, quantity=8)
so7, l7, s7 = new_so(p6, 3)
ok7, msg7 = allocate(so7, l7, s7, ok_r, 3)
rec('A01', 'accepted stock still in RECEIVING can be allocated/shipped', ok7, msg7)

# ---------- A03: owner isolation, same expiry different receipt ----------
rec('A03', 'StockItem has a consignor/owner-of-goods field distinct from permission owner',
    any(f.name in ('consignor', 'goods_owner', 'client') for f in StockItem._meta.get_fields()),
    'fields: owner(permission)=%s customer=%s' % (
        any(f.name == 'owner' for f in StockItem._meta.get_fields()),
        any(f.name == 'customer' for f in StockItem._meta.get_fields())))
rec('A03', 'order line pins expiry', any(f.name in ('expiry_date', 'target_expiry') for f in SalesOrderLineItem._meta.get_fields()),
    'expiry only enforced by employee choosing the stock item')

# ---------- A05: idempotency key on allocation ----------
rec('A05', 'allocation API accepts an idempotency / operation id',
    'operation_id' in SalesOrderShipmentAllocationSerializer().fields or 'idempotency_key' in str(SalesOrderShipmentAllocationSerializer().fields),
    'retry of the same POST creates a second allocation unless rejected by quantity')

print('\nSUMMARY')
for r in RESULTS:
    print('\t'.join(r))
