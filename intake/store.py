"""SQLite state for requests, operator actions, and notifications."""

import json
import sqlite3
from contextlib import contextmanager

from .data import fingerprint

SCHEMA = """
CREATE TABLE IF NOT EXISTS request (
    reference TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK(status IN ('queued','review','error','approved','rejected')),
    revision INTEGER NOT NULL DEFAULT 0,
    result TEXT,
    issue TEXT,
    route TEXT
);
CREATE TABLE IF NOT EXISTS event (
    id INTEGER PRIMARY KEY,
    reference TEXT NOT NULL REFERENCES request(reference),
    kind TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS register (
    reference TEXT PRIMARY KEY REFERENCES request(reference),
    approved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class Conflict(ValueError):
    pass


class Store:
    def __init__(self, path):
        self.path = path
        with self.connection() as connection:
            connection.executescript(SCHEMA)
            connection.execute("PRAGMA journal_mode=WAL")

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.path, timeout=8)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def intake(self, entries):
        report = []
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for line, row, error in entries:
                if error:
                    report.append((line, "", "invalid", error))
                    continue
                reference = row["reference"]
                digest = fingerprint(row)
                existing = connection.execute(
                    "SELECT fingerprint FROM request WHERE reference = ?", (reference,)
                ).fetchone()
                if existing:
                    repeat = existing["fingerprint"] == digest
                    report.append((line, reference, "duplicate" if repeat else "conflict",
                                   "Same cleaned record" if repeat else "Reference already has different data"))
                    continue
                connection.execute(
                    "INSERT INTO request(reference,fingerprint,source) VALUES (?,?,?)",
                    (reference, digest, json.dumps(row, ensure_ascii=False)),
                )
                self._event(connection, reference, "imported", "Request received")
                report.append((line, reference, "queued", "Request received"))
        return report

    def get(self, reference):
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM request WHERE reference=?", (reference,)).fetchone()
        if row is None:
            raise KeyError(reference)
        return self._decode(row)

    @staticmethod
    def _decode(row):
        request = dict(row)
        request["source"] = json.loads(request["source"])
        request["result"] = json.loads(request["result"]) if request["result"] else None
        return request

    def requests(self):
        with self.connection() as connection:
            return [self._decode(row) for row in connection.execute("SELECT * FROM request ORDER BY reference")]

    def events(self, limit=30):
        with self.connection() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM event ORDER BY id DESC LIMIT ?", (limit,)
            )]

    def register(self):
        with self.connection() as connection:
            return [self._decode(row) for row in connection.execute(
                """SELECT request.*, register.approved_at FROM register
                   JOIN request USING(reference) ORDER BY request.reference"""
            )]

    @staticmethod
    def _event(connection, reference, kind, message):
        connection.execute(
            "INSERT INTO event(reference,kind,message) VALUES (?,?,?)", (reference, kind, message)
        )

    def transition(self, request, status, result, route, issue, event, message):
        reference = request["reference"]
        with self.connection() as connection:
            cursor = connection.execute(
                """UPDATE request SET status=?,result=?,route=?,issue=?,revision=revision+1
                   WHERE reference=? AND status=? AND revision=?""",
                (status, json.dumps(result, ensure_ascii=False) if result else None,
                 route, issue, reference, request["status"], request["revision"]),
            )
            if cursor.rowcount != 1:
                raise Conflict("Request changed. Reload before trying again.")
            if status == "approved":
                connection.execute("INSERT INTO register(reference) VALUES (?)", (reference,))
            self._event(connection, reference, event, message)
