"""Recognise legal pages (privacy, terms, cookies, legal notice, imprint) from scripts/data/legal_pages.json."""
import json
import re
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlsplit

DATA = Path(__file__).resolve().parent / 'data' / 'legal_pages.json'


@lru_cache(maxsize=1)
def patterns():
    data = json.loads(DATA.read_text(encoding='utf-8'))
    return [s.lower() for s in data['path_segments']], [label.lower() for label in data['labels']]


def is_legal_url(url):
    segments, _ = patterns()
    try:
        path = urlsplit(url).path
    except ValueError:
        return False
    parts = [p.lower() for p in path.split('/') if p]
    return any(part == s or part.startswith(s + '-') or part.startswith(s + '.') for part in parts for s in segments)


def is_legal_label(text):
    _, labels = patterns()
    text = ' '.join(text.lower().split())
    return any(re.search(r'(?<!\w)' + re.escape(label) + r'(?!\w)', text) for label in labels)


class FooterLinks(HTMLParser):
    """Anchors inside <footer> or role="contentinfo", plus every anchor as a fallback."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth, self.footer, self.anywhere, self.current = 0, [], [], None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'footer' or attrs.get('role') == 'contentinfo':
            self.depth += 1
        if tag == 'a' and attrs.get('href'):
            self.current = {'href': attrs['href'], 'text': ''}
            self.anywhere.append(self.current)
            if self.depth:
                self.footer.append(self.current)

    def handle_endtag(self, tag):
        if tag == 'footer' and self.depth:
            self.depth -= 1
        if tag == 'a':
            self.current = None

    def handle_data(self, data):
        if self.current is not None and len(self.current['text']) < 160:
            self.current['text'] += data


def legal_links(html, origin, final_url, *, limit=10):
    """Same-site legal links from the page footer, or from the whole page when it has no footer."""
    parser = FooterLinks()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # Untrusted markup; keep what was parsed.
        pass
    host = (urlsplit(origin).hostname or '').lower()
    bare = host[4:] if host.startswith('www.') else host
    found = []
    for link in parser.footer or parser.anywhere:
        try:
            url = urldefrag(urljoin(final_url, link['href'].strip()))[0]
            parts = urlsplit(url)
        except ValueError:
            continue
        if parts.scheme not in ('http', 'https') or (parts.hostname or '').lower() not in {bare, 'www.' + bare}:
            continue
        label = ' '.join(link['text'].split())[:120]
        if (is_legal_url(url) or is_legal_label(label)) and url not in [item['loc'] for item in found]:
            found.append({'loc': url, 'label': label, 'source': 'footer' if parser.footer else 'page'})
        if len(found) == limit:
            break
    return found
