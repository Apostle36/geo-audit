"""Validated audit run model. No fetching or truth verification is performed."""
import argparse
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from urllib.parse import urlsplit

from capture_quality import conclusion_warnings
from evidence import strict_json, validate_registry, resolve_ids, extract, structured_data_markers, parse_timestamp
from score import calculate, nonempty, WEIGHTS
from review_topics import TOPICS
from version import RUN_SCHEMA_VERSION, SUPPORTED_RUN_SCHEMAS

# new_run.py marks every value a reviewer must replace with this text.
PLACEHOLDER = "[skeleton placeholder]"
# Captures much older than the audit date are probably reused from another run.
STALE_CAPTURE = timedelta(days=180)


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
    """Validate structure and provenance; return the computed scores."""
    return audit_run(run)[0]


def audit_run(run):
    """Validate a run and return (scores, warnings).

    Schema 1.4.0 rejects every provenance issue. Older schemas stay readable
    without modification, so the same issues are reported as warnings instead.
    """
    version = run.get('schema_version') if isinstance(run, dict) else None
    required = {"schema_version", "metadata", "assessment", "summary", "limitations", "findings"}
    if version in {'1.3.0', '1.4.0'}:
        required.add('review')
    fields(run, required, "Run")
    if version not in SUPPORTED_RUN_SCHEMAS:
        raise ValueError(f"Unsupported schema_version; new runs use {RUN_SCHEMA_VERSION}")
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
    if version != '1.2.0':
        validate_review(run['review'], meta['sample'], registry)
    issues = provenance_issues(run, registry, scores)
    if version == RUN_SCHEMA_VERSION and issues:
        raise ValueError("; ".join(issues))
    warnings = [f"Schema {version} accepts this, schema {RUN_SCHEMA_VERSION} rejects it: {issue}" for issue in issues]
    return scores, warnings + advisory_warnings(run, registry)


def provenance_issues(run, registry, scores):
    """Evidence-linkage problems that schema 1.4.0 rejects outright."""
    sample = run["metadata"]["sample"]
    issues = [f"Sample URL contains a fragment, which never reaches the server: {url}" for url in sample if "#" in url]
    for finding in run["findings"]:
        label = f"Finding {finding['id']}"
        if len(set(finding["affected_urls"])) != len(finding["affected_urls"]):
            issues.append(f"{label} lists an affected URL more than once")
        if finding["kind"] in {"unknown", "hypothesis"} and finding["severity"] in {"critical", "high"}:
            issues.append(f"{label} is a {finding['kind']} rated {finding['severity']}; "
                          "critical and high severity require a verified problem")
        if finding["kind"] != "unknown":
            captured = {registry[key]["source"] for key in finding["evidence_ids"]}
            missing = [url for url in finding["affected_urls"] if url not in captured]
            if missing:
                issues.append(f"{label} cites no capture of its affected page(s): {', '.join(missing)}")
    inventories = {}
    for criterion in scores["criteria"]:
        if criterion["status"] != "not_applicable" or criterion["reason"] != "no_structured_data_in_sample":
            continue
        for key in criterion["evidence_ids"]:
            record = registry[key]
            if record["source"] not in sample:
                continue
            if key not in inventories:
                inventories[key] = structured_data_markers(extract(record["content"]))
            if inventories[key]:
                issues.append(f"{criterion['id']} is marked no_structured_data_in_sample, but evidence {key} "
                              f"contains {', '.join(inventories[key])}")
    return issues


def advisory_warnings(run, registry):
    """Plausibility checks for a human reviewer; never a reason to reject a run."""
    meta, warnings = run["metadata"], []
    origin = site_host(meta["url"])
    for url in meta["sample"]:
        host = site_host(url)
        if host != origin and not host.endswith("." + origin):
            warnings.append(f"Sample URL is outside the audited site {origin}: {url}")
    audit_day = date.fromisoformat(meta["date"])
    now = datetime.now(timezone.utc)
    for key, record in registry.items():
        stamp = parse_timestamp(record["collected_at"])
        day = stamp.astimezone(timezone.utc).date()
        if stamp > now + timedelta(days=1):
            warnings.append(f"Evidence {key} has a collection time in the future: {record['collected_at']}")
        elif day > audit_day + timedelta(days=1):
            warnings.append(f"Evidence {key} was collected after the audit date {meta['date']}")
        elif day < audit_day - STALE_CAPTURE:
            warnings.append(f"Evidence {key} was collected more than {STALE_CAPTURE.days} days before the audit date")
    placeholders = sum(PLACEHOLDER in text for text in run_text(run))
    if placeholders:
        warnings.append(f"{placeholders} field(s) still contain the run skeleton placeholder; "
                        "replace them before delivery")
    # An error page, challenge or empty render is a successful capture, not useful content.
    return warnings + conclusion_warnings(run, registry)


def site_host(url):
    host = urlsplit(url).hostname or ""
    return host[4:] if host.startswith("www.") else host


def run_text(run):
    """Every reviewer-written text value in a run."""
    yield run["summary"]
    yield from run["limitations"]
    for finding in run["findings"]:
        yield from (value for value in finding.values() if isinstance(value, str))
    for item in run.get("review", []):
        yield item["summary"]
    for items in run["assessment"]["criteria"].values():
        for item in items:
            yield from (item.get(key, "") for key in ("rationale", "reason"))


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
    def scope(run, key):
        # The sample is a set of pages; listing the same pages in another order changes nothing.
        value = run["metadata"][key]
        return set(value) if key == "sample" else value
    differences = [key for key in keys if scope(current, key) != scope(previous, key)]
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


def report_data(run, *, technical=False, evidence_limit=None):
    """Report model. evidence_limit shortens each technical capture (used for PDF) with a visible note."""
    if not technical:
        from client_report import client_report_data
        return client_report_data(run, validate_run(run))
    scores, warnings = audit_run(run)
    meta = run["metadata"]
    sections = []
    def section(title, text):
        sections.append({"heading": title, "content": text, "format": "plain"})
    section("Scope and limitations", "\n".join([
        "AI visibility not measured. This is an editorial sample readiness assessment.",
        f"Rubric: {scores['rubric_version']} / SHA-256: {scores['rubric_sha256']}",
        f"Market: {meta['market']} | Language: {meta['language']}",
        f"Sampling: {meta['sampling_rationale']}", *meta["sample"], *run["limitations"]]))
    if warnings:
        section("Validation warnings", "\n".join(warnings))
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
        content = item["content"]
        if evidence_limit is not None and len(content) > evidence_limit:
            content = (content[:evidence_limit] + f"\n[Shortened for this export: first {evidence_limit:,} of "
                       f"{len(item['content']):,} characters. The complete capture and its SHA-256 are in run.json "
                       "and the technical HTML export.]")
        section(f"Evidence {item['id']}", "\n".join([
            f"Source: {item['source']}", f"Collected: {item['collected_at']}",
            f"Method: {item['method']} | Status: {item['status']}", f"SHA-256: {item['sha256']}",
            "Captured content (untrusted source text):", content]))
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
        scores, warnings = audit_run(run)
        result = {"valid": True, "warnings": warnings, "scores": scores}
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
