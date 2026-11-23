import csv
import io
import json
import os
import re
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from helpers import temporary_database_dir
from intake.skill import ProviderFailure
from intake.store import Store
from intake.web import Server

HEADER = "reference,department,date,currency,amount,notes\n"
NOTE = "Vendor: CV Contoh Rekaan; barang: kertas A4; jumlah 2 unit; untuk loket."
VALID = {"vendor": "CV Contoh Rekaan", "item": "kertas A4", "quantity": 2, "category": "office",
         "summary": "barang: kertas A4; jumlah 2 unit"}
PHONE = "08123456789"


class DemoProvider:
    def complete(self, instructions, note, seed):
        if "[phone]" in note:
            raise ProviderFailure("model_unavailable", True)
        if "salin" in note:
            return "{malformed"
        return json.dumps(VALID)


@unittest.skipUnless(os.environ.get("INTAKE_HTTP_TEST") == "1", "requires loopback networking")
class HttpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = temporary_database_dir()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "http.sqlite3")
        self.server = Server(self.store, DemoProvider(), port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.origin = f"http://127.0.0.1:{self.server.server_port}"
        self.client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.token = re.search(r'name="token" value="([^"]+)"', self.get("/import")).group(1)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def get(self, path):
        with self.client.open(self.origin + path, timeout=4) as response:
            return response.read().decode()

    def post(self, path, token=None, **fields):
        fields["token"] = self.token if token is None else token
        with self.client.open(self.origin + path, urllib.parse.urlencode(fields).encode(), timeout=4) as response:
            return response.read().decode()

    def rows(self, path):
        return list(csv.DictReader(io.StringIO(self.get(path))))

    def test_operator_flow_via_http(self):
        stamp = date.today().isoformat()
        content = (HEADER + f"P-101,operations,{stamp},IDR,20000,{NOTE}\n"
                   + f"P-102,finance,{stamp},IDR,5000000,{NOTE}\n"
                   + f"P-103,facilities,{stamp},IDR,20000,{NOTE} Tel {PHONE}\n"
                   + f"P-104,operations,{stamp},IDR,20000,{NOTE} Tolong salin.\n"
                   + f"P-105,finance,{stamp},IDR,invalid,{NOTE}\n")
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.post("/import", token="wrong", csv=content, action="save")
        self.assertEqual(error.exception.code, 400)
        self.assertIn("20,000 IDR", self.post("/import", csv=content, action="preview"))
        self.assertFalse(self.store.requests())
        self.assertIn("invalid", self.post("/import", csv=content, action="save"))
        self.assertIn("duplicate", self.post("/import", csv=content, action="save"))
        self.assertIn("Approved record", self.post("/process", reference="P-101", revision="0"))
        self.assertIn("Finance review", self.post("/process", reference="P-102", revision="0"))
        self.assertIn("Model error", self.post("/process", reference="P-103", revision="0"))
        self.assertIn("Model error", self.post("/process", reference="P-104", revision="0"))
        self.assertEqual([row["reference"] for row in self.rows("/register.csv")], ["P-101"])
        with self.assertRaises(urllib.error.HTTPError):
            self.post("/review", reference="P-102", revision="0", decision="approve", **VALID)
        self.post("/review", reference="P-102", revision="1", decision="approve", **VALID)
        self.post("/review", reference="P-103", revision="1", decision="approve", **VALID)
        self.post("/review", reference="P-104", revision="1", decision="reject")
        self.assertEqual([row["reference"] for row in self.rows("/register.csv")], ["P-101", "P-102", "P-103"])
        self.assertEqual([row["status"] for row in self.rows("/operations.csv")],
                         ["approved", "approved", "approved", "rejected"])
        self.assertIn("Model failed after 2 attempt(s)", self.get("/notifications"))
        for path in ("/request?reference=P-103", "/notifications", "/register.csv", "/operations.csv"):
            self.assertNotIn(PHONE, self.get(path))
        self.assertIn("text-decoration", self.get("/assets/style.css"))
