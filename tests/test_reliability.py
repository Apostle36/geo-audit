import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

pdf = module("pdf", "geo-audit-pdf.py")
evidence = module("evidence", "evidence.py")
scoring = module("scoring", "score.py")


class Reliability(unittest.TestCase):
    def test_decimal_score(self):
        self.assertEqual(pdf.parse_report("**Overall GEO Score: 72.5/100**")["overall_score"], 72.5)

    def test_invalid_scores(self):
        for text in ("No score", "**Overall GEO Score: 999/100**"):
            with self.assertRaises(ValueError):
                pdf.parse_report(text)

    def test_unassessed(self):
        self.assertIsNone(pdf.parse_report("**Overall GEO Score: Not assessed**")["overall_score"])

    def test_fenced_heading(self):
        data = pdf.parse_report("**Overall GEO Score: 50/100**\n## Findings\n```markdown\n## Example\n```")
        self.assertEqual(len(data["sections"]), 1)
        self.assertIn("## Example", data["sections"][0]["content"])

    def test_unsafe_links(self):
        self.assertNotIn('href="javascript:', pdf.inline_md("[x](javascript:alert)"))
        from html.parser import HTMLParser
        attributes = []
        class Links(HTMLParser):
            def handle_starttag(self, tag, attrs):
                attributes.extend(key for key, value in attrs)
        Links().feed(pdf.inline_md('[x](https://example.com/" onmouseover="alert)'))
        self.assertNotIn("onmouseover", attributes)

    def test_metadata_escaped(self):
        data = pdf.parse_report('**URL:** <script>alert(1)</script>\n**Overall GEO Score: 50/100**')
        self.assertNotIn("<script>alert", pdf.generate_html(data))

    def test_schema_arrays_graph_whitespace(self):
        text = '<script type="application/ld+json">[{"@type": "Organization"}]</script><script type="application/ld+json">{"@graph":[{"@type":["WebSite","Thing"]},{"@id":"#org"}]}</script>'
        result = evidence.extract(text)
        self.assertEqual(len(result["jsonld"]), 2)
        self.assertEqual(result["jsonld"][1]["types"], ["Thing", "WebSite"])
        self.assertFalse(result["errors"])

    def test_malformed_schema(self):
        result = evidence.extract('<script type="application/ld+json">{broken}</script>')
        self.assertEqual(len(result["jsonld"]), 1)
        self.assertTrue(result["errors"])

    def test_score_missing(self):
        self.assertIsNone(scoring.calculate({})["overall"])

    def test_weighted_score(self):
        data = {key: [{"id":"a","status":"assessed","value":80,"evidence_ids":["p1"]}] for key in scoring.WEIGHTS}
        self.assertEqual(scoring.calculate(data)["overall"], 80)
        data["schema"].append({"id":"b","status":"unknown"})
        self.assertIsNone(scoring.calculate(data)["overall"])

    def test_score_requires_evidence(self):
        with self.assertRaises(ValueError):
            scoring.calculate({"schema":[{"id":"a","status":"assessed","value":20}]})


if __name__ == "__main__":
    unittest.main()
