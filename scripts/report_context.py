"""Load one consistent comparison/action context and bind it to delivery review."""
from pathlib import Path

from actions import digest, load, summary
from compare_runs import compare
from evidence import strict_json
from run_contract import comparable
from safe_io import check_output


def add_arguments(parser):
    parser.add_argument('--compare', type=Path, help='Compatible previous run for the What changed section')
    parser.add_argument('--actions', type=Path, help='Action journal belonging to this run or --compare')


def protect_output(output, *, previous=None, actions=None, overwrite=False):
    if previous is not None:
        check_output(previous, output, overwrite)
    if actions is not None:
        store, target = Path(actions).resolve(), Path(output).resolve()
        if target == store or store in target.parents:
            raise ValueError('Report output cannot replace or write inside an action journal')
        # Also protect hardlinked store files outside the directory.
        for source in Path(actions).rglob('*'):
            if source.is_file():
                check_output(source, output, overwrite)


def prepare(raw, *, previous=None, actions=None):
    data, attachments = {}, {}
    previous_raw = Path(previous).read_bytes() if previous is not None else None
    state = load(actions) if actions is not None else None
    if state:
        expected = digest(previous_raw if previous_raw is not None else raw)
        if state['baseline_sha256'] != expected:
            raise ValueError('Action journal belongs to a different baseline; supply its exact run with --compare')
        current = strict_json(raw.decode('utf-8'))
        compatibility = comparable(current, state['baseline'])
        if not compatibility['comparable']:
            raise ValueError('Action journal scope differs from the current run')
        data['action_tracking'] = summary(state)
        data['action_tracking']['current_run_sha256'] = digest(raw)
        attachments['actions_sha256'] = state['sha256']
    if previous_raw is not None:
        result = compare(raw, previous_raw, action_state=state)
        if not result['comparable']:
            raise ValueError('Incompatible audit comparison: ' + ', '.join(result['differences']))
        data['comparison'] = result
        attachments['previous_run_sha256'] = digest(previous_raw)
    return data, attachments
