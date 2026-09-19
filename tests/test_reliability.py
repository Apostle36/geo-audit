import importlib.util
from pathlib import Path
import unittest
from test_evidence_contract import capture

ROOT = Path(__file__).resolve().parents[1]

def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

pdf = module("pdf", "geo-audit-pdf.py")
evidence = module("evidence", "evidence.py")
scoring = module("scoring", "score.py")

def legacy(body="Body text", score="50/100"):
    return ("**Audit Date:** 2026-09-10\n**URL:** https://example.com/\n"
            "**Business Type:** Test business\n**Pages Analyzed:** 1\n"
            f"**Overall GEO Score: {score}**\n{body}")

class Reliability(unittest.TestCase):
    def test_decimal_score(self):
        self.assertEqual(pdf.parse_report(legacy(score="72.5/100"))["overall_score"], 72.5)

    def test_invalid_scores(self):
        for text in (legacy().replace("**Overall GEO Score: 50/100**", "No score"), legacy(score="999/100")):
            with self.assertRaises(ValueError):
                pdf.parse_report(text)

    def test_unassessed(self):
        self.assertIsNone(pdf.parse_report(legacy(score="Not assessed"))["overall_score"])

    def test_fenced_heading(self):
        data = pdf.parse_report(legacy("## Findings\n```markdown\n## Example\n```"))
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
        data = pdf.parse_report(legacy().replace("Test business", "<script>alert(1)</script>"))
        self.assertNotIn("<script>alert", pdf.generate_html(data))
        with self.assertRaises(ValueError):
            pdf.parse_report(legacy().replace("https://example.com/", "<script>alert(1)</script>"))

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
        self.assertIsNone(scoring.calculate({"rubric_version": "1.2.0", "evidence": [], "criteria": {}})["overall"])

    def test_weighted_score(self):
        rubric, _ = scoring.load_rubric("1.2.0")
        data = {"rubric_version": "1.2.0", "evidence": [capture()], "criteria": {
            key: [{"id": rule["id"], "status": "assessed", "value": 50,
                   "rationale": "Synthetic test observation", "evidence_ids": ["page-1"]}
                  for rule in profile["criteria"]] for key, profile in rubric["categories"].items()}}
        self.assertEqual(scoring.calculate(data)["overall"], 50)
        item = data["criteria"]["schema"][0]
        item["status"] = "unknown"
        del item["value"]
        self.assertIsNone(scoring.calculate(data)["overall"])

    def test_score_requires_evidence(self):
        with self.assertRaises(ValueError):
            scoring.calculate({"schema":[{"id":"a","status":"assessed","value":20}]})


if __name__ == "__main__":
    unittest.main()
