"""Inventory a saved HTML response: python evidence.py page.html."""
import hashlib
import json
import math
import sys
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path


def strict_json(text):
    """Reject non-standard constants and duplicate keys, retaining no ambiguity."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    def constant(value):
        raise ValueError(f"Non-standard JSON constant: {value}")
    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"JSON number exceeds finite range: {value}")
        return number
    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant, parse_float=finite_float)


def validate_registry(records):
    """Validate captured text records; hashes prove integrity, not factual truth."""
    if not isinstance(records, list):
        raise ValueError("evidence must be a list")
    registry = {}
    required = {"id", "source", "collected_at", "method", "content", "status", "sha256"}
    for record in records:
        if not isinstance(record, dict) or set(record) != required:
            raise ValueError(f"Evidence requires exactly these fields: {sorted(required)}")
        for key in required:
            if not isinstance(record[key], str):
                raise ValueError(f"Evidence {key} must be text")
        for key in ("id", "source", "collected_at", "method", "status"):
            if not record[key].strip():
                raise ValueError(f"Evidence {key} cannot be empty")
        if record["id"] in registry:
            raise ValueError(f"Duplicate evidence ID: {record['id']}")
        try:
            stamp = datetime.fromisoformat(record["collected_at"].replace("Z", "+00:00"))
            if stamp.utcoffset() is None:
                raise ValueError()
        except ValueError:
            raise ValueError("collected_at must be an ISO timestamp with timezone") from None
        if record["status"] not in {"success", "failed", "unavailable"}:
            raise ValueError("Invalid collection status")
        if not record["content"].strip():
            raise ValueError("Capture content or a collection error diagnostic")
        digest = hashlib.sha256(record["content"].encode("utf-8")).hexdigest()
        if record["sha256"] != digest:
            raise ValueError(f"Evidence hash mismatch: {record['id']}")
        registry[record["id"]] = record
    return registry


def resolve_ids(ids, registry, *, require_success=True):
    if (not isinstance(ids, list) or not ids
            or any(not isinstance(value, str) or not value.strip() for value in ids)):
        raise ValueError("evidence_ids must be a nonempty list of nonempty strings")
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate evidence reference")
    for identifier in ids:
        if identifier not in registry:
            raise ValueError(f"Unresolved evidence ID: {identifier}")
        if require_success and registry[identifier]["status"] != "success":
            raise ValueError(f"Collection did not succeed: {identifier}")
    return [registry[identifier] for identifier in ids]


class Inventory(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.result = {"title": "", "titles": [], "descriptions": [], "canonicals": [], "jsonld": [], "errors": [],
                       "not_checked": ["indexing", "robots", "schema semantics", "microdata", "rdfa", "rendered content"]}
        self.in_title = False
        self.in_json = False
        self.buffer = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        # HTML permits empty/boolean/custom attributes (including Astro markers).
        # Diagnose only missing values on the fields this inventory consumes.
        required_values = {'meta': {'name', 'content'}, 'link': {'rel', 'href'}, 'script': {'type'}}
        for key, value in attrs.items():
            if value is None and key in required_values.get(tag, set()):
                self.result["errors"].append(f"Valueless attribute {key} on {tag} at {self.getpos()}")
        attrs = {key: value or "" for key, value in attrs.items()}
        if tag == "title":
            self.in_title = True
            self.result["titles"].append({"text": "", "line": self.getpos()[0], "column": self.getpos()[1]})
        if tag == "meta" and attrs.get("name", "").lower() == "description":
            self.result["descriptions"].append(attrs.get("content", ""))
        if tag == "link" and "canonical" in attrs.get("rel", "").lower().split():
            self.result["canonicals"].append(attrs.get("href", ""))
        if tag == "script" and attrs.get("type", "").lower().strip() == "application/ld+json":
            self.in_json = True
            self.buffer = []

    def handle_data(self, data):
        if self.in_title:
            self.result["titles"][-1]["text"] += data
            self.result["title"] = self.result["titles"][0]["text"]
        if self.in_json:
            self.buffer.append(data)

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag == "script" and self.in_json:
            raw = "".join(self.buffer)
            block = {"raw": raw, "value": None, "types": []}
            try:
                block["value"] = strict_json(raw)
                block["types"] = sorted(set(types(block["value"])))
            except ValueError as exc:
                self.result["errors"].append(str(exc))
            self.result["jsonld"].append(block)
            self.in_json = False


def types(value):
    if isinstance(value, dict):
        kind = value.get("@type", [])
        if isinstance(kind, str):
            yield kind
        elif isinstance(kind, list):
            yield from (item for item in kind if isinstance(item, str))
        for child in value.values():
            yield from types(child)
    elif isinstance(value, list):
        for child in value:
            yield from types(child)


def extract(html):
    parser = Inventory()
    parser.feed(html)
    parser.close()
    if len(parser.result["titles"]) > 1:
        parser.result["errors"].append("Multiple title elements; title is the first observation")
    if parser.in_json:
        parser.result["errors"].append("Unclosed JSON-LD script")
    return parser.result


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--record-id", help="Emit a validated evidence record instead of an HTML inventory")
    parser.add_argument("--source")
    parser.add_argument("--collected-at", help="Actual collection time with timezone, not report creation time")
    parser.add_argument("--method")
    parser.add_argument("--status", choices=["success", "failed", "unavailable"], default="success")
    args = parser.parse_args()
    try:
        body = args.file.read_bytes()
        if args.record_id:
            content = body.decode("utf-8")
            result = {"id": args.record_id, "source": args.source, "collected_at": args.collected_at,
                      "method": args.method, "status": args.status, "content": content,
                      "sha256": hashlib.sha256(body).hexdigest()}
            validate_registry([result])
        else:
            result = extract(body.decode("utf-8", errors="replace"))
            result["sha256"] = hashlib.sha256(body).hexdigest()
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Evidence failed: {exc}\n")


if __name__ == "__main__":
    main()
