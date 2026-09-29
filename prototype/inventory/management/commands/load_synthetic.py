from django.core.management.base import BaseCommand

from inventory.synthetic import load_synthetic_fixture


class Command(BaseCommand):
    help = "Load fixtures/synthetic/stock.json as opening stock (synthetic data only). Safe to re-run."

    def handle(self, *args, **options):
        result = load_synthetic_fixture()
        self.stdout.write(f"posted {result['rows']} synthetic opening rows (re-runs replay by operation_id)")
