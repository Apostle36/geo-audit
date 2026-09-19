"""Validated audit run model. No fetching or truth verification is performed."""
import argparse
from datetime import date
import json
from pathlib import Path
from urllib.parse import urlsplit

from evidence import strict_json, validate_registry, resolve_ids
from score import calculate, nonempty, WEIGHTS
from review_topics import TOPICS


def fields(value, required, label):
    if not isinstance(value, dict) or set(value) != set(required):
        raise ValueError(f"{label} requires exactly {sorted(required)}")


def web_url(value):
    nonempty(value, "URL")
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or any(c.isspace() for c in value)
                or any(c in value for c in '<>"\\') or parsed.port == 0):
            raise ValueError()
    except ValueError:
        raise ValueError(f"Invalid HTTP(S) URL: {value!r}") from None
    return value


def validate_run(run):
    version = run.get('schema_version') if isinstance(run, dict) else None
    required = {"schema_version", "metadata", "assessment", "summary", "limitations", "findings"}
    if version == '1.3.0':
        required.add('review')
    fields(run, required, "Run")
    if version not in {"1.2.0", "1.3.0"}:
        raise ValueError("Unsupported schema_version")
    meta = run["metadata"]
    fields(meta, {"url", "date", "business_type", "market", "language", "sample", "sampling_rationale"}, "Metadata")
    web_url(meta["url"])
    for key in ("business_type", "market", "language", "sampling_rationale", "date"):
        nonempty(meta[key], key)
    try:
        if date.fromisoformat(meta["date"]).isoformat() != meta["date"]:
            raise ValueError()
    except ValueError:
        raise ValueError("date must be YYYY-MM-DD") from None
    if not isinstance(meta["sample"], list) or not 1 <= len(meta["sample"]) <= 50:
        raise ValueError("sample requires 1–50 unique page URLs")
    for url in meta["sample"]:
        web_url(url)
    if len(set(meta["sample"])) != len(meta["sample"]):
        raise ValueError("Duplicate sample URL")
    nonempty(run["summary"], "summary")
    if not isinstance(run["limitations"], list) or not run["limitations"]:
        raise ValueError("limitations must be a nonempty list")
    for item in run["limitations"]:
        nonempty(item, "limitation")
    scores = calculate(run["assessment"])
    registry = validate_registry(run["assessment"]["evidence"])
    for criterion in scores["criteria"]:
        if criterion["status"] != "unknown":
            sources = {registry[key]["source"] for key in criterion["evidence_ids"]}
            if not set(meta["sample"]).issubset(sources):
                raise ValueError(f"{criterion['id']} lacks evidence for every sample page; mark it unknown")
    if not isinstance(run["findings"], list):
        raise ValueError("findings must be a list")
    seen = set()
    for finding in run["findings"]:
        fields(finding, {"id", "category", "kind", "status", "affected_urls", "evidence_ids",
                         "observed", "claim", "consequence", "fix", "acceptance", "severity", "confidence_reason"}, "Finding")
        for key in ("id", "category", "kind", "status", "observed", "claim", "consequence", "fix", "acceptance", "severity", "confidence_reason"):
            nonempty(finding[key], f"finding {key}")
        if finding["id"] in seen:
            raise ValueError("Duplicate finding ID")
        seen.add(finding["id"])
        if finding["category"] not in WEIGHTS:
            raise ValueError("Unknown finding category")
        if finding["kind"] not in {"observation", "hypothesis", "recommendation", "unknown"}:
            raise ValueError("Invalid finding kind")
        if finding["status"] not in {"present", "absent", "unknown", "not_applicable"}:
            raise ValueError("Invalid finding status")
        if (finding["kind"] == "unknown") != (finding["status"] == "unknown"):
            raise ValueError("Unknown findings must have both kind and status unknown")
        if finding["severity"] not in {"critical", "high", "medium", "low", "informational"}:
            raise ValueError("Invalid finding severity")
        if not isinstance(finding["affected_urls"], list) or not finding["affected_urls"]:
            raise ValueError("affected_urls must be a nonempty list")
        for url in finding["affected_urls"]:
            web_url(url)
            if url not in meta["sample"]:
                raise ValueError("Affected URL is outside the declared sample")
        resolve_ids(finding["evidence_ids"], registry, require_success=finding["kind"] != "unknown")
    if version == '1.3.0':
        validate_review(run['review'], meta['sample'], registry)
    return scores


