"""Compute editorial sample readiness from a validated assessment JSON envelope.

Required fields: rubric_version, evidence (captured records), criteria (category
to criterion list). See docs/RUN-FORMAT.md. Legacy unverified scores are rejected.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evidence import strict_json, validate_registry, resolve_ids

WEIGHTS = {"citability": .25, "authority": .30, "content": .20, "technical": .15, "schema": .10}
RUBRIC_SHA256 = "21ba14c323a0ff832a4db0fc7df2ef79641d8c874c2d486f3a298051982fb400"


def load_rubric(version):
    if version != "1.2.0":
        raise ValueError("Unsupported rubric_version; use 1.2.0. Legacy 1.1.0 scores are not verified.")
    raw = (Path(__file__).resolve().parent / "rubrics" / "1.2.0.json").read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != RUBRIC_SHA256:
        raise ValueError("Rubric 1.2.0 was modified; restore it or introduce a new supported version")
    return strict_json(raw.decode("utf-8")), digest


def nonempty(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be nonempty text")


def calculate(data):
    if not isinstance(data, dict) or set(data) != {"rubric_version", "evidence", "criteria"}:
        raise ValueError("Assessment requires rubric_version, evidence and criteria; see docs/RUN-FORMAT.md")
    rubric, digest = load_rubric(data["rubric_version"])
    registry = validate_registry(data["evidence"])
    submitted = data["criteria"]
    if not isinstance(submitted, dict) or set(submitted) - set(WEIGHTS):
        raise ValueError("criteria must map known categories to lists")
    results = {}
    observations = []
    for category, profile in rubric["categories"].items():
        rules = {rule["id"]: rule for rule in profile["criteria"]}
        items = submitted.get(category, [])
        if not isinstance(items, list):
            raise ValueError(f"{category} criteria must be a list")
        indexed = {}
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or item["id"] not in rules:
                raise ValueError(f"Unknown or malformed criterion in {category}")
            if item["id"] in indexed:
                raise ValueError(f"Duplicate criterion: {category}.{item['id']}")
            indexed[item["id"]] = item
        values, unknown, excluded, missing = [], 0, 0, []
        for identifier, rule in rules.items():
            item = indexed.get(identifier)
            if item is None:
                unknown += 1
                missing.append(identifier)
                observations.append({"category": category, "id": identifier, "status": "unknown", "reason": "Not submitted"})
                continue
            status = item.get("status")
            fields = {"id", "status", "rationale", "evidence_ids"}
            if status == "assessed":
                fields.add("value")
            elif status == "not_applicable":
                fields.add("reason")
            elif status != "unknown":
                raise ValueError(f"Invalid status for {identifier}")
            if set(item) != fields:
                raise ValueError(f"{identifier} requires exactly {sorted(fields)}")
            nonempty(item["rationale"], f"{identifier} rationale")
            if status == "unknown":
                if item["evidence_ids"] != []:
                    resolve_ids(item["evidence_ids"], registry, require_success=False)
                unknown += 1
            else:
                resolve_ids(item["evidence_ids"], registry)
                if status == "not_applicable":
                    if item["reason"] not in rule["na_reasons"]:
                        raise ValueError(f"Unsupported N/A reason for {identifier}")
                    excluded += 1
                else:
                    value = item["value"]
                    if type(value) not in (int, float) or value not in (0, 50, 100):
                        raise ValueError(f"{identifier} value must match an anchor: 0, 50 or 100")
                    values.append(value)
            observations.append({"category": category, **item})
        expected = len(rules)
        applicable = expected - excluded
        results[category] = {
            "score": sum(values) / len(values) if values and not unknown else None,
            "weight": profile["weight"], "expected": expected, "assessed": len(values),
            "unknown": unknown, "not_applicable": excluded, "missing": missing,
            "applicable": applicable,
            "coverage": len(values) / expected,
            "applicable_coverage": len(values) / applicable if applicable else None,
        }
    complete = all(row["score"] is not None for row in results.values())
    total = sum(row["score"] * row["weight"] for row in results.values()) if complete else None
    return {"rubric_version": rubric["version"], "rubric_sha256": digest,
            "interpretation": rubric["description"], "categories": results,
            "criteria": observations, "overall": round(total, 2) if total is not None else None,
            "coverage": sum(row["assessed"] for row in results.values()) / sum(row["expected"] for row in results.values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assessment", type=Path)
    args = parser.parse_args()
    try:
        result = calculate(strict_json(args.assessment.read_text(encoding="utf-8")))
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Invalid assessment: {exc}\n")


if __name__ == "__main__":
    main()
