"""Checks added in toolkit 1.8.0. Schema 1.5.0 turns most of them into errors; older runs get warnings."""
import json
import re
from datetime import date

from claims import (CAPTURE_TYPES, COLLECTOR_METHODS, Index, distinctive_terms, excerpt_found, mentions_search,
                    normalise_text, on_audited_site, on_page_verbs, shingles, source_type, split_sentences)
from evidence import parse_timestamp
from legal_pages import is_legal_url
from request_classes import classify
from sample_groups import count_issues, sitemap_urls

ENTITY_KINDS = {'business', 'client', 'person', 'organisation'}
ENTITY_STATUSES = {'confirmed', 'inconsistent', 'wrong', 'needs_owner'}
REFERENCE_BASES = {'entity_site', 'official_register', 'owner'}
VERDICTS = {'supported', 'search_only', 'unsupported'}
TYPE_LABELS = {'search_snippet': 'search-result snippet', 'owner_statement': 'owner statement'}
NEGATIVE_LEGAL = re.compile(
    r"\bno (?:sampled |captured )?pages?\b[^.]{0,120}\b(?:legal entity|legal name|registered (?:company )?name|"
    r"company name|registered entity)|\b(?:legal entity|registered (?:company )?name)\b[^.]{0,60}"
    r"\b(?:not (?:found|named|shown|stated|visible)|is missing|does not appear)", re.I)
OWNER_PLACEHOLDER = re.compile(r'\[[^\]\n]{1,60}\]|\bconfirm (?:it |this |them )?with\b', re.I)


def fields(value, required, label):
    if not isinstance(value, dict) or set(value) != set(required):
        raise ValueError(f'{label} requires exactly {sorted(required)}')


def text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label} must be nonempty text')
    return value


def id_list(value, known, label, *, allow_empty=True):
    if not isinstance(value, list) or (not allow_empty and not value) or len(set(map(str, value))) != len(value):
        raise ValueError(f'{label} must be a list of unique IDs')
    for item in value:
        if not isinstance(item, str) or item not in known:
            raise ValueError(f'{label} refers to an unknown ID: {item!r}')
    return value


def success(registry, identifier, label):
    if identifier not in registry:
        raise ValueError(f'{label} cites unresolved evidence ID: {identifier}')
    if registry[identifier]['status'] != 'success':
        raise ValueError(f'{label} cites unsuccessful evidence: {identifier}')
    return registry[identifier]


def word_in(needle, haystack):
    return re.search(r'(?<![\w-])' + re.escape(normalise_text(needle)) + r'(?![\w-])', normalise_text(haystack)) is not None


# ---------------------------------------------------------------------------
# Schema 1.5.0 structure (errors)
# ---------------------------------------------------------------------------

def strict_issues(run, registry, scores):
    """Return the 1.5.0 contract problems; the caller raises them."""
    origin, issues = run['metadata']['url'], []
    index = Index(registry)
    for record in registry.values():
        kind = record.get('source_type')
        if kind is None:
            issues.append(f"Evidence {record['id']} needs a source_type in schema 1.5.0")
        elif kind == 'audited_site' and not on_audited_site(record['source'], origin):
            issues.append(f"Evidence {record['id']} is marked audited_site, but {record['source']} is not on the audited site")
        elif kind == 'off_site' and on_audited_site(record['source'], origin):
            issues.append(f"Evidence {record['id']} is marked off_site, but {record['source']} is on the audited site")
        elif kind in TYPE_LABELS and record['method'].startswith(COLLECTOR_METHODS):
            issues.append(f"Evidence {record['id']} comes from a collector and cannot be a {TYPE_LABELS[kind]}")
    sample = run['metadata']['sample']
    legal = run['metadata']['legal_pages']
    if not isinstance(legal, list) or len(set(legal)) != len(legal) or any(url not in sample for url in legal):
        issues.append('metadata.legal_pages must be a unique subset of the sample')
    finding_ids = {f['id'] for f in run['findings']}
    criterion_ids = {c['id'] for c in scores['criteria']}
    for finding in run['findings']:
        issues += finding_issues(finding, registry, index, origin, criterion_ids)
    for item in run['review']:
        try:
            id_list(item['finding_ids'], finding_ids, f"Review {item['category']}.{item['topic']} finding_ids")
        except ValueError as exc:
            issues.append(str(exc))
    for check in (entity_issues, owner_question_issues, visibility_issues, claim_check_issues):
        try:
            issues += check(run, registry, index)
        except ValueError as exc:
            issues.append(str(exc))
    return issues


