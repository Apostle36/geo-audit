"""Synthetic schema 1.5.0 runs. Brand names here are invented test values, not product logic."""
import copy
import hashlib

from test_reliability import scoring

SITE = 'https://example.com/'
HOME, ABOUT, CLIENT, PRIVACY = SITE, SITE + 'about/', SITE + 'work/widgetco/', SITE + 'privacy/'
SAMPLE = [HOME, ABOUT, CLIENT, PRIVACY]
STAMP = '2026-09-10T10:00:00Z'

PAGES = {
    HOME: ('<html><head><title>Acme Studio</title></head><body><main><h1>Acme Studio</h1>'
           '<p>Acme Studio builds websites for industrial companies.</p></main>'
           '<footer><a href="/privacy/">Privacy policy</a> <a href="/terms/">Terms of use</a></footer></body></html>'),
    ABOUT: ('<html><head><title>About</title></head><body><main><h2>Jane&nbsp;Smyth&rsquo;s role</h2>'
            '<p>Our collaborator Jane Smyth runs <a href="https://studio.example/">Studio Example</a>.</p>'
            '</main></body></html>'),
    CLIENT: ('<html><head><title>Widgetco case study</title></head><body><main>'
             '<p>We rebuilt the website for Widgetco Ltd in 2025.</p></main></body></html>'),
    PRIVACY: ('<html><head><title>Privacy</title></head><body><main>'
              '<p>This site is operated by Acme Studio EOOD, Sofia.</p></main></body></html>'),
}

SITEMAP_URLS = [HOME, ABOUT, SITE + 'work/', CLIENT, PRIVACY, SITE + 'terms/', SITE + 'resources/templates/',
                *(SITE + f'resources/templates/t{n}/' for n in range(1, 9))]


def http_record(identifier, url, body, *, source_type='audited_site'):
    content = (f'Request: GET {url}\nUser-Agent: GEO-Audit/1.8.0\nResponse: 200 OK\nFinal URL: {url}\n'
               f'Content-Type: text/html; charset=utf-8\n\n{body}')
    return {'id': identifier, 'source': url, 'collected_at': STAMP,
            'method': 'collect.py 1.8.0: HTTP GET without JavaScript', 'content': content, 'status': 'success',
            'sha256': hashlib.sha256(content.encode()).hexdigest(), 'source_type': source_type}


def note_record(identifier, source, content, source_type, method):
    return {'id': identifier, 'source': source, 'collected_at': STAMP, 'method': method, 'content': content,
            'status': 'success', 'sha256': hashlib.sha256(content.encode()).hexdigest(), 'source_type': source_type}


