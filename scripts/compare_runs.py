"""Compare compatible snapshots without treating missing findings as fixed."""
import argparse
import json
from pathlib import Path

from actions import digest, load
from capture_readiness import latest_browser_observations
from evidence import strict_json
from finding_identity import disposition, identity, identity_conflict
from run_contract import audit_run, comparable
from safe_io import check_output, write_new


def compare(current_raw, previous_raw, *, action_state=None):
    current, previous = (strict_json(raw.decode('utf-8')) for raw in (current_raw, previous_raw))
    scores, _ = audit_run(current)
    old_scores, _ = audit_run(previous)
    result = comparable(current, previous)
    if current['metadata']['date'] < previous['metadata']['date']:
        result['differences'].append('date_order')
        result['comparable'] = False
    if action_state is not None and action_state['baseline_sha256'] != digest(previous_raw):
        raise ValueError('Action store must belong to the exact previous run')
    if not result['comparable']:
        return result
    groups = {name: [] for name in ('new', 'recurring', 'resolved', 'unresolved')}
    before = [f for f in previous['findings'] if disposition(f) != 'context']
    after = [f for f in current['findings'] if disposition(f) != 'context']
    tasks = action_state['tasks'] if action_state else {}

    def row(finding, reason, proof=None):
        return {'finding': finding, 'reason': reason, 'verification': proof}

    for finding in before:
        same = [f for f in after if identity(f) == identity(finding)]
        conflict = identity_conflict(finding, current)
        duplicate = sum(identity(f) == identity(finding) for f in before) > 1
        if same and len(same) == 1 and not conflict and not duplicate and disposition(finding) == disposition(same[0]) == 'action':
            groups['recurring'].append(row(same[0], 'The same supported issue remains in the follow-up.'))
            continue
        task = tasks.get(finding['id'])
        proof = task['verification'] if task and task['status'] == 'verified' else None
        if (not same and not conflict and not duplicate and proof and proof['result'] == 'passed'
                and proof['run_sha256'] == digest(current_raw)):
            groups['resolved'].append(row(finding, 'Fresh evidence passed the recorded acceptance review.', proof))
        else:
            reason = ('Finding identity changed or is ambiguous; reconcile the wording and scope.' if conflict or duplicate or len(same) > 1
                      else 'The finding still needs assessment.' if same
                      else 'Absent from this run; no passing review bound to this exact snapshot.')
            groups['unresolved'].append(row(finding, reason))
    for finding in after:
        if any(identity(f) == identity(finding) or f['id'] == finding['id'] for f in before):
            continue
        conflict = identity_conflict(finding, previous)
        group = 'new' if disposition(finding) == 'action' and not conflict else 'unresolved'
        groups[group].append(row(finding, 'New supported issue in the follow-up.' if group == 'new'
                                 else 'New uncertainty or changed identity requires review.'))

    def delta(before, after):
        return {'previous': before, 'current': after,
                'change': after - before if before is not None and after is not None else None}

    def coverage(run):
        return {status: sum(item['status'] == status for item in run.get('review', []))
                for status in ('assessed', 'unknown', 'not_applicable')}

    def conditions(run):
        result = {}
        for observation in latest_browser_observations(run):
            value = observation['measurements'].get('content_readiness')
            condition = value if isinstance(value, dict) else {}
            result[(observation['url'], observation['viewport'])] = {
                key: condition.get(key) for key in ('selector', 'min_count', 'timeout_ms', 'settle_ms', 'status')}
        return result

    old_conditions, new_conditions = conditions(previous), conditions(current)
    capture_conditions = [{'url': url, 'viewport': viewport,
                           'previous': old_conditions.get((url, viewport)),
                           'current': new_conditions.get((url, viewport))}
                          for url, viewport in sorted(set(old_conditions) | set(new_conditions))]

    result.update(previous_date=previous['metadata']['date'], current_date=current['metadata']['date'],
                  counts={key: len(rows) for key, rows in groups.items()}, groups=groups,
                  scores={'overall': delta(old_scores['overall'], scores['overall']),
                          'categories': {key: delta(old_scores['categories'][key]['score'], scores['categories'][key]['score'])
                                         for key in scores['categories']}},
                  coverage={'previous': coverage(previous), 'current': coverage(current)},
                  capture_conditions=capture_conditions,
                  matching='Exact category, normalised claim and page set. Wording changes require review.',
                  verification_limit='Passing reviews are named local attestations, not independent identity verification. '
                  'Check capture conditions and review scope before interpreting change.')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('previous', type=Path)
    parser.add_argument('current', type=Path)
    parser.add_argument('--actions', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        state = load(args.actions) if args.actions else None
        result = compare(args.current.read_bytes(), args.previous.read_bytes(), action_state=state)
        raw = (json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode()
        if args.output:
            from report_context import protect_output
            protect_output(args.output, previous=args.previous, actions=args.actions)
            check_output(args.current, args.output)
            write_new(args.output, raw)
        print(raw.decode(), end='')
        return 0 if result['comparable'] else 3
    except (ValueError, OSError) as exc:
        parser.exit(2, f'Comparison failed: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