def finding_issues(finding, registry, index, origin, criterion_ids):
    label, issues = f"Finding {finding['id']}", []
    title = finding['title']
    if not isinstance(title, str) or not title.strip() or len(title) > 90 or '\n' in title or title.endswith('…'):
        issues.append(f'{label} needs a one-line action title of at most 90 characters')
    criteria = finding['criteria']
    if not isinstance(criteria, list) or len(set(map(str, criteria))) != len(criteria) \
            or any(c not in criterion_ids for c in criteria):
        issues.append(f'{label} criteria must be unique criterion IDs from rubric 1.2.0')
    excerpts = finding['excerpts']
    if not isinstance(excerpts, list):
        return issues + [f'{label} excerpts must be a list']
    if finding['kind'] != 'unknown' and not excerpts:
        issues.append(f'{label} needs at least one excerpt from its cited evidence')
    sentences = split_sentences(finding['observed']) + split_sentences(finding['claim'])
    for excerpt in excerpts:
        if not isinstance(excerpt, dict) or set(excerpt) not in ({'evidence_id', 'text'}, {'evidence_id', 'href'}) \
                or not all(isinstance(v, str) and v.strip() for v in excerpt.values()):
            issues.append(f'{label} excerpts need an evidence_id and either text or href')
            continue
        identifier = excerpt['evidence_id']
        quote = excerpt.get('text', excerpt.get('href'))
        if identifier not in finding['evidence_ids']:
            issues.append(f'{label} excerpt cites {identifier}, which is not in its evidence_ids')
            continue
        record = registry[identifier]
        if record['status'] != 'success':
            issues.append(f'{label} excerpt cites unsuccessful evidence {identifier}')
            continue
        if not excerpt_found(index(identifier), excerpt):
            issues.append(f'{label}: excerpt {quote!r} not found in evidence {identifier}')
            continue
        kind = source_type(record, origin)
        needle = normalise_text(quote)
        for sentence in sentences:
            if needle not in normalise_text(sentence):
                continue
            verbs = on_page_verbs(sentence)
            short = sentence if len(sentence) <= 140 else sentence[:137] + '...'
            if verbs and kind in TYPE_LABELS:
                issues.append(f"{label}: '{short}' presents an on-page observation ('{verbs[0]}') but rests on a "
                              f"{TYPE_LABELS[kind]} ({identifier})")
            elif verbs and kind == 'audited_site' and record['source'] not in finding['affected_urls']:
                issues.append(f"{label}: '{short}' cites {identifier}, which is not a capture of a page this finding names")
            if kind == 'search_snippet' and not mentions_search(sentence):
                issues.append(f"{label}: '{short}' rests on a search-result snippet ({identifier}) and must say it "
                              'comes from search results')
    return issues