def validate_review(review, sample, registry):
    if not isinstance(review, list):
        raise ValueError('review must be a list')
    seen = set()
    for item in review:
        fields(item, {'category', 'topic', 'status', 'summary', 'affected_urls', 'evidence_ids'}, 'Review item')
        for key in ('category', 'topic', 'status', 'summary'):
            nonempty(item[key], f'review {key}')
        pair = (item['category'], item['topic'])
        if item['topic'] not in TOPICS.get(item['category'], {}) or pair in seen:
            raise ValueError('Unknown or duplicate review topic')
        seen.add(pair)
        if item['status'] not in {'assessed', 'unknown', 'not_applicable'}:
            raise ValueError('Invalid review status')
        urls = item['affected_urls']
        if not isinstance(urls, list) or not urls or any(not isinstance(u, str) or u not in sample for u in urls):
            raise ValueError('Review affected_urls must belong to the sample')
        if len(set(urls)) != len(urls):
            raise ValueError('Duplicate review URL')
        if item['status'] == 'unknown' and item['evidence_ids'] == []:
            continue
        records = resolve_ids(item['evidence_ids'], registry, require_success=item['status'] != 'unknown')
        if item['status'] != 'unknown' and not set(urls).issubset({r['source'] for r in records}):
            raise ValueError('Assessed review needs successful evidence for each affected URL')


def comparable(current, previous):
    a, b = validate_run(current), validate_run(previous)
    keys = ("url", "business_type", "market", "language", "sample", "sampling_rationale")
    differences = [key for key in keys if current["metadata"][key] != previous["metadata"][key]]
    for key in ("rubric_version", "rubric_sha256"):
        if a[key] != b[key]:
            differences.append(key)
    # Applicability changes alter denominators even if scope is unchanged.
    def applicability(scores):
        return [(c["category"], c["id"], c["status"] == "not_applicable", c.get("reason") if c["status"] == "not_applicable" else None)
                for c in scores["criteria"]]
    if applicability(a) != applicability(b):
        differences.append("applicability")
    return {"comparable": not differences, "differences": differences,
            "limitation": "Matching scope permits editorial comparison, not causal attribution or measured AI visibility."}


def report_data(run, *, technical=False):
    if not technical:
        from client_report import client_report_data
        return client_report_data(run, validate_run(run))
    scores = validate_run(run)
    meta = run["metadata"]
    sections = []
    def section(title, text):
        sections.append({"heading": title, "content": text, "format": "plain"})
    section("Scope and limitations", "\n".join([
        "AI visibility not measured. This is an editorial sample readiness assessment.",
        f"Rubric: {scores['rubric_version']} / SHA-256: {scores['rubric_sha256']}",
        f"Market: {meta['market']} | Language: {meta['language']}",
        f"Sampling: {meta['sampling_rationale']}", *meta["sample"], *run["limitations"]]))
    section("Assessment coverage", "\n".join(
        f"{category}: score {row['score'] if row['score'] is not None else 'Not assessed'}; "
        f"assessed {row['assessed']}/{row['expected']}; unknown {row['unknown']}; "
        f"not applicable {row['not_applicable']}; missing {', '.join(row['missing']) or 'none'}"
        for category, row in scores["categories"].items()))
    section("Criterion observations", "\n\n".join(
        f"{item['category']}.{item['id']} — {item['status']}\n"
        f"Value: {item.get('value', 'Not assessed')}\n"
        f"Reason: {item.get('rationale', item.get('reason', ''))}\n"
        f"N/A reason: {item.get('reason', 'none')}\n"
        f"Evidence: {', '.join(item.get('evidence_ids', [])) or 'none'}"
        for item in scores["criteria"]))
    for item in run["findings"]:
        section(f"Finding {item['id']}", "\n".join(
            f"{key.replace('_', ' ').capitalize()}: {', '.join(value) if isinstance(value, list) else value}"
            for key, value in item.items()))
    for item in run.get('review', []):
        section(f"Detailed review {item['category']}.{item['topic']}", '\n'.join(
            f"{key}: {', '.join(value) if isinstance(value, list) else value}" for key, value in item.items()))
    for item in run["assessment"]["evidence"]:
        section(f"Evidence {item['id']}", "\n".join([
            f"Source: {item['source']}", f"Collected: {item['collected_at']}",
            f"Method: {item['method']} | Status: {item['status']}", f"SHA-256: {item['sha256']}",
            "Captured content (untrusted source text):", item["content"]]))
    return {"url": meta["url"], "date": meta["date"], "business_type": meta["business_type"],
            "pages_analyzed": str(len(meta["sample"])), "overall_score": scores["overall"],
            "score_label": "Editorial readiness" if scores["overall"] is not None else "Not assessed",
            "executive_summary": run["summary"], "summary_format": "plain", "sections": sections}


def main():
    parser = argparse.ArgumentParser(description="Validate a structured audit run; incomplete coverage stays explicit.")
    parser.add_argument("run", type=Path)
    parser.add_argument("--compare", type=Path)
    args = parser.parse_args()
    try:
        run = strict_json(args.run.read_text(encoding="utf-8"))
        result = {"valid": True, "scores": validate_run(run)}
        if args.compare:
            result["comparison"] = comparable(run, strict_json(args.compare.read_text(encoding="utf-8")))
            if not result["comparison"]["comparable"]:
                print(json.dumps(result, indent=2, allow_nan=False))
                return 3
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Invalid run: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
