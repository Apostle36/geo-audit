"""Guided local audits with immutable configuration and resumable checkpoints.

Start discovers candidate pages. Choose a justified sample, then resume to
collect each page and create run.json. The analyst writes conclusions in that
run. Status reports outstanding work; export defaults to a labelled draft.
"""
import argparse
from contextlib import contextmanager
from datetime import date, datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import sys
from urllib.parse import urlsplit

import browser_collect
import capture_readiness
import collect
from delivery import readiness, validate_approval
from evidence import strict_json, validate_registry
from new_run import skeleton
from run_contract import audit_run, fields, nonempty, web_url
from safe_io import atomic_write, write_new

WORKFLOW_VERSION = '1.1.0'


def dump(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


def read(path):
    return strict_json(Path(path).read_text(encoding='utf-8'))


@contextmanager
def lock(root):
    path = root / '.workflow.lock'
    if path.is_symlink():
        raise ValueError('Refusing a symlink workspace lock')
    with path.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another command is updating this audit; wait for it to finish.') from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def configuration(root):
    config = read(root / 'workflow.json')
    required = {'version', 'url', 'business_type', 'market', 'language', 'date', 'browser', 'allow_private'}
    if isinstance(config, dict) and config.get('version') == WORKFLOW_VERSION:
        required.add('browser_readiness')
    fields(config, required, 'Workflow configuration')
    if config['version'] not in {'1.0.0', WORKFLOW_VERSION}:
        raise ValueError('Unsupported workflow version')
    web_url(config['url'])
    for key in ('business_type', 'market', 'language', 'date'):
        nonempty(config[key], key)
    if date.fromisoformat(config['date']).isoformat() != config['date']:
        raise ValueError('Workflow date must use YYYY-MM-DD')
    if type(config['browser']) is not bool or type(config['allow_private']) is not bool:
        raise ValueError('Browser and private-address options must be booleans')
    if 'browser_readiness' in config:
        fields(config['browser_readiness'], {'selector', 'min_count', 'timeout_ms', 'settle_ms'}, 'Browser readiness')
        capture_readiness.settings(**config['browser_readiness'])
        if not config['browser'] and config['browser_readiness'] != capture_readiness.settings():
            raise ValueError('Browser readiness options require --browser')
    return config


def select_sample(root, urls, rationale):
    config = configuration(root)
    problems = collect.check_urls(urls)
    if problems:
        raise ValueError('; '.join(problems))
    nonempty(rationale, 'sampling rationale')
    hosts = collect.host_twins(config['url'])
    if any((urlsplit(url).hostname or '').lower() not in hosts for url in urls):
        raise ValueError('Workflow sample URLs must belong to the audited host or its www variant')
    if (root / 'run.json').exists():
        raise ValueError('Sample already frozen in run.json; start a new audit to change scope')
    sample_budget(root, urls)
    write_new(root / 'sample.json', dump({'urls': urls, 'rationale': rationale}))


def sample(root):
    path = root / 'sample.json'
    if not path.exists():
        return None
    selection = read(path)
    fields(selection, {'urls', 'rationale'}, 'Sample selection')
    if not isinstance(selection['urls'], list) or any(not isinstance(url, str) for url in selection['urls']):
        raise ValueError('Sample URLs must be a list of strings')
    if collect.check_urls(selection['urls']):
        raise ValueError('; '.join(collect.check_urls(selection['urls'])))
    hosts = collect.host_twins(configuration(root)['url'])
    if any((urlsplit(url).hostname or '').lower() not in hosts for url in selection['urls']):
        raise ValueError('Sample selection contains a URL outside the audited host')
    nonempty(selection['rationale'], 'sampling rationale')
    sample_budget(root, selection['urls'])
    return selection


def sample_budget(root, urls):
    discovery = cached(root, 'discovery')
    navigation = discovery['log']['discovery'].get('navigation', {}) if discovery else {}
    fetched = navigation.get('status') == 'success' or navigation.get('http_status') is not None
    if fetched and navigation.get('seed') not in urls and len(urls) >= collect.MAX_PAGES:
        raise ValueError('Discovery captured the starting page. Include it in the sample or choose at most 49 other pages.')


def attempts(root, name):
    parent = root / 'evidence' / name
    if parent.is_symlink():
        raise ValueError('Refusing a symlink checkpoint directory')
    return sorted(path for path in parent.glob('attempt-*') if re.fullmatch(r'attempt-\d{6}', path.name))


def cached(root, name):
    paths = attempts(root, name)
    if not paths or not (paths[-1] / 'result.json').is_file():
        return None
    result = read(paths[-1] / 'result.json')
    fields(result, {'evidence', 'log'}, 'Checkpoint')
    validate_registry(result['evidence'])
    if not isinstance(result['log'], dict) or result['log'].get('status') not in {'success', 'failed', 'unavailable'}:
        raise ValueError(f'Invalid checkpoint log: {name}')
    if name == 'discovery':
        summary = result['log'].get('discovery')
        if (not isinstance(summary, dict) or not isinstance(summary.get('candidates'), list)
                or any(not isinstance(item, dict) or not isinstance(item.get('loc'), str)
                       for item in summary['candidates'])):
            raise ValueError('Invalid discovery checkpoint; candidate URLs are missing or malformed')
    return result


def checkpoint(root, name, runner, *, retry_failed=False):
    previous = cached(root, name)
    timed_out = previous and previous['log'].get('content_readiness', {}).get('status') == 'timeout'
    if previous and ((previous['log']['status'] == 'success' and not timed_out) or not retry_failed):
        return previous
    previous_paths = attempts(root, name)
    number = int(previous_paths[-1].name.rsplit('-', 1)[1]) + 1 if previous_paths else 1
    output = root / 'evidence' / name / f'attempt-{number:06d}'
    output.parent.mkdir(parents=True, exist_ok=True)
    prefix = f'{name}-a{number}'
    print(f'Collecting {name}, attempt {number}', file=sys.stderr, flush=True)
    result = runner(output, prefix)
    validate_registry(result['evidence'])
    # Browser collection publishes its checkpoint after all artifacts exist.
    if not (output / 'result.json').exists():
        write_new(output / 'result.json', dump(result))
    return result


def collect_discovery(client, config, output, prefix):
    output.mkdir()
    raw = output / 'raw'
    raw.mkdir()
    summary, evidence = collect.discover(client, config['url'], id_prefix=prefix, raw_dir=raw)
    status = 'failed' if summary['robots']['state'] == 'unreachable' else 'success'
    return {'evidence': evidence, 'log': {'status': status, 'discovery': summary}}


def collect_http(client, url, output, prefix):
    output.mkdir()
    raw = output / 'raw'
    raw.mkdir()
    evidence, log = collect.fetch(client, [url], raw, id_prefix=prefix)
    log['status'] = log['pages'][0]['status']
    return {'evidence': evidence, 'log': log}


def collect_http_or_reuse(client, url, output, prefix, discovery, root):
    """Reuse the fallback seed without sending a second HTTP collection request."""
    navigation = discovery['log']['discovery'].get('navigation', {})
    captured = next((item for item in discovery['evidence'] if item['id'] == navigation.get('evidence_id')
                     and item['source'] == url and item['status'] == 'success'), None)
    if not captured or navigation.get('status') != 'success':
        return collect_http(client, url, output, prefix)
    output.mkdir()
    raw_available = navigation.get('raw_bytes_available', False)
    raw_path = navigation.get('raw_path')
    if raw_available:
        if not isinstance(raw_path, str) or not re.fullmatch(r'raw/[0-9a-f]{64}\.bin', raw_path):
            raise ValueError('Invalid raw discovery capture path')
        body = (attempts(root, 'discovery')[-1] / raw_path).read_bytes()
        if hashlib.sha256(body).hexdigest() != navigation.get('body_sha256'):
            raise ValueError('Raw discovery capture hash mismatch')
        (output / 'raw').mkdir()
        write_new(output / raw_path, body)
    evidence = {**captured, 'id': f'{prefix}-01'}
    page = {'id': evidence['id'], 'url': url, 'status': 'success',
            'http_status': navigation['http_status'], 'final_url': navigation['final_url'],
            'flags': navigation.get('flags', []), 'reused_from_navigation': captured['id'],
            'raw_bytes_available': raw_available, 'raw_path': raw_path,
            'notes': ['Reused the saved discovery response; decoded body and headers remain embedded in the evidence.']}
    return {'evidence': [evidence], 'log': {'status': 'success', 'pages': [page],
            'counts': {'success': 1, 'failed': 0, 'unavailable': 0}}}


def sync_run(root, config, selection, records):
    path = root / 'run.json'
    if path.exists():
        original = path.read_bytes()
        run = strict_json(original.decode('utf-8'))
        audit_run(run)
        meta = run['metadata']
        for key in ('url', 'business_type', 'market', 'language', 'date'):
            if meta[key] != config[key]:
                raise ValueError(f'Run metadata diverged from workflow configuration: {key}')
        if meta['sample'] != selection['urls'] or meta['sampling_rationale'] != selection['rationale']:
            raise ValueError('Run sample diverged from the frozen workflow sample')
        registry = {item['id']: item for item in run['assessment']['evidence']}
        changed = False
        for item in records:
            if item['id'] in registry and registry[item['id']] != item:
                raise ValueError(f"Checkpoint differs from embedded evidence: {item['id']}")
            if item['id'] not in registry:
                run['assessment']['evidence'].append(item)
                registry[item['id']] = item
                changed = True
        if changed:
            audit_run(run)
            # Protect the immutable configuration while replacing the derived run.
            atomic_write(root / 'workflow.json', path, dump(run), overwrite=True)
    else:
        run = skeleton(url=config['url'], sample=selection['urls'], business_type=config['business_type'],
                       market=config['market'], language=config['language'], sampling_rationale=selection['rationale'],
                       date=config['date'], evidence=records)
        audit_run(run)
        write_new(path, dump(run))


def resume(root, *, retry_failed=False):
    config = configuration(root)
    selection = sample(root)
    # Read and validate existing analysis before performing any new network work.
    existing_run = (root / 'run.json').exists()
    if existing_run:
        if selection is None:
            raise ValueError('Existing run has no frozen sample selection')
        sync_run(root, config, selection, [])
    client = collect.Client(allow_private=config['allow_private'])
    discovery = checkpoint(root, 'discovery',
                           lambda out, prefix: collect_discovery(client, config, out, prefix),
                           retry_failed=retry_failed)
    if selection is None:
        return status(root)
    sample_budget(root, selection['urls'])
    records = list(discovery['evidence'])
    if existing_run:
        sync_run(root, config, selection, records)
    for index, url in enumerate(selection['urls'], 1):
        http = checkpoint(root, f'http-{index:03d}',
                          lambda out, prefix, url=url: collect_http_or_reuse(client, url, out, prefix, discovery, root),
                          retry_failed=retry_failed)
        records.extend(http['evidence'])
        if existing_run:
            sync_run(root, config, selection, records)
        if config['browser']:
            for viewport in browser_collect.VIEWPORTS:
                rendered = checkpoint(root, f'browser-{index:03d}-{viewport}',
                    lambda out, prefix, url=url, viewport=viewport: browser_collect.capture(
                        client, url, out, identifier=prefix, viewport=viewport,
                        **browser_arguments(config)), retry_failed=retry_failed)
                records.extend(rendered['evidence'])
                if existing_run:
                    sync_run(root, config, selection, records)
    sync_run(root, config, selection, records)
    return status(root)


def browser_arguments(config):
    condition = config.get('browser_readiness', capture_readiness.settings())
    return {'ready_selector': condition['selector'], 'ready_min_count': condition['min_count'],
            'ready_timeout_ms': condition['timeout_ms'], 'settle_ms': condition['settle_ms']}


def status(root, *, approval_path=None):
    config = configuration(root)
    selection = sample(root)
    discovery = cached(root, 'discovery')
    candidates = discovery['log']['discovery']['candidates'] if discovery else []
    result = {'directory': str(root), 'stage': 'collection', 'candidate_count': len(candidates),
              'candidates': [item['loc'] for item in candidates[:20]],
              'browser_requested': config['browser'], 'steps': []}
    names = ['discovery']
    if selection:
        for index in range(1, len(selection['urls']) + 1):
            names.append(f'http-{index:03d}')
            if config['browser']:
                names += [f'browser-{index:03d}-{viewport}' for viewport in browser_collect.VIEWPORTS]
    for name in names:
        completed = cached(root, name)
        step = {'step': name, 'status': completed['log']['status'] if completed else 'pending'}
        if name.startswith('browser-') and completed:
            step['content_readiness'] = completed['log'].get('content_readiness', {'status': 'not_recorded'})
        result['steps'].append(step)
    result['content_readiness'] = {state: sum(step.get('content_readiness', {}).get('status') == state
                                            for step in result['steps'])
                                   for state in ('met', 'unverified', 'timeout', 'not_recorded')}
    result['retryable_steps'] = [step['step'] for step in result['steps'] if step['status'] in {'failed', 'unavailable'}
                                or step.get('content_readiness', {}).get('status') == 'timeout']
    if not discovery and not (root / 'run.json').exists():
        result['next'] = 'Run resume to discover candidate pages.'
    elif selection is None:
        result.update(stage='sample', next='Run sample with --sample URL (repeatable) and --sampling-rationale TEXT.')
    elif not (root / 'run.json').exists():
        result['next'] = 'Run resume to finish collection and create run.json.'
    else:
        raw = (root / 'run.json').read_bytes()
        run = strict_json(raw.decode('utf-8'))
        sync_run(root, config, selection, [])
        registry = {item['id']: item for item in run['assessment']['evidence']}
        unsynced = []
        for name in names:
            completed = cached(root, name)
            if completed and any(registry.get(item['id']) != item for item in completed['evidence']):
                unsynced.append(name)
        result.update(stage='review', delivery=readiness(run), unsynced_steps=unsynced,
                      next='Review evidence and edit run.json; run delivery.py check, then approve when ready.')
        approval = Path(approval_path) if approval_path is not None else root / 'delivery.json'
        if approval.exists():
            try:
                reviewed = read(approval)
                result['approval'] = validate_approval(raw, reviewed)
                result['delivery'] = readiness(strict_json(raw.decode('utf-8')), exclusions=reviewed['exclusions'],
                                               acknowledgements=reviewed['acknowledgements'])
                result.update(stage='ready', next='Export the reviewed report with export --final.')
            except ValueError as exc:
                result['approval'] = {'state': 'stale', 'reason': str(exc)}
        if unsynced or any(step['status'] == 'pending' for step in result['steps']):
            result.update(stage='collection', next='Run resume to finish collection and embed checkpoint evidence.')
        elif result['content_readiness']['timeout']:
            result['next'] = 'Configured content checks timed out. Inspect saved snapshots; use resume --retry-failed to retry.'
    return result


def export(root, output, *, final=False, approval=None, content_lang=None, overwrite=False):
    configuration(root)
    if final and status(root, approval_path=approval)['stage'] != 'ready':
        raise ValueError('Finish collection and approve the current run before exporting a final workflow report')
    spec = importlib.util.spec_from_file_location('geo_report_export', Path(__file__).with_name('geo-audit-pdf.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.export_report(root / 'run.json', output, final=final, approval_path=approval,
                         content_lang=content_lang, overwrite=overwrite)
    return {'saved': str(output), 'state': 'ready' if final else 'draft'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    start = commands.add_parser('start', help='Create a new audit and discover pages')
    start.add_argument('directory', type=Path)
    start.add_argument('--url', required=True)
    for name in ('business-type', 'market', 'language'):
        start.add_argument('--' + name, required=True)
    start.add_argument('--browser', action='store_true', help='Collect desktop/mobile DOM, screenshots and lab timings')
    start.add_argument('--allow-private', action='store_true', help='Explicitly allow a local/staging site')
    start.add_argument('--sample', action='append', default=[])
    start.add_argument('--sampling-rationale')
    capture_readiness.add_arguments(start)
    choose = commands.add_parser('sample', help='Freeze the chosen pages and their rationale')
    choose.add_argument('directory', type=Path)
    choose.add_argument('--sample', action='append', required=True)
    choose.add_argument('--sampling-rationale', required=True)
    continuation = commands.add_parser('resume', help='Reuse completed checkpoints and finish collection')
    continuation.add_argument('directory', type=Path)
    continuation.add_argument('--retry-failed', action='store_true', help='Preserve failed attempts and collect fresh evidence')
    progress = commands.add_parser('status', help='Show collection progress, retryable steps and delivery blockers')
    progress.add_argument('directory', type=Path)
    progress.add_argument('--approval', type=Path, help='Review a named approval instead of delivery.json')
    report = commands.add_parser('export', help='Export a labelled draft or an approved final client report')
    report.add_argument('directory', type=Path)
    report.add_argument('output', type=Path)
    report.add_argument('--final', action='store_true')
    report.add_argument('--approval', type=Path)
    report.add_argument('--content-lang')
    report.add_argument('--overwrite', action='store_true')
    args = parser.parse_args()
    root = args.directory.absolute()
    try:
        if args.command == 'start':
            if bool(args.sample) != bool(args.sampling_rationale):
                raise ValueError('Supply both --sample and --sampling-rationale, or choose pages after discovery')
            web_url(args.url)
            if collect.check_urls([args.url]):
                raise ValueError('; '.join(collect.check_urls([args.url])))
            for value in (args.business_type, args.market, args.language):
                nonempty(value, 'scope')
            condition = capture_readiness.from_arguments(args)
            if not args.browser and condition != capture_readiness.settings():
                raise ValueError('Browser readiness options require --browser')
            # Never initialise inside a nonempty directory or overwrite an old audit.
            if root.exists() and any(root.iterdir()):
                raise ValueError('Start in a new or empty audit directory')
            root.mkdir(parents=True, exist_ok=True)
            with lock(root):
                config = {'version': WORKFLOW_VERSION, 'url': args.url, 'business_type': args.business_type,
                          'market': args.market, 'language': args.language,
                          'date': datetime.now(timezone.utc).date().isoformat(),
                          'browser': args.browser, 'allow_private': args.allow_private, 'browser_readiness': condition}
                write_new(root / 'workflow.json', dump(config))
                if args.sample:
                    select_sample(root, args.sample, args.sampling_rationale)
                result = resume(root)
        else:
            configuration(root)
            with lock(root):
                if args.command == 'sample':
                    select_sample(root, args.sample, args.sampling_rationale)
                    result = status(root)
                    result['next'] = 'Run resume to collect the selected pages.'
                elif args.command == 'resume':
                    result = resume(root, retry_failed=args.retry_failed)
                elif args.command == 'status':
                    result = status(root, approval_path=args.approval)
                else:
                    result = export(root, args.output, final=args.final, approval=args.approval,
                                    content_lang=args.content_lang, overwrite=args.overwrite)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except (ValueError, OSError) as exc:
        parser.exit(2, f'Audit workflow failed: {exc}\n')
    except KeyboardInterrupt:
        print(f'\nAudit interrupted. Completed checkpoints are preserved. Resume with:\n'
              f'  python scripts/audit.py resume {shlex.quote(str(root))}', file=sys.stderr)
        return 130
    return 4 if result.get('content_readiness', {}).get('timeout') else 0


if __name__ == '__main__':
    raise SystemExit(main())