def entity_issues(run, registry, index):
    entities, issues = run['entities'], []
    if not isinstance(entities, list):
        raise ValueError('entities must be a list')
    findings = {f['id']: f for f in run['findings']}
    question_entities = {e for q in run['owner_questions'] if isinstance(q, dict)
                         for e in (q.get('entity_ids') or [])}
    seen = set()
    for entity in entities:
        fields(entity, {'id', 'name', 'kind', 'spellings', 'reference', 'status', 'finding_ids'}, 'Entity')
        label = f"Entity {entity['id']}"
        text(entity['id'], 'Entity id')
        text(entity['name'], f'{label} name')
        if entity['id'] in seen:
            raise ValueError(f'Duplicate entity ID: {entity["id"]}')
        seen.add(entity['id'])
        if entity['kind'] not in ENTITY_KINDS or entity['status'] not in ENTITY_STATUSES:
            raise ValueError(f'{label} needs a kind in {sorted(ENTITY_KINDS)} and a status in {sorted(ENTITY_STATUSES)}')
        id_list(entity['finding_ids'], findings, f'{label} finding_ids')
        if not isinstance(entity['spellings'], list) or not entity['spellings']:
            raise ValueError(f'{label} needs at least one observed spelling')
        for spelling in entity['spellings']:
            fields(spelling, {'text', 'evidence_ids'}, f'{label} spelling')
            text(spelling['text'], f'{label} spelling')
            id_list(spelling['evidence_ids'], registry, f'{label} spelling evidence', allow_empty=False)
            for identifier in spelling['evidence_ids']:
                success(registry, identifier, label)
                if not index(identifier).has_text(spelling['text']):
                    issues.append(f"{label}: spelling {spelling['text']!r} not found in evidence {identifier}")
        reference = entity['reference']
        if reference is not None:
            fields(reference, {'spelling', 'evidence_id', 'basis'}, f'{label} reference')
            text(reference['spelling'], f'{label} reference spelling')
            if reference['basis'] not in REFERENCE_BASES:
                raise ValueError(f'{label} reference basis must be one of {sorted(REFERENCE_BASES)}')
            record = success(registry, reference['evidence_id'], f'{label} reference')
            kind = source_type(record, run['metadata']['url'])
            if reference['basis'] == 'owner' and kind != 'owner_statement':
                issues.append(f'{label}: an owner reference must cite an owner_statement record')
            elif reference['basis'] != 'owner' and kind not in CAPTURE_TYPES:
                issues.append(f'{label}: an entity-site or register reference must cite a captured page')
            if not index(reference['evidence_id']).has_text(reference['spelling']):
                issues.append(f"{label}: reference spelling {reference['spelling']!r} not found in evidence "
                              f"{reference['evidence_id']}")
        if entity['status'] == 'needs_owner' and entity['id'] not in question_entities:
            issues.append(f"{label} ({entity['name']}) is marked needs_owner but no owner question asks about it")
        flagged = flagged_spellings(entity)
        for finding in findings.values():
            if not is_strength(finding):
                continue
            for spelling in flagged:
                if word_in(spelling, finding['claim']) or word_in(spelling, finding['observed']):
                    issues.append(f"Finding {finding['id']} presents {spelling!r} as a strength, but the entity "
                                  f"register marks {entity['name']} as {entity['status']}")
        if reference is not None:
            for identifier in entity['finding_ids']:
                finding = findings[identifier]
                if finding['kind'] != 'unknown' and not is_strength(finding) \
                        and normalise_text(reference['spelling']) not in normalise_text(finding['fix']):
                    basis = reference['basis'].replace('_', ' ')
                    issues.append(f"Finding {identifier} must recommend the source spelling "
                                  f"{reference['spelling']!r} from the {basis}, not a choice between spellings")
    return issues


def flagged_spellings(entity):
    if entity['status'] == 'confirmed':
        return []
    reference = (entity.get('reference') or {}).get('spelling')
    return [s['text'] for s in entity['spellings'] if s['text'] != reference]


def is_strength(finding):
    return finding['severity'] == 'informational' and finding['status'] == 'present' and finding['kind'] == 'observation'


def owner_question_issues(run, registry, index):
    questions, issues = run['owner_questions'], []
    if not isinstance(questions, list):
        raise ValueError('owner_questions must be a list')
    findings = {f['id'] for f in run['findings']}
    entities = {e['id'] for e in run['entities'] if isinstance(e, dict) and 'id' in e}
    seen_ids, seen_text = set(), {}
    for question in questions:
        fields(question, {'id', 'question', 'seen', 'why', 'likely_answers', 'finding_ids', 'entity_ids',
                          'evidence_ids'}, 'Owner question')
        label = f"Owner question {question['id']}"
        text(question['id'], 'Owner question id')
        if question['id'] in seen_ids:
            raise ValueError(f"Duplicate owner question ID: {question['id']}")
        seen_ids.add(question['id'])
        for key in ('question', 'seen', 'why'):
            text(question[key], f'{label} {key}')
        if not question['question'].rstrip().endswith('?'):
            issues.append(f'{label} must be written as a question')
        if not isinstance(question['likely_answers'], list) or not question['likely_answers'] \
                or any(not isinstance(a, str) or not a.strip() for a in question['likely_answers']):
            issues.append(f'{label} needs at least one likely answer')
        id_list(question['finding_ids'], findings, f'{label} finding_ids')
        id_list(question['entity_ids'], entities, f'{label} entity_ids')
        id_list(question['evidence_ids'], registry, f'{label} evidence_ids')
        key = re.sub(r'[^a-z0-9]+', '', question['question'].lower())
        if key in seen_text:
            issues.append(f"Duplicate owner question: {question['id']} repeats {seen_text[key]}")
        seen_text[key] = question['id']
    return issues


PLATFORMS = ('ChatGPT', 'Perplexity', 'Gemini', 'Google AI Mode', 'Copilot')


