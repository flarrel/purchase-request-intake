"""Workflow decisions shared by the operator UI and command-line demo."""

import re

from .data import age_days, csv_bytes
from .skill import QUANTITY, ProviderFailure, parse_note, validate

REGISTER_FIELDS = ("reference", "department", "date", "currency", "amount", "route", "vendor",
                   "item", "quantity", "category", "summary", "approved_at")
LIMIT_MINOR = {"IDR": 200_000_000, "USD": 15_000}
SOURCE_FLAGS = re.compile(r"\b(?:belum pasti|belum jelas|tidak diketahui|vendor menyusul|atau|batal)\b", re.I)


def run_request(store, reference, provider, revision="v2"):
    request = store.get(reference)
    if request["status"] not in {"queued", "error"}:
        raise ValueError("Only queued requests or model errors can be processed")
    source = request["source"]
    note = source["notes"]
    route = "finance" if source["amount_minor"] >= LIMIT_MINOR[source["currency"]] else "procurement"
    attempts = 0
    for attempt in range(2):
        attempts = attempt + 1
        try:
            result = parse_note(provider, note, revision)
            break
        except ProviderFailure as exc:
            if exc.retryable and attempt == 0:
                continue
            store.transition(request, "error", None, route, str(exc), "alert",
                             f"Model failed after {attempts} attempt(s) [{exc}]. Retry or open manual review.")
            return store.get(reference)
    issues = validate(result, note)
    if route == "finance":
        issues.append("finance_threshold")
    if not 0 <= age_days(source["date"]) <= 90:
        issues.append("date_outside_90_days")
    if SOURCE_FLAGS.search(note) or len(list(QUANTITY.finditer(note))) > 1:
        issues.append("ambiguous_source")
    if issues:
        store.transition(request, "review", result, route, ", ".join(issues),
                         "review_required", f"{route.title()} review requested")
    else:
        store.transition(request, "approved", result, route, None, "approved",
                         "Validated request written to the register")
    return store.get(reference)


def review_request(store, reference, revision, decision, changes):
    request = store.get(reference)
    if request["status"] not in {"review", "error"}:
        raise ValueError("This request is outside the review queue")
    if revision != request["revision"]:
        raise ValueError("Request changed. Reload before submitting a decision.")
    route = request["route"]
    if decision == "reject":
        store.transition(request, "rejected", None, route, None, "rejected",
                         f"{route.title()} reviewer rejected the request")
        return
    if decision != "approve":
        raise ValueError("Choose approve or reject")
    issues = validate(changes, request["source"]["notes"])
    if issues:
        raise ValueError("Review corrections need source support: " + ", ".join(issues))
    store.transition(request, "approved", changes, route, None, "approved",
                     f"{route.title()} reviewer approved and wrote the record")


def export_register(store):
    rows = []
    for request in store.register():
        source = request["source"]
        minor = source["amount_minor"]
        amount = str(minor // 100) if source["currency"] == "IDR" else f"{minor // 100}.{minor % 100:02d}"
        row = {**source, **request["result"], "amount": amount,
               "route": request["route"], "approved_at": request["approved_at"]}
        rows.append(tuple(row[field] for field in REGISTER_FIELDS))
    return csv_bytes(REGISTER_FIELDS, rows)


def export_operations(store):
    return csv_bytes(("reference", "department", "status", "route", "issue", "revision"),
                     [(row["reference"], row["source"]["department"], row["status"],
                       row["route"], row["issue"], row["revision"]) for row in store.requests()])
