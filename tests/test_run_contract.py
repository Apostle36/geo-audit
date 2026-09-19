import copy
import unittest
from test_scoring_contract import assessment
from run_contract import validate_run, report_data, comparable


def run_fixture():
    return {"schema_version": "1.2.0", "metadata": {
        "url": "https://example.com/", "date": "2026-09-10", "business_type": "Synthetic test business",
        "market": "Test market", "language": "en", "sample": ["https://example.com/"],
        "sampling_rationale": "Synthetic single-page fixture, not a live audit."},
        "assessment": assessment(), "summary": "Synthetic test conclusion — not a live audit.",
        "limitations": ["Synthetic data only; factual truth not verified."],
        "findings": [{"id": "F1", "category": "content", "kind": "observation", "status": "present",
                      "affected_urls": ["https://example.com/"], "evidence_ids": ["page-1"],
                      "observed": "Captured content", "claim": "Synthetic content observation", "consequence": "Test only",
                      "fix": "No action; synthetic fixture", "acceptance": "Verify fixture preservation", "severity": "informational",
                      "confidence_reason": "Fixture, not a measured business result"}]}


class RunContract(unittest.TestCase):
    def test_valid_run_and_calculated_report(self):
        run = run_fixture()
        self.assertEqual(validate_run(run)["overall"], 100)
        self.assertEqual(report_data(run)["overall_score"], 100)
        self.assertIn("Captured content", str(report_data(run)))

    def test_finding_references_resolve(self):
        for ids in ("fiction", [None], ["missing"], []):
            run = run_fixture()
            run["findings"][0]["evidence_ids"] = ids
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                validate_run(run)

    def test_failed_collection_only_supports_unknown(self):
        run = run_fixture()
        run["assessment"]["criteria"] = {}
        run["assessment"]["evidence"][0]["status"] = "failed"
        with self.assertRaises(ValueError):
            validate_run(run)
        run["findings"][0].update(kind="unknown", status="unknown")
        self.assertIsNone(validate_run(run)["overall"])

    def test_extra_sample_requires_evidence(self):
        run = run_fixture()
        run["metadata"]["sample"].append("https://example.com/other")
        with self.assertRaises(ValueError):
            validate_run(run)

    def test_unknown_extra_fields_and_malformed_metadata(self):
        for field, value in (("url", "not-a-url"), ("date", "yesterday"), ("sample", []),
                             ("market", None), ("language", ""), ("sample", [None])):
            run = run_fixture()
            run["metadata"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validate_run(run)
        run = run_fixture()
        run["overall_score"] = 5
        with self.assertRaises(ValueError):
            validate_run(run)

    def test_hash_mismatch(self):
        run = run_fixture()
        run["assessment"]["evidence"][0]["content"] = "Changed after capture"
        with self.assertRaises(ValueError):
            validate_run(run)

    def test_comparison_scope(self):
        a, b = run_fixture(), run_fixture()
        b["metadata"]["date"] = "2026-09-11"
        self.assertTrue(comparable(a, b)["comparable"])
        b["metadata"]["market"] = "Other market"
        self.assertEqual(comparable(a, b)["differences"], ["market"])

    def test_comparison_applicability(self):
        a, b = run_fixture(), run_fixture()
        for item in b["assessment"]["criteria"]["schema"]:
            item.update(status="not_applicable", reason="no_structured_data_in_sample")
            del item["value"]
        self.assertIn("applicability", comparable(a, b)["differences"])

    def test_model_does_not_mutate_input(self):
        run = run_fixture()
        before = copy.deepcopy(run)
        report_data(run)
        self.assertEqual(run, before)
