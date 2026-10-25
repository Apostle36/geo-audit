"""Inventory a saved HTML response: python evidence.py page.html."""
import hashlib
import json
import math
import re
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


TIMESTAMP = re.compile(r"(\d{4}-\d{2}-\d{2})[Tt ](\d{2}:\d{2})(?::(\d{2})(?:\.(\d+))?)?([Zz]|[+-]\d{2}:?\d{2})")


def parse_timestamp(value):
    """Parse an RFC 3339-style timestamp identically on every supported Python version."""
    match = TIMESTAMP.fullmatch(value) if isinstance(value, str) else None
    if not match:
        raise ValueError("collected_at must be an ISO timestamp with timezone")
    day, minutes, seconds, fraction, zone = match.groups()
    text = f"{day}T{minutes}:{seconds or '00'}"
    if fraction:
        text += "." + (fraction + "000000")[:6]
    if zone in "Zz":
        zone = "+00:00"
    elif ":" not in zone:
        zone = zone[:3] + ":" + zone[3:]
    try:
        return datetime.fromisoformat(text + zone)
    except ValueError:
        raise ValueError("collected_at must be an ISO timestamp with timezone") from None


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
        parse_timestamp(record["collected_at"])
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
        self.result = {"title": "", "titles": [], "descriptions": [], "canonicals": [], "jsonld": [],
                       "microdata": {"items": 0, "types": []}, "rdfa": {"typed": 0, "types": [], "vocabularies": []},
                       "errors": [],
                       "not_checked": ["indexing", "robots", "schema semantics", "microdata properties",
                                       "rdfa properties", "rendered content"]}
        self.in_title = False
        self.in_json = False
        self.buffer = []
        # <title> inside inline SVG or MathML labels a graphic, not the document.
        self.foreign_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        # HTML permits empty/boolean/custom attributes (including Astro markers).
        # Diagnose only missing values on the fields this inventory consumes.
        required_values = {'meta': {'name', 'content'}, 'link': {'rel', 'href'}, 'script': {'type'}}
        for key, value in attrs.items():
            if value is None and key in required_values.get(tag, set()):
                self.result["errors"].append(f"Valueless attribute {key} on {tag} at {self.getpos()}")
        attrs = {key: value or "" for key, value in attrs.items()}
        if tag in FOREIGN:
            self.foreign_depth += 1
        self.inventory_markup(attrs)
        if tag == "title" and not self.foreign_depth:
            self.in_title = True
            self.result["titles"].append({"text": "", "line": self.getpos()[0], "column": self.getpos()[1]})
        if tag == "meta" and attrs.get("name", "").lower() == "description":
            self.result["descriptions"].append(attrs.get("content", ""))
        if tag == "link" and "canonical" in attrs.get("rel", "").lower().split():
            self.result["canonicals"].append(attrs.get("href", ""))
        if tag == "script" and attrs.get("type", "").lower().strip() == "application/ld+json":
            self.in_json = True
            self.buffer = []

    def inventory_markup(self, attrs):
        """Count Microdata items and typed RDFa resources; properties are not parsed."""
        if "itemscope" in attrs:
            self.result["microdata"]["items"] += 1
            add_unique(self.result["microdata"]["types"], attrs.get("itemtype", "").split())
        # Property-only RDFa, such as Open Graph meta tags, is not counted as typed data.
        if "typeof" in attrs or "vocab" in attrs:
            self.result["rdfa"]["typed"] += 1
            add_unique(self.result["rdfa"]["types"], attrs.get("typeof", "").split())
            add_unique(self.result["rdfa"]["vocabularies"], attrs.get("vocab", "").split())

    def handle_data(self, data):
        if self.in_title:
            self.result["titles"][-1]["text"] += data
            self.result["title"] = self.result["titles"][0]["text"]
        if self.in_json:
            self.buffer.append(data)

    def handle_endtag(self, tag):
        if tag in FOREIGN and self.foreign_depth:
            self.foreign_depth -= 1
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


FOREIGN = {"svg", "math"}


def add_unique(target, values):
    target.extend(value for value in values if value not in target)


def structured_data_markers(inventory):
    """Describe JSON-LD, Microdata or typed RDFa found by extract(); empty when none was seen."""
    markers = []
    if inventory["jsonld"]:
        markers.append(f"{len(inventory['jsonld'])} JSON-LD block(s)")
    if inventory["microdata"]["items"]:
        markers.append(f"{inventory['microdata']['items']} Microdata item(s)")
    if inventory["rdfa"]["typed"]:
        markers.append(f"{inventory['rdfa']['typed']} typed RDFa resource(s)")
    return markers


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


def document_title(html):
    """Read a title without parsing unrelated structured data for a display label."""
    class TitleOnly(Inventory):
        def handle_starttag(self, tag, attrs):
            if tag in {'title', *FOREIGN}:
                super().handle_starttag(tag, attrs)
    if html.startswith('Request: GET '):
        html = html.partition('\n\n')[2]
    parser = TitleOnly()
    parser.feed(html)
    parser.close()
    return parser.result['title']


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
    if args.record_id and not (args.source and args.collected_at and args.method):
        parser.error("--record-id requires --source, --collected-at and --method")
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
