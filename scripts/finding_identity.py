"""Conservative, deterministic finding identity; no semantic matching."""
import re


def disposition(finding):
    if finding['kind'] in {'unknown', 'hypothesis'} or finding['status'] == 'unknown':
        return 'verification'
    if finding['severity'] == 'informational' or finding['status'] == 'not_applicable':
        return 'context'
    return 'action'


def identity(finding):
    # IDs can be renamed between runs. Wording or scope changes need review;
    # they must never silently turn a dropped finding into a resolved issue.
    claim = re.sub(r'\W+', ' ', finding['claim'].casefold()).strip()
    return finding['category'], claim, tuple(sorted(finding['affected_urls']))


def matches(finding, run):
    return [item for item in run['findings'] if identity(item) == identity(finding)]


def identity_conflict(finding, run):
    return any(item['id'] == finding['id'] and identity(item) != identity(finding)
               for item in run['findings'])
