import unittest
from pathlib import Path

from helpers import temporary_database_dir

from intake.data import csv_bytes, parse_csv
from intake.store import Conflict, Store

HEADER = b" Reference , Department , Date , Currency , Amount , Notes\n"
ROW = b'p-001,Operations,02/11/2026,IDR,"Rp 1.450.000,00",Kontak person@example.com dan 08123456789\n'


class IntakeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = temporary_database_dir()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "intake.sqlite3")

    def test_messy_csv_and_formula_safe_export(self):
        valid, invalid = parse_csv(HEADER + ROW + b"?,operations,02/11/2026,IDR,5,x\n")
        row = valid[1]
        self.assertEqual(row["reference"], "P-001")
        self.assertEqual(row["date"], "2026-11-02")
        self.assertEqual(row["amount_minor"], 145000000)
        self.assertEqual(row["notes"], "Kontak [email] dan [phone]")
        self.assertEqual(invalid[2], "missing or invalid reference")
        self.assertEqual(csv_bytes(("text",), [(" =2+2",)]), b"text\r\n' =2+2\r\n")

    def test_duplicate_conflict_and_approval_replay(self):
        entries = parse_csv(HEADER + ROW)
        self.assertEqual(self.store.intake(entries)[0][2], "queued")
        self.assertEqual(self.store.intake(entries)[0][2], "duplicate")
        self.assertEqual(self.store.intake(parse_csv(HEADER + ROW.replace(b"450", b"550")))[0][2], "conflict")
        source = self.store.get("P-001")
        self.store.transition(source, "approved", {"category": "office"}, "procurement", None,
                              "approved", "Saved")
        with self.assertRaises(Conflict):
            self.store.transition(source, "approved", {"category": "office"}, "procurement", None,
                                  "approved", "Saved")
        self.assertEqual(len(self.store.register()), 1)
        self.assertEqual([event["kind"] for event in self.store.events()], ["approved", "imported"])
