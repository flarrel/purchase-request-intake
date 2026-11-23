"""Score raw provider outputs and the automatic-write guard on synthetic notes."""

import argparse
import hashlib
import json
import statistics
import time
from pathlib import Path

from intake.data import CATEGORIES
from intake.skill import LlamaProvider, ProviderFailure, RulesProvider, parse_note, reconcile_category, routing_issues, validate

from .samples import make_split

METRIC_FIELDS = ("vendor", "item", "quantity")


def same_value(actual, expected):
    if isinstance(expected, str):
        return isinstance(actual, str) and actual == expected
    return type(actual) is int and actual == expected


def f1_for(category, rows):
    tp = sum(row["category"] == row["gold_category"] == category for row in rows)
    predicted = sum(row["category"] == category for row in rows)
    positives = sum(row["gold_category"] == category for row in rows)
    return 2 * tp / (predicted + positives) if predicted + positives else 0


def measure(name, provider, revision, cases, repeats=0):
    rows = []
    for case in cases:
        start = time.monotonic()
        got, failure = predict(provider, case["note"], revision)
        elapsed = time.monotonic() - start
        gold = case["gold"]
        field_hits = {field: same_value(got.get(field), gold[field]) for field in METRIC_FIELDS}
        issues = validate(got, case["note"]) + routing_issues(got, case["note"]) if got else [failure]
        summary = got.get("summary")
        grounded = isinstance(summary, str) and gold["item"] in summary and summary in case["note"]
        adjusted = reconcile_category(got) if got else {}
        adjusted_issues = validate(adjusted, case["note"]) + routing_issues(adjusted, case["note"]) if got else [failure]
        accurate_fields_and_summary = all(field_hits.values()) and grounded
        accurate = accurate_fields_and_summary and got.get("category") == gold["category"]
        adjusted_accurate = accurate_fields_and_summary and adjusted.get("category") == gold["category"]
        rows.append({
            "id": case["id"], "category": got.get("category"), "gold_category": gold["category"],
            "fields_correct": field_hits, "summary_grounded": grounded, "issues": issues,
            "workflow_category": adjusted.get("category"), "workflow_issues": adjusted_issues,
            "workflow_incorrect_auto_write": not adjusted_issues and not adjusted_accurate,
            "auto_write": not issues, "incorrect_auto_write": not issues and not accurate,
            "output": got, "latency_s": round(elapsed, 3),
        })
    agreement = []
    for case, row in zip(cases[:repeats], rows):
        output, failure = predict(provider, case["note"], revision)
        agreement.append(not failure and output == row["output"])
    count = len(rows)
    field_hits = sum(sum(row["fields_correct"].values()) for row in rows)
    summary_missing = sum(not row["output"].get("summary") for row in rows)
    unsupported = sum(bool(row["output"].get("summary")) and not row["summary_grounded"] for row in rows)
    counts = {
        "cases": count, "field_matches": field_hits, "field_total": count * len(METRIC_FIELDS),
        "field_exact": round(field_hits / (count * len(METRIC_FIELDS)), 4),
        "macro_f1": round(statistics.mean(f1_for(category, rows) for category in CATEGORIES), 4),
        "workflow_macro_f1": round(statistics.mean(f1_for(category, [
            {**row, "category": row["workflow_category"]} for row in rows
        ]) for category in CATEGORIES), 4),
        "workflow_review_or_error": sum(bool(row["workflow_issues"]) for row in rows),
        "workflow_incorrect_auto_writes": sum(row["workflow_incorrect_auto_write"] for row in rows),
        "grounded_summaries": count - summary_missing - unsupported,
        "unsupported_summaries": unsupported, "missing_summaries": summary_missing,
        "review_or_error": sum(bool(row["issues"]) for row in rows),
        "incorrect_auto_writes": sum(row["incorrect_auto_write"] for row in rows),
        "median_latency_s": round(statistics.median(row["latency_s"] for row in rows), 3),
        "repeat_matches": sum(agreement), "repeat_cases": len(agreement),
    }
    return {"method": name, "metrics": counts, "cases": rows}


def predict(provider, note, revision):
    try:
        return parse_note(provider, note, revision), None
    except ProviderFailure as error:
        return {}, str(error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("development", "holdout"), required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8082")
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--revision", choices=("v1", "v2", "v3"), nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    all_cases = make_split(args.split)
    chosen = [case for case in all_cases if case["template"] == 1] if args.split == "development" else all_cases
    digest = hashlib.sha256(json.dumps(all_cases, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    model = LlamaProvider(args.url, api_key=args.key_file.read_text().strip() if args.key_file else None)
    runs = [measure("rules", RulesProvider(), args.revision[0], chosen)]
    for version in args.revision:
        runs.append(measure(version, model, version, chosen, repeats=4 if args.split == "development" else 0))
        print(version, runs[-1]["metrics"], flush=True)
    payload = {"split": args.split, "model": args.model_id, "fixture_sha256": digest,
               "split_size": len(all_cases), "evaluated_ids": [case["id"] for case in chosen], "runs": runs}
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
