"""Calculate editorial readiness from JSON.

Input maps each category to a nonempty list of criteria:
{"citability": [{"id": "direct_answers", "status": "assessed", "value": 75,
"evidence_ids": ["page-1"]}], ...}
Statuses: assessed, unknown, not_applicable. Record anchors in the run manifest.
Unknown or missing categories suppress the overall score. N/A is excluded.
"""
import json
import math
import sys

WEIGHTS = {"citability": .25, "authority": .30, "content": .20, "technical": .15, "schema": .10}


def calculate(data):
    if set(data) - set(WEIGHTS):
        raise ValueError("Unknown category")
    results = {}
    for category, weight in WEIGHTS.items():
        criteria = data.get(category, [])
        values, unknown, ids = [], 0, set()
        for item in criteria:
            if not item.get("id") or item["id"] in ids:
                raise ValueError("Criterion IDs must be unique within a category")
            ids.add(item["id"])
            status = item["status"]
            if status == "not_applicable":
                if not item.get("reason"):
                    raise ValueError("N/A needs a reason")
                continue
            if status == "unknown":
                unknown += 1
                continue
            if status != "assessed":
                raise ValueError("Invalid criterion status")
            value = item.get("value")
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value <= 100:
                raise ValueError("Criterion value must be finite and between 0 and 100")
            if not item.get("evidence_ids"):
                raise ValueError("Assessed criteria require evidence IDs")
            values.append(value)
        applicable = len(values) + unknown
        score = sum(values) / len(values) if values and not unknown else None
        results[category] = {"score": score, "weight": weight, "assessed": len(values),
                             "applicable": applicable, "coverage": len(values) / applicable if applicable else None}
    overall = sum(row["score"] * row["weight"] for row in results.values()) if all(row["score"] is not None for row in results.values()) else None
    return {"rubric_version": "1.1.0", "categories": results,
            "overall": round(overall, 2) if overall is not None else None}


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as source:
        print(json.dumps(calculate(json.load(source)), indent=2))