def sitemap_record():
    body = ('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + ''.join(f'<url><loc>{url}</loc></url>' for url in SITEMAP_URLS) + '</urlset>')
    record = http_record('discovery-sitemap-01', SITE + 'sitemap.xml', body)
    record['content'] = record['content'].replace('text/html', 'application/xml')
    record['sha256'] = hashlib.sha256(record['content'].encode()).hexdigest()
    return record


def evidence():
    records = [http_record(f'page-{n}', url, PAGES[url]) for n, url in enumerate(SAMPLE, 1)]
    records.append(sitemap_record())
    records.append(note_record('search-1', 'web-search-log-2026-09-10',
                               'Query 1 (2026-09-10): "Jane Smith studio" - result: linkedin.com/in/janesmith, '
                               'profile title Jane Smith, Studio Example.',
                               'search_snippet', 'WebSearch queries summarised as a dated log'))
    records.append(http_record('register-1', 'https://register.example/company/123',
                               '<html><body><p>Company name: ACME STUDIO EOOD</p></body></html>',
                               source_type='off_site'))
    return records


def criteria():
    rubric, _ = scoring.load_rubric('1.2.0')
    ids = [f'page-{n}' for n in range(1, len(SAMPLE) + 1)]
    return {category: [{'id': rule['id'], 'status': 'assessed', 'value': 100,
                        'rationale': 'Synthetic fixture: all sampled pages meet the anchor.', 'evidence_ids': ids[:]}
                       for rule in profile['criteria']]
            for category, profile in rubric['categories'].items()}


def finding(identifier, **changes):
    value = {'id': identifier, 'category': 'content', 'kind': 'observation', 'status': 'present',
             'affected_urls': [ABOUT], 'evidence_ids': ['page-2'],
             'title': 'Correct the collaborator name on the about page',
             'excerpts': [{'evidence_id': 'page-2', 'text': 'Jane Smyth'}],
             'criteria': ['accountability'],
             'observed': "The about page names the collaborator 'Jane Smyth'.",
             'claim': 'A collaborator name may be misspelled.', 'consequence': 'Searches for her name may miss the studio.',
             'fix': 'Confirm the spelling with her and correct the about page.',
             'acceptance': 'The about page shows the confirmed spelling.', 'severity': 'low',
             'confidence_reason': 'Read in the saved about page capture.'}
    value.update(changes)
    return value


def strength():
    return finding('F2', kind='observation', severity='informational', affected_urls=[HOME],
                   evidence_ids=['page-1'], title='Keep the plain description on the homepage',
                   excerpts=[{'evidence_id': 'page-1', 'text': 'Acme Studio builds websites for industrial companies.'}],
                   criteria=[], observed="The homepage says 'Acme Studio builds websites for industrial companies.'",
                   claim='The homepage states plainly what the studio builds.', consequence='Readers understand the offer.',
                   fix='Keep this sentence.', acceptance='The sentence stays on the homepage.',
                   confidence_reason='Read in the saved homepage capture.')


def legal_finding():
    return finding('F3', category='authority', affected_urls=[PRIVACY], evidence_ids=['page-4', 'register-1'],
                   title='Use the registered company name on the privacy page',
                   excerpts=[{'evidence_id': 'page-4', 'text': 'Acme Studio EOOD'},
                             {'evidence_id': 'register-1', 'text': 'ACME STUDIO EOOD'}],
                   criteria=['identity_consistency'],
                   observed="The privacy page says the site is operated by 'Acme Studio EOOD'. The company register lists 'ACME STUDIO EOOD'.",
                   claim='The privacy page does not use the registered company name.',
                   consequence='Readers who check the register may not match the names.',
                   fix='Change the operator name on the privacy page to ACME STUDIO EOOD.',
                   acceptance='The privacy page shows ACME STUDIO EOOD.',
                   confidence_reason='Read in the saved privacy page and register captures.')


def questions():
    return [f'Synthetic buyer question {n}?' for n in range(1, 16)]


def v15_run():
    """A valid 1.5.0 run: on-page claims cite captures of the named pages; entities and questions agree."""
    run = {
        'schema_version': '1.5.0',
        'metadata': {'url': SITE, 'date': '2026-09-10', 'business_type': 'Synthetic studio', 'market': 'Test market',
                     'language': 'en', 'sample': SAMPLE[:], 'legal_pages': [PRIVACY],
                     'sampling_rationale': 'Synthetic fixture: homepage, about page, one case study and the privacy page.'},
        'assessment': {'rubric_version': '1.2.0', 'evidence': evidence(), 'criteria': criteria()},
        'summary': 'Synthetic test conclusion, not a live audit.',
        'limitations': ['Synthetic data only.'],
        'findings': [finding('F1'), strength(), legal_finding()],
        'review': [{'category': 'content', 'topic': 'expertise', 'status': 'assessed',
                    'summary': 'The about page names the collaborator; see the related finding.',
                    'affected_urls': SAMPLE[:], 'evidence_ids': [f'page-{n}' for n in range(1, 5)],
                    'finding_ids': ['F1']}],
        'entities': [
            {'id': 'E1', 'name': 'Jane Smith', 'kind': 'person',
             'spellings': [{'text': 'Jane Smyth', 'evidence_ids': ['page-2']},
                           {'text': 'Jane Smith', 'evidence_ids': ['search-1']}],
             'reference': None, 'status': 'needs_owner', 'finding_ids': ['F1']},
            {'id': 'E2', 'name': 'Acme Studio', 'kind': 'business',
             'spellings': [{'text': 'Acme Studio EOOD', 'evidence_ids': ['page-4']}],
             'reference': {'spelling': 'ACME STUDIO EOOD', 'evidence_id': 'register-1', 'basis': 'official_register'},
             'status': 'wrong', 'finding_ids': ['F3']}],
        'owner_questions': [
            {'id': 'Q1', 'question': "Is your collaborator's surname spelled Smyth or Smith?",
             'seen': "The about page says 'Jane Smyth'; a search result for her profile says 'Jane Smith'.",
             'why': 'A wrong spelling stops searches for her name from finding the studio.',
             'likely_answers': ['Smyth', 'Smith'], 'finding_ids': ['F1'], 'entity_ids': ['E1'],
             'evidence_ids': ['page-2', 'search-1']}],
        'claim_check': None,
        'visibility': {'inputs': {'services': ['websites'], 'customer_types': ['industrial companies'],
                                  'market': 'Test market'},
                       'questions': questions(), 'observations': []},
    }
    return run


def with_claim_check(run, verdict='supported'):
    from claim_check import worklist
    run = copy.deepcopy(run)
    run['claim_check'] = {'reviewer': 'Independent checker', 'reviewer_type': 'agent', 'checked_at': STAMP,
                          'sentences': [{**item, 'verdict': verdict, 'note': 'Synthetic verdict.'}
                                        for item in worklist(run)]}
    return run


def rehash(record):
    record['sha256'] = hashlib.sha256(record['content'].encode()).hexdigest()
    return record


def deliverable(run):
    """Add what a 1.5.0 run needs before delivery: a buyer question set and a complete claim check."""
    run = copy.deepcopy(run)
    run['visibility'] = {'inputs': {'services': ['websites'], 'customer_types': ['industrial companies'],
                                    'market': run['metadata']['market']}, 'questions': questions(), 'observations': []}
    return with_claim_check(run)


def legacy(run, version):
    """The same run in an older schema, without the fields that 1.5.0 introduced."""
    run = copy.deepcopy(run)
    run['schema_version'] = version
    for key in ('entities', 'owner_questions', 'claim_check', 'visibility'):
        run.pop(key, None)
    run['metadata'].pop('legal_pages', None)
    for record in run['assessment']['evidence']:
        record.pop('source_type', None)
    for finding in run['findings']:
        for key in ('title', 'excerpts', 'criteria'):
            finding.pop(key, None)
    for item in run.get('review', []):
        item.pop('finding_ids', None)
    if version == '1.2.0':
        run.pop('review', None)
    return run
