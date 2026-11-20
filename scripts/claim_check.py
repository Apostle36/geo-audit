"""Independent claim check: every factual sentence is re-read against its cited evidence before export.

  python3 claim_check.py worklist run.json > worklist.json
      Every sentence of each finding's observed and claim fields, with its cited evidence IDs.
  python3 claim_check.py record run.json verdicts.json --reviewer NAME --reviewer-type agent
      Save the checker's verdicts in run.json (claim_check). Every current sentence needs a verdict.
  python3 claim_check.py status run.json
      Coverage and verdict counts; exits 4 while the check is missing, stale or has unsupported sentences.

Verdicts are supported, search_only (supported only by search-result snippets; the sentence must say so)
or unsupported. The checker must not be the agent that wrote the findings. Editing a checked sentence
makes its verdict stale; re-run the check. The tool records verdicts; it does not judge truth itself.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from claims import mentions_search, split_sentences  # noqa: E402
from evidence import strict_json  # noqa: E402

FIELDS = ('observed', 'claim')


def worklist(run):
    """The sentences a checker must judge, in report order."""
    items = []
    for finding in run['findings']:
        for field in FIELDS:
            for sentence in split_sentences(finding[field]):
                items.append({'finding_id': finding['id'], 'field': field, 'text': sentence,
                              'evidence_ids': list(finding['evidence_ids'])})
    return items


def key(item):
    return item['finding_id'], item['field'], item['text']


def status(run):
    expected = {key(item) for item in worklist(run)}
    check = run.get('claim_check')
    if not check:
        return {'present': False, 'complete': False, 'missing': sorted(expected), 'stale': [], 'unsupported': [],
                'undisclosed': [], 'counts': {}}
    recorded = {key(item): item for item in check['sentences']}
    current = [recorded[k] for k in recorded if k in expected]
    result = {'present': True, 'reviewer': check['reviewer'], 'reviewer_type': check['reviewer_type'],
              'checked_at': check['checked_at'],
              'missing': sorted(expected - recorded.keys()), 'stale': sorted(recorded.keys() - expected),
              'unsupported': [key(i) for i in current if i['verdict'] == 'unsupported'],
              'undisclosed': [key(i) for i in current if i['verdict'] == 'search_only' and not mentions_search(i['text'])],
              'counts': {verdict: sum(i['verdict'] == verdict for i in current)
                         for verdict in ('supported', 'search_only', 'unsupported')}}
    result['complete'] = not result['missing'] and not result['stale']
    return result


def blockers(run):
    """Delivery blockers from the claim check; unsupported sentences also block every client export."""
    result = status(run)
    problems = export_blockers(result)
    if not result['present']:
        problems.append('Run the independent claim check (claim_check.py) before final delivery.')
    elif not result['complete']:
        problems.append(f"The claim check is stale: {len(result['missing'])} current sentence(s) are unchecked and "
                        f"{len(result['stale'])} checked sentence(s) no longer exist. Re-run the claim check.")
    return problems


def export_blockers(result):
    problems = []
    if result['unsupported']:
        problems.append(f"{len(result['unsupported'])} sentence(s) are unsupported by their cited evidence; fix or remove "
                        'them and re-run the claim check: '
                        + '; '.join(f'{fid}.{field}: {text[:80]}' for fid, field, text in result['unsupported'][:5]))
    if result['undisclosed']:
        problems.append(f"{len(result['undisclosed'])} sentence(s) rest only on search results but do not say so: "
                        + '; '.join(f'{fid}.{field}: {text[:80]}' for fid, field, text in result['undisclosed'][:5]))
    return problems


def record(run, verdicts, *, reviewer, reviewer_type, checked_at=None):
    expected = {key(item): item for item in worklist(run)}
    sentences = []
    for item in verdicts:
        if not isinstance(item, dict) or key(item) not in expected:
            raise ValueError(f'Verdict does not match a current sentence: {item!r}'[:200])
        sentences.append({'finding_id': item['finding_id'], 'field': item['field'], 'text': item['text'],
                          'evidence_ids': list(item.get('evidence_ids', expected[key(item)]['evidence_ids'])),
                          'verdict': item['verdict'], 'note': item.get('note', '')})
    if len({key(s) for s in sentences}) != len(sentences):
        raise ValueError('Each sentence needs exactly one verdict')
    missing = expected.keys() - {key(s) for s in sentences}
    if missing:
        raise ValueError(f'{len(missing)} sentence(s) have no verdict; the check must cover every sentence')
    updated = dict(run, claim_check={'reviewer': reviewer, 'reviewer_type': reviewer_type,
                                     'checked_at': checked_at or datetime.now(timezone.utc).isoformat(timespec='seconds'),
                                     'sentences': sentences})
    return updated


def main():
    from run_contract import audit_run
    from safe_io import atomic_write
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('worklist', 'status'):
        commands.add_parser(name).add_argument('run', type=Path)
    save = commands.add_parser('record')
    save.add_argument('run', type=Path)
    save.add_argument('verdicts', type=Path)
    save.add_argument('--reviewer', required=True)
    save.add_argument('--reviewer-type', required=True, choices=('agent', 'human'))
    args = parser.parse_args()
    try:
        run = strict_json(args.run.read_text(encoding='utf-8'))
        if run.get('schema_version') != '1.5.0':
            raise ValueError('The claim check is stored in run schema 1.5.0 runs')
        audit_run(run)
        if args.command == 'worklist':
            print(json.dumps(worklist(run), indent=2, ensure_ascii=False))
            return 0
        if args.command == 'record':
            verdicts = strict_json(args.verdicts.read_text(encoding='utf-8'))
            run = record(run, verdicts, reviewer=args.reviewer, reviewer_type=args.reviewer_type)
            audit_run(run)
            atomic_write(args.verdicts, args.run, (json.dumps(run, ensure_ascii=False, indent=2) + '\n').encode(),
                         overwrite=True)
        result = status(run)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result['complete'] and not export_blockers(result) else 4
    except (ValueError, OSError) as exc:
        parser.exit(2, f'Claim check failed: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
