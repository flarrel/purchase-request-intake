import json
import unittest
from datetime import date
from pathlib import Path

from helpers import temporary_database_dir

from intake.data import parse_csv
from intake.skill import LlamaProvider, ProviderFailure
from intake.store import Store
from intake.workflow import export_operations, export_register, review_request, run_request

NOTE = "Vendor: Toko Fiktif; barang: kabel HDMI; jumlah 3 unit; untuk ruang rapat."
GOOD = {"vendor": "Toko Fiktif", "item": "kabel HDMI", "quantity": 3, "category": "it", "summary": NOTE}


class PluginStub:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = 0

    def complete(self, instructions, note, seed):
        self.calls += 1
        reply = next(self.responses)
        if isinstance(reply, Exception):
            raise reply
        return json.dumps(reply) if isinstance(reply, dict) else reply


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = temporary_database_dir()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "requests.sqlite3")

    def ingest(self, ref, amount=500_000):
        text = (f"reference,department,date,currency,amount,notes\n"
                f"{ref},operations,{date.today()},IDR,{amount},{NOTE}\n")
        self.store.intake(parse_csv(text.encode()))

    def test_retries_and_approved_record(self):
        self.ingest("P-2")
        plugin = PluginStub(ProviderFailure("timeout", True), GOOD)
        output = run_request(self.store, "P-2", plugin)
        self.assertEqual(plugin.calls, 2)
        self.assertEqual(output["status"], "approved")
        self.assertIn(b"P-2,operations", export_register(self.store))
        self.assertIn(b"approved,procurement", export_operations(self.store))
        with self.assertRaises(ValueError):
            run_request(self.store, "P-2", plugin)
        self.assertEqual(len(self.store.register()), 1)

    def test_finance_review_disallows_ungrounded_correction(self):
        self.ingest("P-3", 4_000_000)
        proposal = dict(GOOD, quantity=4)
        output = run_request(self.store, "P-3", PluginStub(proposal))
        self.assertEqual(output["status"], "review")
        self.assertEqual(output["route"], "finance")
        self.assertIn("quantity_without_source", output["issue"])
        with self.assertRaises(ValueError):
            review_request(self.store, "P-3", output["revision"], "approve", proposal)
        self.assertFalse(self.store.register())
        with self.assertRaises(ValueError):
            review_request(self.store, "P-3", 0, "approve", GOOD)
        review_request(self.store, "P-3", output["revision"], "approve", GOOD)
        self.assertEqual(self.store.register()[0]["result"], GOOD)

    def test_error_alert_and_manual_recovery(self):
        for reply in ("{invalid", {"invalid": "shape"}, ProviderFailure("timeout", True)):
            reference = f"P-{len(self.store.requests()) + 1}"
            self.ingest(reference)
            plugin = PluginStub(reply, reply)
            output = run_request(self.store, reference, plugin)
            self.assertEqual(output["status"], "error")
            self.assertEqual(self.store.events()[0]["kind"], "alert")
            self.assertEqual(plugin.calls, 2 if isinstance(reply, ProviderFailure) else 1)
            review_request(self.store, reference, output["revision"], "reject", {})
        self.assertFalse(self.store.register())

    def test_catalog_reconciles_wrong_model_category(self):
        self.ingest("P-4")
        output = run_request(self.store, "P-4", PluginStub(dict(GOOD, category="facilities")))
        self.assertEqual(output["status"], "approved")
        self.assertEqual(output["result"]["category"], "it")
        self.assertIn("resolved by item catalog", self.store.events()[0]["message"])

    def test_model_url_rejects_nonlocal_targets(self):
        for url in ("https://127.0.0.1:8082", "http://example.com", "http://user@localhost",
                    "http://127.0.0.1:8082/path"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                LlamaProvider(url)
