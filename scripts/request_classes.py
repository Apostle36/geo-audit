"""Classify browser requests from scripts/data/request_classes.json. Vendor knowledge lives in the data file."""
import json
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

DATA = Path(__file__).resolve().parent / 'data' / 'request_classes.json'
# Categories whose requests cannot change the visible page content.
NON_CONTENT = {'analytics', 'session_recording', 'advertising', 'consent'}


@lru_cache(maxsize=1)
def load():
    data = json.loads(DATA.read_text(encoding='utf-8'))
    if set(data['order']) != set(data['categories']):
        raise ValueError('request_classes.json: order must list every category exactly once')
    return data


def classify(url):
    """Return a category name, or 'unclassified' when nothing matches."""
    data = load()
    try:
        parts = urlsplit(url)
    except ValueError:
        return 'unclassified'
    host = (parts.hostname or '').lower()
    target = (parts.path + ('?' + parts.query if parts.query else '')).lower()
    for name in data['order']:
        rules = data['categories'][name]
        if any(host == item or host.endswith('.' + item) for item in rules['hosts']):
            return name
        if any(pattern.lower() in target for pattern in rules['paths']):
            return name
        if any(host.startswith(prefix) for prefix in rules['host_prefixes']):
            return name
    return 'unclassified'


def label(category):
    return load()['labels'].get(category, category)


def changes_content(category):
    return category not in NON_CONTENT
