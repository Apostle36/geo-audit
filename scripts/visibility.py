"""Buyer question set for measuring AI visibility later; this tool never queries an AI platform.

  python3 visibility.py draft --service "B2B websites" --customer "industrial manufacturers" \\
      --market "EU" --brand "Example Studio" > visibility.json
      Expand the analyst's services, customer types and market into 15-20 draft questions.
  python3 visibility.py record run.json visibility.json
      Validate the edited plan (and any observations) and save it as run.json's visibility field.

Edit the draft before recording it: the questions should be ones real buyers ask. Observations are
added later, one per platform answer, each citing a saved evidence record (off_site or owner_statement).
They are reported as observations, never as a score.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evidence import strict_json  # noqa: E402

PLATFORMS = ('ChatGPT', 'Perplexity', 'Gemini', 'Google AI Mode', 'Copilot')
UNBRANDED = (
    'Who are the best {service} providers for {customer} in {market}?',
    'How do I choose a {service} partner for {customer}?',
    'What does {service} typically cost for {customer}?',
    'What should {customer} look for in a {service} provider?',
    'Which {service} firms in {market} have case studies with {customer}?',
    'What are common mistakes {customer} make with {service}?',
    'How long does a {service} project usually take for {customer}?',
    'Should {customer} hire an agency or a freelancer for {service}?',
    'What questions should {customer} ask before hiring a {service} provider?',
)
BRANDED = (
    'What does {brand} do?',
    'Is {brand} a good choice for {service}?',
    'Who are {brand}\'s clients?',
    'What do clients say about {brand}?',
    'How does {brand} compare with other {service} providers in {market}?',
    'Where is {brand} based and who runs it?',
)


def draft_questions(services, customers, market, brand=None, *, limit=20):
    """Deterministic expansion of analyst inputs; the analyst edits the result before saving it."""
    if not services or not customers or not market:
        raise ValueError('Supply at least one service, one customer type and the market')
    questions = []
    combos = [(s, c) for c in customers for s in services]
    for template in UNBRANDED:
        for service, customer in combos:
            questions.append(template.format(service=service, customer=customer, market=market))
    if brand:
        branded = [t.format(brand=brand, service=services[0], market=market) for t in BRANDED]
        questions = questions[:limit - len(branded)] + branded
    unique = list(dict.fromkeys(questions))[:limit]
    if len(unique) < 15:
        raise ValueError('These inputs produce fewer than 15 questions; add a service, a customer type or a brand')
    return unique


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    draft = commands.add_parser('draft')
    draft.add_argument('--service', action='append', required=True)
    draft.add_argument('--customer', action='append', required=True)
    draft.add_argument('--market', required=True)
    draft.add_argument('--brand')
    save = commands.add_parser('record')
    save.add_argument('run', type=Path)
    save.add_argument('plan', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'draft':
            plan = {'inputs': {'services': args.service, 'customer_types': args.customer, 'market': args.market},
                    'questions': draft_questions(args.service, args.customer, args.market, args.brand),
                    'observations': []}
            print(json.dumps(plan, indent=2, ensure_ascii=False))
            return 0
        from run_contract import audit_run
        from safe_io import atomic_write
        run = strict_json(args.run.read_text(encoding='utf-8'))
        if run.get('schema_version') != '1.5.0':
            raise ValueError('The visibility plan is stored in run schema 1.5.0 runs')
        run['visibility'] = strict_json(args.plan.read_text(encoding='utf-8'))
        audit_run(run)
        atomic_write(args.plan, args.run, (json.dumps(run, ensure_ascii=False, indent=2) + '\n').encode(), overwrite=True)
        print(json.dumps({'saved': str(args.run), 'questions': len(run['visibility']['questions']),
                          'observations': len(run['visibility']['observations'])}, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        parser.exit(2, f'Visibility plan failed: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
