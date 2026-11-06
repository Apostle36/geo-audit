"""Shared helpers that tie written claims to saved evidence. Matching is textual, never semantic."""
import html
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

SOURCE_TYPES = ('audited_site', 'off_site', 'search_snippet', 'owner_statement')
CAPTURE_TYPES = {'audited_site', 'off_site'}
COLLECTOR_METHODS = ('collect.py', 'browser_collect.py')

QUOTES = str.maketrans({'‘': "'", '’': "'", '‚': "'", '‛': "'", '′': "'",
                        '“': '"', '”': '"', '„': '"', '‟': '"', '″': '"',
                        ' ': ' ', ' ': ' ', ' ': ' '})


def normalise_text(text):
    """Collapse whitespace, decode HTML entities and straighten curly quotes."""
    return ' '.join(html.unescape(text).translate(QUOTES).split())


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def visible_text(content):
    parser = _Text()
    try:
        parser.feed(content)
        parser.close()
    except Exception:  # Untrusted markup; fall back to the raw text.
        return content
    return ' '.join(parser.parts)


class Searchable:
    """Normalised raw and tag-free forms of one evidence record, computed once."""

    def __init__(self, record):
        self.record = record
        content = record['content']
        self.raw = normalise_text(content)
        self.text = normalise_text(visible_text(content))
        self.hrefs = {html.unescape(value).strip() for value in
                      re.findall(r'''href\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))''', content, re.I)
                      for value in value if value}

    def has_text(self, text, *, case=True):
        needle = normalise_text(text)
        if not needle:
            return False
        if case:
            return needle in self.raw or needle in self.text
        return needle.lower() in self.raw.lower() or needle.lower() in self.text.lower()

    def has_href(self, href):
        href = html.unescape(href).strip()
        base = self.record['source'] if self.record['source'].startswith(('http://', 'https://')) else ''
        target = urljoin(base, href) if base else href
        return any(value == href or (base and urljoin(base, value) == target) for value in self.hrefs)


class Index:
    def __init__(self, registry):
        self.registry, self.cache = registry, {}

    def __call__(self, identifier):
        if identifier not in self.cache:
            self.cache[identifier] = Searchable(self.registry[identifier])
        return self.cache[identifier]


def excerpt_found(searchable, excerpt):
    if 'href' in excerpt:
        return searchable.has_href(excerpt['href'])
    return searchable.has_text(excerpt['text'])


def hostname(url):
    try:
        return (urlsplit(url).hostname or '').lower()
    except ValueError:  # A malformed source (for example a bad IPv6 literal) names no host.
        return ''


def site_family(url):
    host = hostname(url)
    return host[4:] if host.startswith('www.') else host


def on_audited_site(source, origin):
    if not source.startswith(('http://', 'https://')):
        return False
    host, root = hostname(source), site_family(origin)
    return bool(host) and (host == root or host.endswith('.' + root))


def source_type(record, origin):
    """The declared type, or for older records an inference from method and source."""
    if record.get('source_type'):
        return record['source_type']
    method, source = record['method'].lower(), record['source']
    if 'owner' in method:
        return 'owner_statement'
    if not source.startswith(('http://', 'https://')):
        return 'search_snippet' if 'search' in method or 'search' in source.lower() else 'unclassified'
    if 'websearch' in method or 'search result' in method or 'search log' in method:
        return 'search_snippet'
    return 'audited_site' if on_audited_site(source, origin) else 'off_site'


# A full stop after these words (or after initials such as "U.S.") does not end a sentence.
ABBREVIATIONS = {'e.g', 'i.e', 'etc', 'vs', 'approx', 'incl', 'esp', 'cf', 'fig', 'no', 'nos', 'dr', 'mr', 'mrs',
                 'ms', 'st', 'ltd', 'inc', 'co', 'jan', 'feb', 'mar', 'apr', 'jun', 'jul', 'aug', 'sep', 'sept',
                 'oct', 'nov', 'dec'}


def split_sentences(text):
    """Deterministic sentence split shared by the contract, the claim check and the report."""
    text = ' '.join(text.split())
    sentences, start = [], 0
    for match in re.finditer(r'[.!?]["\'’”)]*\s+(?=[A-Z0-9"\'‘“(])', text):
        if text[match.start()] == '.':
            before = text[start:match.start()].split()
            word = before[-1].lstrip('([{"\'‘“').lower() if before else ''
            if word in ABBREVIATIONS or re.fullmatch(r'(?:[a-z]\.)*[a-z]', word):
                continue
        sentences.append(text[start:match.end()].strip())
        start = match.end()
    if text[start:].strip():
        sentences.append(text[start:].strip())
    return sentences


ON_PAGE = re.compile(r"\b(shows?|showing|says?|saying|links?\s+to|linking\s+to|lists?|listed|names?|named|"
                     r"displays?|displayed|states?|stated|spells?|spelled|spelt|reads?)\b", re.I)
SEARCH = re.compile(r'\bsearch(?:es|ed|ing)?\b|\bsnippets?\b', re.I)


def on_page_verbs(sentence):
    """Verbs that present something as seen on a page, ignoring "search results show" phrasing."""
    verbs = []
    for match in ON_PAGE.finditer(sentence):
        before = sentence[max(0, match.start() - 40):match.start()].split()[-4:]
        if any(SEARCH.search(word) for word in before):
            continue
        verbs.append(match.group(1).lower())
    return verbs


def mentions_search(sentence):
    return bool(SEARCH.search(sentence))


COMMON = {'the', 'this', 'that', 'these', 'those', 'there', 'their', 'they', 'then', 'when', 'where', 'which',
          'while', 'what', 'with', 'without', 'within', 'about', 'after', 'before', 'both', 'each', 'every',
          'none', 'some', 'most', 'many', 'only', 'also', 'although', 'because', 'since', 'however', 'page',
          'pages', 'site', 'website', 'search', 'google', 'title', 'heading',
          'january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october',
          'november', 'december', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'}


def distinctive_terms(sentence):
    """Quoted strings and capitalised words that are not the first word of the sentence."""
    terms = [q.strip() for q in re.findall(r"""['"‘“]([^'"’”]{3,80})['"’”]""", sentence)]
    words = re.findall(r"(?<=[\s(])([A-Z][A-Za-zÀ-ɏЀ-ӿ-]{3,})", sentence)
    terms += [w for w in words if w.lower() not in COMMON]
    return list(dict.fromkeys(t for t in terms if t))


def shingles(text, size=6):
    words = re.findall(r"[a-z0-9À-ɏЀ-ӿ']+", normalise_text(text).lower())
    return {tuple(words[i:i + size]) for i in range(len(words) - size + 1)}
