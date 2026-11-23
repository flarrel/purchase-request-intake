"""Normalize the CSV input and keep spreadsheet exports safe to open."""

import csv
import hashlib
import io
import json
import re
from datetime import date, datetime
from decimal import Decimal

HEADERS = ("reference", "department", "date", "currency", "amount", "notes")
MAX_BYTES = 256_000
MAX_ROWS = 500
DEPARTMENTS = {"operations", "facilities", "finance"}
CATEGORIES = ("office", "it", "facilities", "services")
EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
PHONE = re.compile(r"(?<!\w)(?:\+62|08)[\d -]{7,15}\d(?!\w)")


def redact(text):
    return PHONE.sub("[phone]", EMAIL.sub("[email]", text))


def clean(cell):
    return " ".join(cell.split())


def normalize_date(value):
    for pattern in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            continue
    raise ValueError("date must be YYYY-MM-DD or DD/MM/YYYY")


def normalize_amount(value, currency):
    value = re.sub(r"^(?:rp\.?|idr)\s*", "", value, flags=re.I) if currency == "IDR" else value
    if currency == "IDR" and re.fullmatch(r"[0-9]{1,3}(?:\.[0-9]{3})+(?:,00)?", value):
        value = value.replace(".", "")
    value = value.replace(",00", "") if currency == "IDR" and value.endswith(",00") else value
    if not re.fullmatch(r"[0-9]{1,9}(?:\.[0-9]{1,2})?", value):
        raise ValueError("amount must be a positive number in the currency's supported format")
    cents = int(Decimal(value) * 100)
    if cents < 1 or (currency == "IDR" and cents % 100):
        raise ValueError("amount must be positive and IDR amounts must be whole rupiah")
    return cents


def parse_csv(raw):
    if len(raw) > MAX_BYTES:
        raise ValueError("CSV exceeds 256 kB")
    reader = csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
    try:
        header = [clean(cell).lower().replace(" ", "_") for cell in next(reader, [])]
        if set(header) != set(HEADERS) or len(header) != len(HEADERS):
            raise ValueError("CSV columns must be " + ", ".join(HEADERS))
        entries = []
        for number, cells in enumerate(reader, 2):
            if number > MAX_ROWS + 1:
                raise ValueError("CSV exceeds 500 rows")
            if not any(cells):
                continue
            try:
                if len(cells) != len(header):
                    raise ValueError("wrong number of cells")
                row = dict(zip(header, map(clean, cells)))
                row["reference"] = row["reference"].upper()
                row["department"] = row["department"].lower()
                row["currency"] = row["currency"].upper()
                if not re.fullmatch(r"[A-Z0-9-]{1,32}", row["reference"]):
                    raise ValueError("missing or invalid reference")
                if row["department"] not in DEPARTMENTS:
                    raise ValueError("unknown department")
                if row["currency"] not in {"IDR", "USD"}:
                    raise ValueError("unsupported currency")
                row["date"] = normalize_date(row["date"])
                row["amount_minor"] = normalize_amount(row.pop("amount"), row["currency"])
                if not 1 <= len(row["notes"]) <= 1500:
                    raise ValueError("notes must contain 1–1500 characters")
                if any(ord(character) < 32 for character in row["notes"]):
                    raise ValueError("notes contain a control character")
                row["notes"] = redact(row["notes"])
                entries.append((number, row, None))
            except ValueError as error:
                entries.append((number, None, str(error)))
        return entries
    except csv.Error as error:
        raise ValueError("invalid CSV structure") from error


def fingerprint(row):
    return hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()


def safe_cell(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def csv_bytes(headers, rows):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows([safe_cell(value) for value in row] for row in rows)
    return output.getvalue().encode("utf-8")


def age_days(iso, today=None):
    return ((today or date.today()) - date.fromisoformat(iso)).days
