"""Create a run.json skeleton for a new audit, optionally embedding collected evidence.

  python3 new_run.py /absolute/path/run.json --url https://example.com/ \\
      --sample https://example.com/ --sample https://example.com/services \\
      --business-type "Services / agency" --market "UK" --language en \\
      --sampling-rationale "Homepage plus the main service template." \\
      --evidence /absolute/path/evidence/fetch-evidence.json

Every criterion and detailed review topic starts as unknown, with a placeholder
that run_contract.py reports as a warning until a reviewer replaces it. The
skeleton is validated before it is written; an existing file is never replaced.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evidence import strict_json  # noqa: E402
from review_topics import TOPICS  # noqa: E402
from run_contract import PLACEHOLDER, audit_run  # noqa: E402
from safe_io import write_new  # noqa: E402
from score import load_rubric  # noqa: E402
from version import RUBRIC_VERSION, RUN_SCHEMA_VERSION  # noqa: E402


def skeleton(*, url, sample, business_type, market, language, sampling_rationale, date, evidence=()):
    rubric, _ = load_rubric(RUBRIC_VERSION)
    criteria = {category: [{"id": rule["id"], "status": "unknown", "evidence_ids": [],
                            "rationale": f"{PLACEHOLDER} Not yet assessed against the anchor: {rule['anchor']}"}
                           for rule in profile["criteria"]]
                for category, profile in rubric["categories"].items()}
    review = [{"category": category, "topic": topic, "status": "unknown", "affected_urls": list(sample),
               "evidence_ids": [], "summary": f"{PLACEHOLDER} {label}: not yet reviewed."}
              for category, topics in TOPICS.items() for topic, label in topics.items()]
    return {
        "schema_version": RUN_SCHEMA_VERSION,
        "metadata": {"url": url, "date": date, "business_type": business_type, "market": market,
                     "language": language, "sample": list(sample), "sampling_rationale": sampling_rationale},
        "assessment": {"rubric_version": RUBRIC_VERSION, "evidence": list(evidence), "criteria": criteria},
        "summary": f"{PLACEHOLDER} Audit in progress; no conclusions have been recorded yet.",
        "limitations": [f"{PLACEHOLDER} Record the actual scope, collection and review limitations.",
                        "AI visibility not measured."],
        "findings": [],
        "review": review,
    }


def merge_evidence(paths):
    records, sources = [], {}
    for path in paths:
        loaded = strict_json(Path(path).read_text(encoding="utf-8"))
        if not isinstance(loaded, list):
            raise ValueError(f"{path} must contain a JSON list of evidence records")
        for item in loaded:
            identifier = item.get("id") if isinstance(item, dict) else None
            # Malformed records are reported by the full validation that follows.
            if isinstance(identifier, str) and identifier in sources:
                raise ValueError(f"Evidence ID {identifier!r} appears in both {sources[identifier]} and {path}; "
                                 "collect into separate prefixes or rename one")
            sources[identifier] = path
            records.append(item)
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("output", type=Path)
    parser.add_argument("--url", required=True, help="Audited site origin")
    parser.add_argument("--sample", action="append", default=[], help="Sample page URL (repeatable, 1-50)")
    parser.add_argument("--sample-file", type=Path, help="One sample URL per line; # comments are ignored")
    parser.add_argument("--business-type", required=True)
    parser.add_argument("--market", required=True)
    parser.add_argument("--language", required=True)
    parser.add_argument("--sampling-rationale", required=True)
    parser.add_argument("--date", default=datetime.now(timezone.utc).date().isoformat(), help="Audit date, YYYY-MM-DD")
    parser.add_argument("--evidence", action="append", default=[], type=Path,
                        help="Evidence records from collect.py or evidence.py --record-id (repeatable)")
    args = parser.parse_args()
    try:
        sample = list(args.sample)
        if args.sample_file:
            sample += [line.strip() for line in args.sample_file.read_text(encoding="utf-8").splitlines()
                       if line.strip() and not line.lstrip().startswith("#")]
        run = skeleton(url=args.url, sample=sample, business_type=args.business_type, market=args.market,
                       language=args.language, sampling_rationale=args.sampling_rationale, date=args.date,
                       evidence=merge_evidence(args.evidence))
        _, warnings = audit_run(run)
        captured = {record["source"] for record in run["assessment"]["evidence"] if record["status"] == "success"}
        warnings += [f"No successful capture yet for sample URL {url}" for url in sample if url not in captured]
        write_new(args.output, (json.dumps(run, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        print(json.dumps({"created": str(args.output), "schema_version": RUN_SCHEMA_VERSION,
                          "evidence_records": len(run["assessment"]["evidence"]), "warnings": warnings}, indent=2))
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Could not create run: {exc}\n")


if __name__ == "__main__":
    main()
