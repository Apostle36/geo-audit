import hashlib
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("evidence_contract", Path(__file__).resolve().parents[1] / "scripts/evidence.py")
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)


def capture(**changes):
    value = {"id": "page-1", "source": "https://example.com/", "collected_at": "2026-09-10T10:00:00Z",
             "method": "saved-http-response", "content": "Captured content", "status": "success",
             "sha256": hashlib.sha256(b"Captured content").hexdigest()}
    value.update(changes)
    return value


class EvidenceContract(unittest.TestCase):
    def test_valid_capture_and_resolution(self):
        registry = evidence.validate_registry([capture()])
        self.assertEqual(evidence.resolve_ids(["page-1"], registry)[0]["content"], "Captured content")

    def test_reference_regressions(self):
        registry = evidence.validate_registry([capture()])
        for ids in ("fiction", [None], ["does-not-exist"], [], [""], ["page-1", "page-1"]):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                evidence.resolve_ids(ids, registry)

    def test_failed_capture_cannot_support_assessment(self):
        registry = evidence.validate_registry([capture(status="failed")])
        with self.assertRaises(ValueError):
            evidence.resolve_ids(["page-1"], registry)
        self.assertEqual(len(evidence.resolve_ids(["page-1"], registry, require_success=False)), 1)

    def test_invalid_records(self):
        for change in ({"collected_at": "yesterday"}, {"collected_at": "2026-09-10"},
                       {"status": "invented"}, {"content": "tampered"}, {"sha256": ""},
                       {"source": " "}, {"method": None}, {"content": ""}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                evidence.validate_registry([capture(**change)])
        with self.assertRaises(ValueError):
            evidence.validate_registry([capture(), capture()])
        with self.assertRaises(ValueError):
            evidence.validate_registry({})

    def test_malformed_attributes_do_not_lose_later_data(self):
        result = evidence.extract('<meta name><link rel><script type></script><title>Later</title>')
        self.assertEqual(result["title"], "Later")
        self.assertEqual(len(result["errors"]), 3)

    def test_titles_are_separate_observations(self):
        result = evidence.extract('<title>Alpha &amp; β</title><title>Other</title>')
        self.assertEqual([item["text"] for item in result["titles"]], ["Alpha & β", "Other"])
        self.assertEqual(result["title"], "Alpha & β")
        self.assertTrue(result["errors"])

    def test_strict_json_preserves_invalid_raw(self):
        for body in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '{"x":-Infinity}', '{"x":1e999}'):
            with self.subTest(body=body):
                result = evidence.extract('<script type="application/ld+json">' + body + '</script>')
                self.assertEqual(result["jsonld"][0]["raw"], body)
                self.assertIsNone(result["jsonld"][0]["value"])
                self.assertTrue(result["errors"])


if __name__ == "__main__":
    unittest.main()
