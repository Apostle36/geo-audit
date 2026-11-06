"""Sample composition computed from saved sitemap evidence, and checks for hand-written counts."""
import re
from urllib.parse import urlsplit
from xml.etree import ElementTree

WORDS = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve',
         'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen', 'twenty']
TENS = {'twenty': 20, 'thirty': 30, 'forty': 40, 'fifty': 50}
NUMBER_WORDS = {word: value for value, word in enumerate(WORDS)}
for tens, base in TENS.items():
    NUMBER_WORDS[tens] = base
    if base < 50:
        for unit in range(1, 10):
            NUMBER_WORDS[f'{tens}-{WORDS[unit]}'] = base + unit
NUMBER = r'(\d{1,4}|' + '|'.join(sorted(map(re.escape, NUMBER_WORDS), key=len, reverse=True)) + r')'
COUNT = re.compile(rf'\b{NUMBER}\s+of\s+(?:the\s+)?{NUMBER}\s+((?:[A-Za-z][\w-]*\s*){{1,3}})', re.I)
TOTAL_NOUNS = ('sitemap url', 'sitemap page', 'sitemap address', 'sitemap entr', 'listed url', 'public url')


def number(text):
    text = text.lower()
    return int(text) if text.isdigit() else NUMBER_WORDS[text]


def sitemap_urls(records):
    """Page URLs from saved urlset sitemaps, in document order, without duplicates."""
    urls = []
    for record in records:
        if record.get('status') != 'success':
            continue
        body = record['content'].partition('\n\n')[2] if record['content'].startswith('Request: ') else record['content']
        if '<urlset' not in body:
            continue
        try:
            root = ElementTree.fromstring(body.strip().encode('utf-8'))
        except ElementTree.ParseError:
            continue
        for element in root.iter():
            if element.tag.rsplit('}', 1)[-1] == 'loc' and element.text and element.text.strip() not in urls:
                urls.append(element.text.strip())
    return urls


def section_of(url):
    parts = [p for p in urlsplit(url).path.split('/') if p]
    return '/' if len(parts) <= 1 else '/' + '/'.join(parts[:-1]) + '/'


def path_of(url):
    path = urlsplit(url).path or '/'
    return path if path.endswith('/') else path + '/'


def group_urls(urls, sample=(), legal=()):
    """Group pages by parent path section. A section's own page is its hub, not one of its items."""
    paths = {path_of(url) for url in urls}
    groups = {}
    for url in urls:
        section = section_of(url)
        if path_of(url) == '/' and section == '/':
            continue  # The homepage belongs to no section.
        group = groups.setdefault(section, {'section': section, 'label': section.strip('/').rsplit('/', 1)[-1] or 'top-level',
                                            'items': 0, 'sampled': 0, 'hub': section != '/' and section in paths, 'legal': 0})
        if url in legal:
            group['legal'] += 1
            continue
        group['items'] += 1
        group['sampled'] += url in sample
    return [groups[key] for key in sorted(groups)]


def singular(word):
    word = word.lower()
    for suffix, replacement in (('ies', 'y'), ('ses', 's'), ('s', '')):
        if word.endswith(suffix) and len(word) > len(suffix) + 2:
            return word[:-len(suffix)] + replacement
    return word


def count_claims(text):
    for match in COUNT.finditer(text):
        yield match.group(0).strip(), number(match.group(1)), number(match.group(2)), match.group(3).strip()


def count_issues(texts, urls, sample, legal=()):
    """Hand-written "N of M <noun>" counts that disagree with counts computed from the sitemap."""
    if not urls:
        return []
    groups = group_urls(urls, sample, legal)
    by_label = {}
    for group in groups:
        by_label.setdefault(singular(group['label']), []).append(group)
    in_sitemap = sum(url in urls for url in sample)
    issues = []
    for text in texts:
        for phrase, n, m, noun in count_claims(text):
            lowered = noun.lower()
            if any(lowered.startswith(key) for key in TOTAL_NOUNS):
                if (n, m) != (in_sitemap, len(urls)):
                    issues.append(f"Count '{phrase}' disagrees with the saved sitemap: {in_sitemap} of the "
                                  f"{len(urls)} sitemap URLs are in the sample")
                continue
            matches = by_label.get(singular(lowered.split()[0]), [])
            if len(matches) != 1:
                continue  # No section or several share the noun; nothing to verify mechanically.
            group = matches[0]
            if (n, m) != (group['sampled'], group['items']):
                hub = ' plus the section page' if group['hub'] else ''
                issues.append(f"Count '{phrase}' disagrees with the saved sitemap: it lists {group['items']} "
                              f"{group['label']} ({group['section']}){hub}, and {group['sampled']} of them are sampled")
    return issues


def composition_sentence(urls, sample, legal=()):
    """A count sentence generated from the sitemap, phrased so the count check can verify it."""
    if not urls:
        return ''
    legal = [url for url in legal if url in sample]
    in_sitemap = sum(url in urls for url in sample)
    parts = [f'Computed from the saved sitemap: {in_sitemap} of {len(urls)} sitemap URLs are sampled']
    for group in group_urls(urls, sample, legal):
        if group['items'] < 2 and not group['hub']:
            continue
        hub = ', plus the section page' if group['hub'] else ''
        noun = group['label'] if group['label'].endswith('s') else group['label'] + ' pages'
        parts.append(f"{group['sampled']} of {group['items']} {noun} ({group['section']}{hub})")
    sentence = '; '.join(parts) + '.'
    if legal:
        sentence += f" Legal pages sampled outside these counts: {', '.join(urlsplit(u).path for u in legal)}."
    return sentence
