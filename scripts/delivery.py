"""Check delivery readiness and record a local review of an exact run snapshot.

An approval is an integrity record, not authentication or proof that claims are
true. Editing run.json invalidates it. Draft exports never need an approval.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re

from evidence import parse_timestamp, strict_json
from review_topics import TOPICS
from run_contract import PLACEHOLDER, audit_run, fields, run_text
from safe_io import write_new

APPROVAL_VERSION = '1.0.0'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def check_keys(scores):
    core = {f"core.{item['category']}.{item['id']}" for item in scores['criteria']}
    review = {f'review.{category}.{topic}' for category, topics in TOPICS.items() for topic in topics}
    return core | review


def reasons(value, allowed, label):
    if not isinstance(value, dict):
        raise ValueError(f'{label} must map check names to reasons')
    for key, reason in value.items():
        if key not in allowed or not isinstance(reason, str) or not reason.strip() or PLACEHOLDER in reason:
            raise ValueError(f'Invalid {label}: {key!r}; use a known check and a specific reason')


def readiness(run, *, exclusions=None, acknowledgements=None):
    """Separate a structurally valid draft from a reviewable delivery scope."""
    scores, warnings = audit_run(run)
    exclusions = {} if exclusions is None else exclusions
    acknowledgements = {} if acknowledgements is None else acknowledgements
    reasons(exclusions, check_keys(scores), 'scope exclusion')
    reasons(acknowledgements, set(warnings), 'warning acknowledgement')
    blockers = []
    if any(PLACEHOLDER in text for text in run_text(run)):
        blockers.append('Replace every skeleton placeholder before delivery.')
    for warning in warnings:
        if 'skeleton placeholder' not in warning and warning not in acknowledgements:
            blockers.append(f'Resolve or acknowledge warning: {warning}')
    completed = 0
    for criterion in scores['criteria']:
        key = f"core.{criterion['category']}.{criterion['id']}"
        if key in exclusions:
            continue
        if criterion['status'] == 'unknown':
            blockers.append(f'Unfinished check: {key}')
        elif criterion['status'] == 'assessed':
            completed += 1
    recorded = {(item['category'], item['topic']): item for item in run.get('review', [])}
    sample = set(run['metadata']['sample'])
    for category, topics in TOPICS.items():
        for topic in topics:
            key = f'review.{category}.{topic}'
            if key in exclusions:
                continue
            item = recorded.get((category, topic))
            if item is None or item['status'] == 'unknown':
                blockers.append(f'Unfinished check: {key}')
            elif set(item['affected_urls']) != sample:
                blockers.append(f'Check covers only part of the sample: {key}; finish it or exclude it explicitly.')
            elif item['status'] == 'assessed':
                completed += 1
    if not completed:
        blockers.append('At least one assessed check must remain within the delivery scope.')
    return {'reviewable': not blockers, 'blockers': blockers, 'warnings': warnings,
            'exclusions': exclusions, 'acknowledgements': acknowledgements}


def validate_approval(raw, approval, *, attachments=None):
    contextual = isinstance(approval, dict) and approval.get('version') == '1.1.0'
    required = {'version', 'run_sha256', 'reviewer', 'reviewed_at', 'exclusions', 'acknowledgements'}
    fields(approval, required | ({'attachments'} if contextual else set()), 'Approval')
    if not isinstance(approval['version'], str) or approval['version'] not in {APPROVAL_VERSION, '1.1.0'}:
        raise ValueError('Unsupported approval version')
    attachments = attachments or {}
    if attachments != approval.get('attachments', {}):
        raise ValueError('Report attachments changed after review; review the complete report context again.')
    if (not isinstance(attachments, dict) or set(attachments) - {'previous_run_sha256', 'actions_sha256'}
            or any(not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value)
                   for value in attachments.values())):
        raise ValueError('Invalid report attachment hashes')
    if approval['run_sha256'] != digest(raw):
        raise ValueError('The run changed after review; review this snapshot again.')
    if not isinstance(approval['reviewer'], str) or not approval['reviewer'].strip():
        raise ValueError('Approval needs a named reviewer')
    if parse_timestamp(approval['reviewed_at']) > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ValueError('Review time is in the future')
    result = readiness(strict_json(raw.decode('utf-8')), exclusions=approval['exclusions'],
                       acknowledgements=approval['acknowledgements'])
    if not result['reviewable']:
        raise ValueError('Run is not ready for delivery: ' + '; '.join(result['blockers']))
    return {'state': 'ready', 'reviewer': approval['reviewer'], 'reviewed_at': approval['reviewed_at'],
            'exclusions': approval['exclusions'], 'acknowledgements': approval['acknowledgements']}


def approve(raw, reviewer, *, exclusions=None, acknowledgements=None, attachments=None):
    approval = {'version': '1.1.0' if attachments else APPROVAL_VERSION, 'run_sha256': digest(raw), 'reviewer': reviewer,
                'reviewed_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                'exclusions': exclusions or {}, 'acknowledgements': acknowledgements or {}}
    if attachments:
        approval['attachments'] = attachments
    validate_approval(raw, approval, attachments=attachments)
    return approval


def assignments(values):
    result = {}
    for value in values:
        key, separator, reason = value.partition('=')
        if not separator or not key.strip() or not reason.strip() or key.strip() in result:
            raise ValueError('Use a unique CHECK=reason (or exact WARNING=reason) for each entry')
        result[key.strip()] = reason.strip()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    check = commands.add_parser('check', help='List delivery blockers without changing the run')
    check.add_argument('run', type=Path)
    check.add_argument('--approval', type=Path)
    review = commands.add_parser('approve', help='Attest that you reviewed the findings, evidence and declared scope')
    review.add_argument('run', type=Path)
    review.add_argument('--reviewer', required=True)
    review.add_argument('--output', type=Path, help='Default: delivery.json beside the run; existing approvals are preserved')
    review.add_argument('--exclude', action='append', default=[], metavar='CHECK=reason')
    review.add_argument('--acknowledge', action='append', default=[], metavar='WARNING=reason')
    from report_context import add_arguments, prepare, protect_output
    for command in (check, review):
        add_arguments(command)
    args = parser.parse_args()
    try:
        raw = args.run.read_bytes()
        _, attachments = prepare(raw, previous=args.compare, actions=args.actions)
        if args.command == 'approve':
            approval = approve(raw, args.reviewer, exclusions=assignments(args.exclude),
                               acknowledgements=assignments(args.acknowledge), attachments=attachments)
            output = args.output or args.run.with_name('delivery.json')
            from safe_io import check_output
            check_output(args.run, output)
            protect_output(output, previous=args.compare, actions=args.actions)
            write_new(output, (json.dumps(approval, indent=2, ensure_ascii=False) + '\n').encode())
            print(json.dumps({'state': 'ready', 'approval': str(output)}, indent=2))
        elif args.approval:
            print(json.dumps(validate_approval(raw, strict_json(args.approval.read_text(encoding='utf-8')),
                                              attachments=attachments), indent=2))
        else:
            result = readiness(strict_json(raw.decode('utf-8')))
            print(json.dumps({'state': 'draft', **result}, indent=2))
            return 0 if result['reviewable'] else 4
    except (ValueError, OSError) as exc:
        parser.exit(2, f'Delivery check failed: {exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
