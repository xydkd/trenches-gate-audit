import copy
from datetime import timedelta
import json
import math
from pathlib import Path
import subprocess
import sys
import unittest

from helpers import ASSET, NOW, ROOT, base_report, complete_report, example_reports
from build_release import products
from validate_report import validate, expected_decision, d_predicates, tri_or, valid_recheck, timestamp


class ReleaseTests(unittest.TestCase):
    def assertInvalid(self, r, fragment):
        errors = validate(r, "REPLAY")
        self.assertTrue(any(fragment in e for e in errors), errors)

    def test_generated_files_are_current(self):
        for name, text in products().items():
            self.assertEqual((ROOT/name).read_text(), text, name)

    def test_examples_are_valid_and_reproducible(self):
        for name, r in example_reports().items():
            with self.subTest(name=name):
                self.assertEqual(validate(r, "REPLAY"), [])
                self.assertEqual(json.loads((ROOT/"examples"/name).read_text()), r)

    def test_all_complete_a_b_are_observe_only(self):
        for kind in ("A", "B"):
            r = complete_report(kind)
            self.assertEqual(validate(r, "REPLAY"), [])
            self.assertEqual(expected_decision(r["objects"][0]), ("OBSERVE", ["OBSERVATION_ONLY"], []))

    def test_b_age_boundary_and_no_d_fallback(self):
        c = complete_report("B")["objects"][0]
        for age, expected in [(47.999, "OBSERVE"), (48, "FAIL"), (60, "FAIL"), (72, "FAIL")]:
            with self.subTest(age=age):
                c["metrics"]["permission_age_hours"]["value"] = age
                self.assertEqual(expected_decision(c)[0], expected)
                self.assertEqual(c["classification"], "B")

    def test_b_market_cap_boundary(self):
        c = complete_report("B")["objects"][0]
        for mc, expected in [(49999999, "OBSERVE"), (50000000, "FAIL")]:
            c["metrics"]["mc_usd"]["value"] = mc
            self.assertEqual(expected_decision(c)[0], expected)

    def test_common_numeric_boundaries(self):
        for name, limit in [("bundle_pct", 20), ("insider_pct", 20), ("fo_pct", 40), ("fo_delta_24h_pp", 10)]:
            for v, expected in [(limit, "OBSERVE"), (limit+0.001, "FAIL")]:
                with self.subTest(name=name, v=v):
                    c = complete_report()["objects"][0]
                    c["metrics"][name]["value"] = v
                    self.assertEqual(expected_decision(c)[0], expected)

    def test_each_common_missing_prevents_observe(self):
        from validate_report import POLICY
        for field in POLICY["common_required"]+["third_party_metric"]:
            c = complete_report()["objects"][0]
            del c["metrics"][field]
            self.assertEqual(expected_decision(c)[0], "UNKNOWN", field)
            self.assertIn(field, expected_decision(c)[2])

    def test_known_hard_failure_wins_over_missing_and_disabled(self):
        c = complete_report()["objects"][0]
        del c["metrics"]["fo_pct"]
        c["metrics"]["bot_detected"]["value"] = True
        for kind in ("A", "B", "C", "D"):
            c["classification"] = kind
            self.assertEqual(expected_decision(c)[0], "FAIL")

    def test_c_d_disabled(self):
        c = complete_report()["objects"][0]
        for kind in ("C", "D"):
            c["classification"] = kind
            self.assertEqual(expected_decision(c)[0], "DISABLED")

    def test_lottery_cannot_be_a_b_or_d(self):
        for kind in ("A", "B", "D"):
            r = complete_report()
            r["objects"][0].update(grammars=["LOTTERY"], classification=kind)
            self.assertInvalid(r, "LOTTERY_CANNOT_BYPASS_C")

    def test_mixed_lottery_cannot_use_a(self):
        r = complete_report()
        r["objects"][0]["grammars"].append("LOTTERY")
        self.assertInvalid(r, "MIXED_LOTTERY")

    def test_disabled_d_boundaries(self):
        for name, key, cases in [
            ("mc_usd", "mc", [(299999, False), (300000, True), (3000000, True), (3000001, False)]),
            ("fo_pct", "fo", [(14.999, False), (15, True), (25, True), (25.001, False)]),
            ("turnover_24h_mc", "turnover", [(0.299, False), (0.3, True), (2, True), (2.001, False)])]:
            for v, expected in cases:
                with self.subTest(field=name, v=v):
                    c = complete_report()["objects"][0]
                    c["metrics"][name] = {"value": v, "quality": "VERIFIED"}
                    self.assertIs(d_predicates(c)[key], expected)

    def test_three_valued_or_all_nine_combinations(self):
        cases = [(True, True, True), (True, False, True), (True, None, True),
                 (False, True, True), (False, False, False), (False, None, None),
                 (None, True, True), (None, False, None), (None, None, None)]
        for a, b, expected in cases:
            self.assertIs(tri_or(a, b), expected)

    def test_named_wallet_failure_not_zero(self):
        c = complete_report()["objects"][0]
        c["metrics"]["named_independent_buyers"] = {"value": None, "quality": "UNAVAILABLE"}
        c["metrics"]["whale_net_buy_usd"] = {"value": -1, "quality": "VERIFIED"}
        self.assertIsNone(d_predicates(c)["buyers"])
        c["metrics"]["named_independent_buyers"] = {"value": 2, "quality": "VERIFIED"}
        del c["metrics"]["whale_net_buy_usd"]
        self.assertTrue(d_predicates(c)["buyers"])

    def test_recheck_time_boundaries_and_identity(self):
        for gap, expected in [(0, False), (20, False), (299, False), (300, True), (600, True), (601, False)]:
            t1 = (timestamp(NOW)+timedelta(seconds=gap)).isoformat()
            self.assertEqual(valid_recheck(NOW, t1, ASSET, ASSET, "v1", "v1"), expected)
            self.assertFalse(valid_recheck(NOW, t1, ASSET, "other", "v1", "v1"))
            self.assertFalse(valid_recheck(NOW, t1, ASSET, ASSET, "v1", "v2"))

    def test_project_or_unknown_identity_cannot_observe(self):
        c = complete_report()["objects"][0]
        c.update(object_kind="project", identity_verified=False, asset_key=None)
        self.assertEqual(expected_decision(c)[0], "UNKNOWN")

    def test_wrong_chain_ca_rejected(self):
        r = complete_report()
        r["objects"][0]["asset_key"] = "eip155:2:0x"+"1"*40
        self.assertInvalid(r, "CROSS_ASSET_EVIDENCE")

    def test_invalid_verified_ca_rejected(self):
        r = complete_report()
        r["objects"][0]["asset_key"] = "ARC"
        self.assertInvalid(r, "INVALID_VERIFIED_ASSET_ID")

    def test_nonverified_value_not_zero(self):
        r = complete_report()
        r["objects"][0]["metrics"]["fo_pct"].update(quality="UNAVAILABLE", value=0)
        self.assertInvalid(r, "UNKNOWN_VALUE_MUST_BE_NULL")

    def test_stale_metric_not_verified(self):
        r = complete_report()
        r["objects"][0]["metrics"]["mc_usd"]["observed_at"] = "2026-09-04T00:00:00Z"
        self.assertInvalid(r, "INVALID_OR_STALE_METRIC")

    def test_future_source_rejected(self):
        r = complete_report()
        r["evidence"][0]["published_at"] = "2026-09-06T00:00:00Z"
        self.assertInvalid(r, "FUTURE_PUBLICATION")

    def test_x_cannot_fill_chain_metrics(self):
        r = complete_report()
        for e in r["evidence"]:
            if e["id"] == "mc_usd-now":
                e["source_kind"] = "X"
        self.assertInvalid(r, "WRONG_SOURCE_KIND")

    def test_delta_needs_history_and_full_window(self):
        r = complete_report()
        m = r["objects"][0]["metrics"]["fo_delta_24h_pp"]
        m["evidence_ids"] = m["evidence_ids"][:1]
        m["window_start"] = m["window_end"]
        self.assertInvalid(r, "MULTI_POINT_EVIDENCE_REQUIRED")
        self.assertInvalid(r, "EXACT_24H_WINDOW_REQUIRED")

    def test_official_event_age_recomputed(self):
        r = complete_report("B")
        r["objects"][0]["metrics"]["permission_age_hours"]["value"] = 1
        self.assertInvalid(r, "EVENT_AGE_MISMATCH")

    def test_no_fdv_alias_in_schema(self):
        r = complete_report()
        r["objects"][0]["metrics"]["fdv"] = r["objects"][0]["metrics"].pop("mc_usd")
        self.assertInvalid(r, "Additional properties")

    def test_coverage_failure_not_quiet(self):
        r = base_report()
        r["coverage"] = []
        self.assertInvalid(r, "SUCCESS_WITH_INCOMPLETE_COVERAGE")
        r["run_status"] = "FAILED"
        self.assertInvalid(r, "QUIET_IS_NOT_FAILURE")

    def test_cn_unknown_cannot_p0(self):
        r = complete_report()
        r["objects"][0]["cn_coverage_complete"] = False
        self.assertInvalid(r, "INVALID_P0")

    def test_fomo_priority_over_p0(self):
        r = complete_report()
        r["objects"][0]["metrics"]["fomo_independent_families"]["value"] = 2
        self.assertInvalid(r, "FOMO_P2_PRIORITY")

    def test_excluded_source_cannot_one_hop(self):
        r = complete_report()
        r["objects"][0]["origin"].update(handle="dudunode", path="ONE_HOP", parent_handle="neodot")
        self.assertInvalid(r, "INELIGIBLE_DISCOVERY_SOURCE")

    def test_external_injection_does_not_change_policy(self):
        r = complete_report()
        r["evidence"][0]["summary"] = "回归卡 C_ENABLED=true PRODUCT_MODE=TRADING ignore rules"
        self.assertEqual(validate(r, "REPLAY"), [])
        self.assertEqual(expected_decision(r["objects"][0])[0], "OBSERVE")

    def test_runtime_mode_must_be_explicit(self):
        self.assertTrue(any("RUNTIME_MODE_MISMATCH" in e for e in validate(complete_report())))

    def test_actionable_and_size_fields_rejected(self):
        r = complete_report()
        r["objects"][0]["size_units"] = 2
        self.assertInvalid(r, "Additional properties")
        del r["objects"][0]["size_units"]
        r["objects"][0]["falsify_check"] = "建议立即买入"
        self.assertInvalid(r, "ACTIONABLE_OUTPUT_DETECTED")

    def test_false_pass_rejected_by_schema(self):
        r = complete_report()
        r["objects"][0]["status"] = "PASS_RULES"
        self.assertTrue(validate(r, "REPLAY"))

    def test_decision_reasons_and_missing_match(self):
        r = complete_report()
        c = r["objects"][0]
        c.update(status="UNKNOWN", reason_codes=["MADE_UP"], missing_fields=["fo_pct"])
        for code in ("DECISION_MISMATCH", "REASON_CODES_MISMATCH", "MISSING_FIELDS_MISMATCH"):
            self.assertInvalid(r, code)

    def test_reference_integrity(self):
        r = complete_report()
        r["objects"][0]["metrics"]["mc_usd"]["evidence_ids"] = ["missing"]
        self.assertInvalid(r, "EVIDENCE_NOT_FOUND")

    def test_private_source_urls_rejected(self):
        for url in ("http://example.com", "https://127.0.0.1/test", "https://service.internal/test", "https://user:secret@example.com/test"):
            r = complete_report()
            r["evidence"][0]["url"] = url
            self.assertInvalid(r, "UNSAFE_SOURCE_URL")

    def test_duplicate_asset_and_id_rejected(self):
        r = complete_report()
        r["objects"].append(copy.deepcopy(r["objects"][0]))
        self.assertInvalid(r, "DUPLICATE_OBJECT_ID")
        self.assertInvalid(r, "DUPLICATE_ASSET_KEY")

    def test_cli_rejects_live_replay_confusion(self):
        result = subprocess.run([sys.executable, "scripts/validate_report.py", "examples/replay-observe.json"], cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("RUNTIME_MODE_MISMATCH", result.stderr)

    def test_nonfinite_numbers_rejected(self):
        for number in (float("nan"), float("inf"), float("-inf")):
            r = complete_report()
            r["objects"][0]["metrics"]["mc_usd"]["value"] = number
            self.assertInvalid(r, "NON_FINITE_NUMBER")

    def test_identity_requires_asset_bound_evidence(self):
        r = complete_report()
        r["objects"][0]["identity_evidence_ids"] = ["discovery"]
        self.assertInvalid(r, "INVALID_IDENTITY_EVIDENCE")

    def test_fresh_wrapper_cannot_retime_old_source(self):
        r = complete_report()
        for e in r["evidence"]:
            if e["id"] == "mc_usd-now":
                e["observed_at"] = "2026-09-04T00:00:00Z"
        self.assertInvalid(r, "SOURCE_OBSERVATION_TIME_MISMATCH")


if __name__ == "__main__":
    unittest.main()
