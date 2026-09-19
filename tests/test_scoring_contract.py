import copy
import unittest
from unittest.mock import patch
from test_reliability import scoring
from test_evidence_contract import capture


def assessment():
    rubric, _ = scoring.load_rubric("1.2.0")
    return {"rubric_version": "1.2.0", "evidence": [capture()], "criteria": {
        category: [{"id": rule["id"], "status": "assessed", "value": 100,
                    "rationale": "Synthetic fixture only: all declared sample units meet the anchor.",
                    "evidence_ids": ["page-1"]} for rule in profile["criteria"]]
        for category, profile in rubric["categories"].items()}}


class ScoringContract(unittest.TestCase):
    def test_complete_and_repeatable(self):
        data = assessment()
        result = scoring.calculate(data)
        self.assertEqual(result, scoring.calculate(copy.deepcopy(data)))
        self.assertEqual(result["overall"], 100)
        self.assertEqual(result["coverage"], 1)
        self.assertEqual(len(result["rubric_sha256"]), 64)

    def test_cherry_picking_is_incomplete(self):
        data = assessment()
        for items in data["criteria"].values():
            items.pop()
        result = scoring.calculate(data)
        self.assertIsNone(result["overall"])
        self.assertEqual(result["coverage"], .5)
        self.assertTrue(all(len(row["missing"]) == 1 for row in result["categories"].values()))

    def test_nonexistent_or_failed_evidence(self):
        for ids in ("fiction", [None], ["does-not-exist"], [], ["page-1", "page-1"]):
            data = assessment()
            data["criteria"]["technical"][0]["evidence_ids"] = ids
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                scoring.calculate(data)
        data = assessment()
        data["evidence"][0]["status"] = "failed"
        with self.assertRaises(ValueError):
            scoring.calculate(data)

    def test_invalid_values(self):
        for value in (True, False, "100", None, float("nan"), float("inf"), -1, 101, 80):
            data = assessment()
            data["criteria"]["content"][0]["value"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                scoring.calculate(data)

    def test_na_cannot_hide_coverage(self):
        data = assessment()
        for item in data["criteria"]["schema"]:
            item.update(status="not_applicable", reason="no_structured_data_in_sample")
            del item["value"]
        result = scoring.calculate(data)
        self.assertEqual(result["coverage"], .8)
        self.assertEqual(result["categories"]["schema"]["not_applicable"], 2)
        self.assertIsNone(result["overall"])
        data["criteria"]["schema"][0]["reason"] = "skip"
        with self.assertRaises(ValueError):
            scoring.calculate(data)

    def test_malformed_shapes_and_fields(self):
        for value in ([], None, {}, {"technical": []}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                scoring.calculate(value)
        for value in (None, {}, [None], [{"id": []}], [{"id": "fiction"}]):
            data = assessment()
            data["criteria"]["technical"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                scoring.calculate(data)
        data = assessment()
        data["criteria"]["technical"][0]["extra"] = "ignored?"
        with self.assertRaises(ValueError):
            scoring.calculate(data)

    def test_unknown_status_cannot_have_score(self):
        data = assessment()
        data["criteria"]["technical"][0]["status"] = "unknown"
        with self.assertRaises(ValueError):
            scoring.calculate(data)

    def test_unsupported_version(self):
        data = assessment()
        data["rubric_version"] = "1.1.0"
        with self.assertRaises(ValueError):
            scoring.calculate(data)

    def test_changed_rubric_cannot_reuse_version(self):
        with patch.object(scoring.Path, 'read_bytes', return_value=b'{"version":"1.2.0","changed":true}'), self.assertRaisesRegex(ValueError, 'modified'):
            scoring.calculate(assessment())


if __name__ == "__main__":
    unittest.main()
