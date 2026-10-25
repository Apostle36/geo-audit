"""Local action journal with frozen acceptance checks and evidence-based review.

Completion queues verification. Only a separate named review with fresh captures
can mark an action verified. Local records provide integrity, not authentication.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import math
from pathlib import Path
import re

from evidence import parse_timestamp, strict_json, resolve_ids
from finding_identity import disposition, matches, identity_conflict
from run_contract import audit_run, comparable, fields
from safe_io import write_new

VERSION = '1.0.0'
STATUSES = {'planned', 'in_progress', 'ready_to_verify', 'verified'}
HASH = re.compile(r'[0-9a-f]{64}')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def dump(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label} must be nonempty text')


def read(path):
    if path.is_symlink():
        raise ValueError(f'Journal files cannot be symlinks: {path}')
    return path.read_bytes()


@contextmanager
def lock(root, *, exclusive=False):
    root = Path(root)
    if root.is_symlink() or not root.is_dir() or (root / '.lock').is_symlink():
        raise ValueError('Use a real action store with a regular lock file')
    with (root / '.lock').open('rb') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield


def validate_dependencies(tasks):
    visiting, visited = set(), set()

    def visit(identifier):
        if identifier in visiting:
            raise ValueError('Action dependencies contain a cycle')
        if identifier in visited:
            return
        visiting.add(identifier)
        task = tasks[identifier]
        deps = task['depends_on']
        if (not isinstance(deps, list) or any(not isinstance(dep, str) or dep not in tasks for dep in deps)
                or len(set(deps)) != len(deps)):
            raise ValueError('Dependencies must be unique existing action IDs')
        for dep in deps:
            visit(dep)
        if task['status'] != 'planned' and any(tasks[dep]['status'] != 'verified' for dep in deps):
            raise ValueError('Active actions require verified dependencies; reopen dependents first')
        visiting.remove(identifier)
        visited.add(identifier)

    for identifier in tasks:
        visit(identifier)


def validate_review(baseline, task, current_raw, payload, at):
    fields(payload, {'run_sha256', 'evidence_ids', 'result', 'reviewer', 'reviewer_type', 'rationale'}, 'Action review')
    if payload['run_sha256'] != digest(current_raw) or digest(current_raw) == digest(dump(baseline)):
        raise ValueError('Review must reference the exact follow-up snapshot')
    current = strict_json(current_raw.decode('utf-8'))
    audit_run(current)
    compatibility = comparable(current, baseline)
    if not compatibility['comparable']:
        raise ValueError('Incompatible follow-up scope: ' + ', '.join(compatibility['differences']))
    if task['status'] != 'ready_to_verify':
        raise ValueError('Mark the action ready_to_verify before reviewing fresh evidence')
    if not isinstance(payload['result'], str) or payload['result'] not in {'passed', 'failed', 'inconclusive'}:
        raise ValueError('Review result must be passed, failed or inconclusive')
    if not isinstance(payload['reviewer_type'], str) or payload['reviewer_type'] not in {'human', 'agent'}:
        raise ValueError('Declare reviewer_type as human or agent')
    text(payload['reviewer'], 'Reviewer')
    text(payload['rationale'], 'Review rationale')
    registry = {record['id']: record for record in current['assessment']['evidence']}
    records = resolve_ids(payload['evidence_ids'], registry, require_success=payload['result'] != 'inconclusive')
    selected = {record['source'] for record in records}
    if not set(task['finding']['affected_urls']).issubset(selected):
        raise ValueError('Review needs evidence for every affected URL')
    ready = parse_timestamp(task['ready_at'])
    baseline_records = baseline['assessment']['evidence']
    for record in records:
        collected = parse_timestamp(record['collected_at'])
        older = [parse_timestamp(old['collected_at']) for old in baseline_records if old['source'] == record['source']]
        if collected < ready or (older and collected <= max(older)) or collected > at + timedelta(minutes=5):
            raise ValueError('Review evidence must be fresh: after baseline captures and after ready_to_verify')
    if payload['result'] == 'passed' and (identity_conflict(task['finding'], current)
                                         or any(disposition(f) != 'context' for f in matches(task['finding'], current))):
        raise ValueError('Follow-up still contains the issue or an identity conflict; it cannot pass')
    return current


def apply_event(tasks, event, baseline, snapshot):
    identifier = event['action_id']
    if not isinstance(identifier, str) or identifier not in tasks:
        raise ValueError('Unknown action ID')
    task, payload = tasks[identifier], event['payload']
    at = parse_timestamp(event['at'])
    if event['kind'] == 'update':
        if not isinstance(payload, dict) or not payload or set(payload) - {'owner', 'effort_hours', 'depends_on', 'status'}:
            raise ValueError('Invalid action update fields')
        if 'owner' in payload and payload['owner'] is not None:
            text(payload['owner'], 'Owner')
        effort = payload.get('effort_hours')
        if effort is not None and (type(effort) not in (int, float) or not math.isfinite(effort) or effort <= 0):
            raise ValueError('Effort must be positive finite hours or null')
        if 'status' in payload and (not isinstance(payload['status'], str) or payload['status'] not in STATUSES - {'verified'}):
            raise ValueError('Use a separate evidence review to mark an action verified')
        if task['status'] == 'verified' and 'depends_on' in payload:
            raise ValueError('Reopen a verified action before changing dependencies')
        old_status = task['status']
        task.update(payload)
        if 'status' in payload:
            if task['status'] == 'ready_to_verify' and old_status != 'ready_to_verify':
                task['ready_at'] = event['at']
            elif task['status'] != 'ready_to_verify':
                task['ready_at'] = None
            task['verification'] = None
    elif event['kind'] == 'review':
        if not isinstance(payload, dict) or not HASH.fullmatch(str(payload.get('run_sha256', ''))):
            raise ValueError('Invalid review snapshot hash')
        current_raw = snapshot(payload['run_sha256'])
        validate_review(baseline, task, current_raw, payload, at)
        task['verification'] = {**payload, 'reviewed_at': event['at']}
        task['status'] = {'passed': 'verified', 'failed': 'in_progress', 'inconclusive': 'ready_to_verify'}[payload['result']]
        if task['status'] != 'ready_to_verify':
            task['ready_at'] = None
    else:
        raise ValueError('Unknown action event kind')
    validate_dependencies(tasks)


def _load(root):
    root = Path(root)
    manifest_raw = read(root / 'manifest.json')
    manifest = strict_json(manifest_raw.decode('utf-8'))
    fields(manifest, {'version', 'baseline_sha256', 'created_at'}, 'Action manifest')
    if manifest['version'] != VERSION:
        raise ValueError('Unsupported action store version')
    baseline_raw = read(root / 'baseline.json')
    if digest(baseline_raw) != manifest['baseline_sha256']:
        raise ValueError('Action baseline hash mismatch')
    baseline = strict_json(baseline_raw.decode('utf-8'))
    audit_run(baseline)
    tasks = {f['id']: {'id': f['id'], 'finding': f, 'owner': None, 'effort_hours': None,
                       'depends_on': [], 'status': 'planned', 'ready_at': None, 'verification': None}
             for f in baseline['findings'] if disposition(f) == 'action'}
    previous = digest(manifest_raw)
    at = parse_timestamp(manifest['created_at'])
    if at > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ValueError('Action creation time cannot be in the future')
    if (root / 'events').is_symlink() or (root / 'runs').is_symlink():
        raise ValueError('Action store directories cannot be symlinks')
    paths = sorted((root / 'events').iterdir())

    def snapshot(sha):
        raw = read(root / 'runs' / (sha + '.json'))
        if digest(raw) != sha or sha == manifest['baseline_sha256']:
            raise ValueError('Follow-up snapshot hash mismatch or reused baseline')
        return raw

    for index, path in enumerate(paths, 1):
        if path.name != f'{index:06d}.json':
            raise ValueError('Action event sequence is not contiguous')
        raw = read(path)
        event = strict_json(raw.decode('utf-8'))
        fields(event, {'sequence', 'previous_sha256', 'at', 'action_id', 'kind', 'payload'}, 'Action event')
        if type(event['sequence']) is not int or event['sequence'] != index or event['previous_sha256'] != previous:
            raise ValueError('Action event chain mismatch')
        event_at = parse_timestamp(event['at'])
        if event_at < at or event_at > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError('Action event times must be ordered and not in the future')
        apply_event(tasks, event, baseline, snapshot)
        at, previous = event_at, digest(raw)
    # Snapshot hashes are transitively covered by validated events.
    fingerprint = digest(dump([manifest['baseline_sha256'], digest(manifest_raw), previous, len(paths)]))
    return {'baseline': baseline, 'baseline_sha256': manifest['baseline_sha256'], 'tasks': tasks,
            'sha256': fingerprint, 'event_count': len(paths), 'head_sha256': previous,
            'last_event_at': at.isoformat()}


def load(root):
    with lock(root):
        return _load(root)


def initialise(raw, root):
    baseline = strict_json(raw.decode('utf-8'))
    audit_run(baseline)
    root = Path(root)
    root.mkdir()  # Existing histories are never replaced, including empty stores.
    write_new(root / '.lock', b'')
    with lock(root, exclusive=True):
        (root / 'events').mkdir()
        (root / 'runs').mkdir()
        write_new(root / 'baseline.json', raw)
        write_new(root / 'manifest.json', dump({'version': VERSION, 'baseline_sha256': digest(raw), 'created_at': now()}))
        return _load(root)


def append(root, identifier, kind, payload, *, current_raw=None):
    root = Path(root)
    with lock(root, exclusive=True):
        state = _load(root)
        event = {'sequence': state['event_count'] + 1, 'previous_sha256': state['head_sha256'],
                 'at': now(), 'action_id': identifier, 'kind': kind, 'payload': payload}
        if parse_timestamp(event['at']) < parse_timestamp(state['last_event_at']):
            raise ValueError('Clock moved backwards; wait until the last event time before updating')
        if kind == 'review' and current_raw is None:
            raise ValueError('Review requires a follow-up run')
        if current_raw is not None and digest(current_raw) == state['baseline_sha256']:
            raise ValueError('Review needs a different follow-up run, not the baseline')
        apply_event(state['tasks'], event, state['baseline'], lambda _sha: current_raw)
        if kind == 'review':
            path = root / 'runs' / (digest(current_raw) + '.json')
            if path.exists():
                if read(path) != current_raw:
                    raise ValueError('Follow-up snapshot changed')
            else:
                write_new(path, current_raw)
        write_new(root / 'events' / f"{event['sequence']:06d}.json", dump(event))
        return _load(root)


def update(root, identifier, **changes):
    return append(root, identifier, 'update', changes)


def review(root, identifier, current_raw, *, evidence_ids, result, reviewer, reviewer_type, rationale):
    return append(root, identifier, 'review', {'run_sha256': digest(current_raw), 'evidence_ids': evidence_ids,
                  'result': result, 'reviewer': reviewer, 'reviewer_type': reviewer_type, 'rationale': rationale},
                  current_raw=current_raw)


def summary(state):
    return {key: value for key, value in state.items() if key not in {'baseline', 'head_sha256'}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init', help='Freeze improvement actions from a validated run')
    init.add_argument('run', type=Path)
    init.add_argument('--store', type=Path)
    show = commands.add_parser('status', help='Read the validated journal without changing it')
    show.add_argument('store', type=Path)
    change = commands.add_parser('update', help='Assign, scope or queue verification; no direct verified status')
    change.add_argument('store', type=Path)
    change.add_argument('action')
    change.add_argument('--owner')
    change.add_argument('--effort-hours', type=float)
    change.add_argument('--depends-on', action='append', help='Replace dependencies (repeatable)')
    change.add_argument('--clear-dependencies', action='store_true')
    change.add_argument('--status', choices=sorted(STATUSES - {'verified'}))
    check = commands.add_parser('review', help='Record a named human or agent review of fresh evidence')
    check.add_argument('store', type=Path)
    check.add_argument('action')
    check.add_argument('--run', type=Path, required=True)
    check.add_argument('--evidence', action='append', required=True)
    check.add_argument('--result', choices=['passed', 'failed', 'inconclusive'], required=True)
    check.add_argument('--reviewer', required=True)
    check.add_argument('--reviewer-type', choices=['human', 'agent'], required=True)
    check.add_argument('--rationale', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'init':
            state = initialise(args.run.read_bytes(), args.store or args.run.with_name('actions'))
        elif args.command == 'status':
            state = load(args.store)
        elif args.command == 'update':
            changes = {key: getattr(args, key) for key in ('owner', 'effort_hours', 'depends_on', 'status')
                       if getattr(args, key) is not None}
            if args.clear_dependencies:
                if args.depends_on:
                    raise ValueError('Choose --depends-on or --clear-dependencies')
                changes['depends_on'] = []
            state = update(args.store, args.action, **changes)
        else:
            state = review(args.store, args.action, args.run.read_bytes(), evidence_ids=args.evidence,
                           result=args.result, reviewer=args.reviewer, reviewer_type=args.reviewer_type,
                           rationale=args.rationale)
        print(json.dumps(summary(state), ensure_ascii=False, indent=2))
    except (ValueError, OSError) as exc:
        parser.exit(2, f'Action tracking failed: {exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