def visibility_issues(run, registry, index):
    plan = run['visibility']
    if plan is None:
        return []
    fields(plan, {'inputs', 'questions', 'observations'}, 'visibility')
    fields(plan['inputs'], {'services', 'customer_types', 'market'}, 'visibility inputs')
    for key in ('services', 'customer_types'):
        values = plan['inputs'][key]
        if not isinstance(values, list) or not values or any(not isinstance(v, str) or not v.strip() for v in values):
            raise ValueError(f'visibility inputs {key} must be a nonempty list of text')
    text(plan['inputs']['market'], 'visibility inputs market')
    questions = plan['questions']
    if not isinstance(questions, list) or not 15 <= len(questions) <= 20 \
            or any(not isinstance(q, str) or not q.strip() for q in questions) \
            or len({q.strip().lower() for q in questions}) != len(questions):
        raise ValueError('The AI visibility question set needs 15 to 20 distinct questions')
    if not isinstance(plan['observations'], list):
        raise ValueError('visibility observations must be a list')
    for item in plan['observations']:
        fields(item, {'platform', 'date', 'question', 'brand_named', 'cited_urls', 'competitors', 'evidence_id'},
               'Visibility observation')
        text(item['platform'], 'Visibility observation platform')
        try:
            date.fromisoformat(item['date'])
        except (TypeError, ValueError):
            raise ValueError('Visibility observation date must be YYYY-MM-DD') from None
        if type(item['question']) is not int or not 0 <= item['question'] < len(questions):
            raise ValueError('Visibility observation question must index the question set')
        if type(item['brand_named']) is not bool:
            raise ValueError('Visibility observation brand_named must be true or false')
        if not isinstance(item['cited_urls'], list) or any(
                not isinstance(u, str) or not u.startswith(('http://', 'https://')) for u in item['cited_urls']):
            raise ValueError('Visibility observation cited_urls must be HTTP(S) URLs')
        if not isinstance(item['competitors'], list) or any(not isinstance(c, str) or not c.strip()
                                                           for c in item['competitors']):
            raise ValueError('Visibility observation competitors must be a list of names')
        record = success(registry, item['evidence_id'], 'Visibility observation')
        if source_type(record, run['metadata']['url']) not in {'off_site', 'owner_statement'}:
            raise ValueError('Visibility observations must cite an off_site or owner_statement record')
    return []


def claim_check_issues(run, registry, index):
    check = run['claim_check']
    if check is None:
        return []
    fields(check, {'reviewer', 'reviewer_type', 'checked_at', 'sentences'}, 'claim_check')
    text(check['reviewer'], 'claim_check reviewer')
    if check['reviewer_type'] not in {'agent', 'human'}:
        raise ValueError('claim_check reviewer_type must be agent or human')
    parse_timestamp(check['checked_at'])
    if not isinstance(check['sentences'], list):
        raise ValueError('claim_check sentences must be a list')
    findings = {f['id'] for f in run['findings']}
    for item in check['sentences']:
        fields(item, {'finding_id', 'field', 'text', 'evidence_ids', 'verdict', 'note'}, 'Claim check sentence')
        if item['finding_id'] not in findings or item['field'] not in {'observed', 'claim'}:
            raise ValueError('Claim check sentence must name a finding and its observed or claim field')
        text(item['text'], 'Claim check sentence text')
        if item['verdict'] not in VERDICTS:
            raise ValueError(f'Claim check verdict must be one of {sorted(VERDICTS)}')
        if not isinstance(item['note'], str):
            raise ValueError('Claim check note must be text')
        id_list(item['evidence_ids'], registry, 'Claim check evidence_ids')
    return []


# ---------------------------------------------------------------------------
# Advisory checks for every schema (warnings) and count checks
# ---------------------------------------------------------------------------

def count_problems(run, registry):
    meta = run['metadata']
    urls = sitemap_urls(registry.values())
    legal = meta.get('legal_pages', [])
    return count_issues([meta['sampling_rationale'], *run['limitations']], urls, meta['sample'], legal)


def advisory(run, registry):
    warnings = []
    origin = run['metadata']['url']
    index = Index(registry)
    warnings += provenance_warnings(run, registry, index, origin)
    warnings += legal_warnings(run)
    warnings += recording_warnings(run, registry)
    warnings += repetition_warnings(run)
    if run.get('schema_version') == '1.5.0':
        warnings += entity_warnings(run)
        warnings += owner_warnings(run)
    return warnings


