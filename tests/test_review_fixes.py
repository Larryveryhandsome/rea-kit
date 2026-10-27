"""Regression checks for review S2, using synthetic labels only."""
import tempfile
import unittest
from adapters.csv.customer_source import CsvCustomerSource
from adapters.storage import TenantStore


class ReviewFixTests(unittest.TestCase):
    def test_create_and_rename_reject_numeric_contact_labels_without_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = TenantStore(tmp)
            source = CsvCustomerSource(store)
            need = {'transaction': 'buy', 'preferred_areas': ['示範市'], 'budget_max': 1000}
            customer = source.save_need('synthetic', label='合成買方', need=need)
            path = store.path('synthetic', *source.CUSTOMERS)
            before = path.read_bytes()
            for label in ['1' * 10, '合成' + '2' * 7]:
                with self.assertRaises(ValueError):
                    source.save_need('synthetic', label=label, need=need)
                with self.assertRaises(ValueError):
                    source.update_identity('synthetic', customer['customer_id'], label=label)
                self.assertEqual(before, path.read_bytes())
