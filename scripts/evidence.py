"""Inventory a saved HTML response: python evidence.py page.html."""
import hashlib
import json
import sys
from html.parser import HTMLParser
from pathlib import Path


class Inventory(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.result = {"title": "", "descriptions": [], "canonicals": [], "jsonld": [], "errors": []}
        self.in_title = False
        self.in_json = False
        self.buffer = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "title":
            self.in_title = True
        if tag == "meta" and attrs.get("name", "").lower() == "description":
            self.result["descriptions"].append(attrs.get("content", ""))
        if tag == "link" and "canonical" in attrs.get("rel", "").lower().split():
            self.result["canonicals"].append(attrs.get("href", ""))
        if tag == "script" and attrs.get("type", "").lower().strip() == "application/ld+json":
            self.in_json = True
            self.buffer = []

    def handle_data(self, data):
        if self.in_title:
            self.result["title"] += data
        if self.in_json:
            self.buffer.append(data)

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag == "script" and self.in_json:
            raw = "".join(self.buffer)
            block = {"raw": raw, "value": None, "types": []}
            try:
                block["value"] = json.loads(raw)
                block["types"] = sorted(set(types(block["value"])))
            except json.JSONDecodeError as exc:
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
    if parser.in_json:
        parser.result["errors"].append("Unclosed JSON-LD script")
    return parser.result


if __name__ == "__main__":
    body = Path(sys.argv[1]).read_bytes()
    result = extract(body.decode("utf-8", errors="replace"))
    result["sha256"] = hashlib.sha256(body).hexdigest()
    print(json.dumps(result, ensure_ascii=False, indent=2))