def provenance_warnings(run, registry, index, origin):
    warnings = []
    for finding in run['findings']:
        if finding['kind'] == 'unknown':
            continue
        cited = [registry[i] for i in finding['evidence_ids'] if i in registry and registry[i]['status'] == 'success']
        captures = [r for r in cited if source_type(r, origin) in CAPTURE_TYPES]
        searches = [r for r in cited if source_type(r, origin) == 'search_snippet']
        if not searches:
            continue
        for sentence in split_sentences(finding['observed']) + split_sentences(finding['claim']):
            verbs = on_page_verbs(sentence)
            if not verbs:
                continue
            for term in distinctive_terms(sentence):
                found = [r['id'] for r in searches if index(r['id']).has_text(term, case=False)]
                if found and not any(index(r['id']).has_text(term, case=False) for r in captures):
                    shown = "', '".join(dict.fromkeys(verbs))
                    warnings.append(f"Finding {finding['id']}: '{term}' appears only in search-result evidence "
                                    f"({', '.join(found)}), but its sentence presents an on-page observation "
                                    f"('{shown}'). Cite a capture of the page or say the term comes from search results.")
    return warnings


def legal_warnings(run):
    meta = run['metadata']
    sampled = meta.get('legal_pages') or [url for url in meta['sample'] if is_legal_url(url)]
    if sampled:
        return []
    from run_contract import run_text
    for value in run_text(run):
        if NEGATIVE_LEGAL.search(value):
            return ['A conclusion says no page names a legal entity or registered name, but the legal pages '
                    '(privacy, terms, cookies, imprint) were not sampled. Sample them or remove the conclusion.']
    return []


def browser_measurements(record):
    if not record['method'].startswith('browser_collect.py') or record['status'] != 'success':
        return None
    head = record['content'].partition('\n\nRendered DOM:\n')[0]
    try:
        value = json.loads(head.split('\n', 1)[1])
    except (IndexError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def blocked_by_page(registry):
    pages = {}
    for record in registry.values():
        values = browser_measurements(record)
        blocked = values.get('blocked_requests') if values else None
        if isinstance(blocked, list):
            for request in blocked:
                if isinstance(request, dict) and isinstance(request.get('url'), str):
                    pages.setdefault(request['url'], set()).add(record['source'])
    return pages


def script_checks(registry):
    """Blocked-script checks saved by the workflow, keyed by script URL."""
    return {record['source']: record for record in registry.values()
            if record['status'] == 'success' and 'Blocked-script check:' in record['content']}


def served(record):
    match = re.search(r'^Response: (\d{3})', record['content'], re.M)
    return bool(match) and match.group(1).startswith('2')


def recording_warnings(run, registry):
    warnings, checks = [], script_checks(registry)
    cited = {i for f in run['findings'] for i in f['evidence_ids']}
    for url, pages in sorted(blocked_by_page(registry).items()):
        if classify(url) != 'session_recording':
            continue
        check = checks.get(url)
        if check and check['id'] in cited:
            continue
        where = f'on {len(pages)} sampled page' + ('s' if len(pages) != 1 else '')
        if check is None:
            warnings.append(f'A session recording or heatmap script ({url}) was referenced {where} but was not '
                            'fetched or reported. Check whether it is served and record a finding.')
        elif served(check):
            warnings.append(f'A session recording or heatmap script ({url}) is served {where} but no finding cites '
                            'it. Add a finding; it is high severity when the privacy policy does not mention the tool.')
        else:
            warnings.append(f'A session recording or heatmap script ({url}) is referenced {where} but not served. '
                            'Add a low finding to remove or gate the reference.')
    return warnings


def repetition_warnings(run, threshold=0.2, size=4, minimum=8):
    """A topic summary that reuses a fifth of a finding's four-word runs is restating it, not adding to it."""
    warnings = []
    observed = {f['id']: shingles(f['observed'], size) for f in run['findings']}
    for item in run.get('review', []):
        summary = shingles(item['summary'], size)
        for identifier, parts in observed.items():
            if len(parts) >= minimum and len(parts & summary) / len(parts) >= threshold:
                warnings.append(f"Review {item['category']}.{item['topic']} repeats finding {identifier}; cite the "
                                'finding and add only what is new.')
    return warnings


def entity_warnings(run):
    warnings = []
    for entity in run['entities']:
        for spelling in flagged_spellings(entity):
            for item in run['review']:
                if word_in(spelling, item['summary']) and not set(entity['finding_ids']) & set(item['finding_ids']):
                    warnings.append(f"Review {item['category']}.{item['topic']} mentions {spelling!r} "
                                    f"({entity['name']}, {entity['status']}) without citing its finding.")
    return warnings


def owner_warnings(run):
    linked = {f for q in run['owner_questions'] for f in q['finding_ids']}
    return [f"Finding {f['id']} asks the owner for facts, but no owner question links to it. Move the request into "
            '"Questions for the owner".' for f in run['findings']
            if f['id'] not in linked and OWNER_PLACEHOLDER.search(f['fix'])]
