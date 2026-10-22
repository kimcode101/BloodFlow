from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from unittest.mock import MagicMock
import subprocess
import sys

from blood_response import model
from blood_response.database import safe_schema, load_database
from blood_response.social import normalize

class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = model.load_world()

    def setUp(self):
        self.world = deepcopy(self.fixture)

    def test_source_ledger_reconciles(self):
        report = model.validate(self.world)
        self.assertEqual(report["units"], 1538)
        self.assertEqual(report["available_units"], 777)
        self.assertEqual(report["used_units"], 761)

    def test_partial_day_cannot_inflate_baseline(self):
        before = model.baselines(self.world)
        self.assertAlmostEqual(before[("H1", "A+")], 55/6)
        for r in self.world["daily_usage"]:
            if r["partial_day"] == "true":
                r["units_used"] = "999999"
        self.assertEqual(before, model.baselines(self.world))

    def test_broken_foreign_key_and_consumption_are_rejected(self):
        self.world["units"][0]["site_id"] = "MISSING"
        with self.assertRaises(ValueError):
            model.validate(self.world)
        self.world = deepcopy(self.fixture)
        self.world["daily_usage"][0]["units_used"] = "99999"
        with self.assertRaises(ValueError):
            model.validate(self.world)

    def test_zero_stock_and_unknown_usage_are_distinct(self):
        config = self.world["scenario"]
        self.assertEqual(model.classify_stock(0, None, config), "CRITICAL")
        self.assertEqual(model.classify_stock(2, None, config), "UNKNOWN")
        self.assertEqual(model.classify_stock(3, 1, config), "LOW")
        self.assertEqual(model.classify_stock(6, 1, config), "OK")

    def test_future_movement_is_not_completed_history(self):
        unit = next(u for u in self.world["units"] if u["status"] == "available" and u["expiry_date"] > "2026-10-23")
        destination = "B2" if unit["site_id"] != "B2" else "B1"
        self.world["transfers"].append({"transfer_id": "INVALID-FUTURE", "unit_id": unit["unit_id"],
            "from_site_id": unit["site_id"], "to_site_id": destination, "transfer_date": "2026-10-23"})
        unit["site_id"] = destination
        with self.assertRaisesRegex(ValueError, "completed movement"):
            model.validate(self.world)

    def test_duplicate_procedure_cannot_double_count_planned_demand(self):
        self.world["planned_activity"].append(dict(self.world["planned_activity"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate planned activity"):
            model.validate(self.world)

    def test_planning_uses_floor_not_double_counting(self):
        result = model.plan(self.world)
        row = next(r for r in result["rows"] if r["site_id"] == "H1" and r["blood_type"] == "O-")
        self.assertEqual(row["scheduled_critical_units"], 8)
        self.assertEqual(row["forecast_units"], 8)
        self.assertLess(row["forecast_units"], row["planned_units"] + row["baseline_daily_units"])

    def test_shared_bank_units_are_not_promised_twice(self):
        result = model.plan(self.world)
        ids = [uid for p in result["transfer_proposals"] for uid in p["unit_ids"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(result["uncovered_units"], 0)
        before = deepcopy(self.world)
        model.plan(self.world)
        self.assertEqual(before, self.world)

    def test_unknown_route_blocks_proposal_without_inventing_eta(self):
        for r in self.world["travel_times"]:
            if r["from_site_id"] == "B1" and r["to_site_id"] == "H1":
                r.update(route_status="unavailable", minutes_normal="", minutes_rush="", distance_km="")
        result = model.plan(self.world)
        row = next(r for r in result["rows"] if r["site_id"] == "H1" and r["blood_type"] == "O-")
        self.assertEqual(row["transfer_blocker"], "unknown_route_eta")
        self.assertGreater(row["uncovered_units"], 0)
        self.assertFalse(any(p["to_site_id"] == "H1" for p in result["transfer_proposals"]))

    def test_unknown_history_does_not_mean_zero_demand(self):
        self.world["daily_usage"] = []
        result = model.plan(self.world)
        self.assertEqual(result["unknown_demand_rows"], 32)
        self.assertTrue(all(r["forecast_units"] is None for r in result["rows"]))

    def test_expired_units_cannot_be_proposed(self):
        day = "2026-10-23"
        for u in self.world["units"]:
            if u["blood_type"] == "O-" and u["site_id"] == "B1":
                u["expiry_date"] = day
        result = model.plan(self.world)
        self.assertFalse(any(p["blood_type"] == "O-" and p["from_site_id"] == "B1" for p in result["transfer_proposals"]))

    def test_simulation_reproducible_conserving_and_reconciled(self):
        other = deepcopy(self.world)
        for _ in range(84):
            a = model.advance(self.world, seed=123)
            b = model.advance(other, seed=123)
            self.assertEqual(a, b)
            self.assertEqual(a["inventory_conservation"], "PASS")
            model.validate(self.world)
        self.assertEqual(self.world, other)
        self.assertEqual(datetime.fromisoformat(self.world["clock"]).utcoffset(), timedelta(hours=1))

    def test_hourly_consumption_stays_on_correct_day_at_midnight(self):
        self.world["clock"] = "2026-10-22T23:00:00+02:00"
        model.advance(self.world, seed=5)
        self.assertTrue(all(r["date"] <= "2026-10-22" for r in self.world["daily_usage"]))
        self.assertEqual(self.world["clock"], "2026-10-23T00:00:00+02:00")
        model.validate(self.world)

    def test_rebased_social_dates_use_paris_dst_and_no_oracle_fields(self):
        posts = [json.loads(line) for line in (model.DEFAULT_DATA/"social_reports.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(posts[0]["published_at"][:10], "2026-10-23")
        self.assertTrue(posts[-1]["published_at"].endswith("+01:00"))
        self.assertTrue(all("decisions" not in r and "expected_event_id" not in r for r in posts))
        self.assertTrue(all(datetime.fromisoformat(r["published_at"]) < datetime.fromisoformat(r["available_at"]) for r in posts))

    def test_public_or_injected_schema_is_rejected_before_connecting(self):
        for schema in ["public", "pg_catalog", "demo;drop_table", "information_schema"]:
            with patch("blood_response.database.connect") as connect:
                with self.assertRaises(ValueError):
                    load_database(self.world, schema)
                connect.assert_not_called()
        self.assertEqual(safe_schema("blood_demo"), "blood_demo")

    def test_loader_requires_explicit_reset_for_existing_objects(self):
        connection, cursor = MagicMock(), MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value.__enter__.return_value = cursor
        cursor.fetchone.return_value = ("blood_demo.sites",)
        with patch("blood_response.database.connect", return_value=connection):
            with self.assertRaisesRegex(ValueError, "Pass --reset"):
                load_database(self.world)
        self.assertFalse(any("DROP " in str(call) for call in cursor.execute.call_args_list))

    def test_postgres_copy_contract_accepts_all_canonical_columns(self):
        connection, cursor = MagicMock(), MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value.__enter__.return_value = cursor
        cursor.fetchone.return_value = (None,)
        with patch("blood_response.database.connect", return_value=connection):
            result = load_database(self.world)
        self.assertEqual(result["units"], 1538)
        self.assertEqual(cursor.copy.call_count, 6)
        self.assertFalse(any("DROP " in str(call) for call in cursor.execute.call_args_list))

    def test_loader_wrapper_validates_from_another_working_directory(self):
        result = subprocess.run([sys.executable, str(model.ROOT/"blood-storage"/"load_blood_data.py"), "--validate-only"], cwd=model.ROOT/"tests", text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["raw_source_hashes"], "PASS")

    def test_social_policy_suppresses_duplicate_and_keeps_event_escalated(self):
        reports = [{"report_id":"A", "available_at":"2026-10-23T10:00:00+02:00", "text":"same", "quoted_report_id":None},
            {"report_id":"B", "available_at":"2026-10-23T10:01:00+02:00", "text":"same", "quoted_report_id":"A"}]
        assessment = {"zone":"paris_northeast", "timing":"ongoing", "reported_impact_level_mode":3, "impact_pathway":"potential_demand", "update_type":"initial_report"}
        predictions = [{"report_id":r["report_id"], "available_at":r["available_at"], "assessment":assessment,
            "decisions":{"contribution":"adds_information"}, "event_id":"E1"} for r in reports]
        result = normalize(reports, predictions)
        self.assertEqual(result[0]["paris_action"], "URGENT_REVIEW")
        self.assertEqual(result[0]["event_review_priority"], "URGENT_REVIEW")
        self.assertEqual(result[1]["paris_action"], "IGNORE")
        self.assertEqual(result[1]["event_review_priority"], "URGENT_REVIEW")
        self.assertEqual(result[1]["event_phase"], "ongoing")
        self.assertEqual(result[1]["evidence_status"], "unverified")

    def test_social_policy_rejects_old_response_relabelled_as_forward_run(self):
        reports = [{"report_id":"A", "available_at":"2026-10-23T10:00:00+02:00"}]
        with self.assertRaisesRegex(ValueError, "clock mismatch"):
            normalize(reports, [{"report_id":"A", "available_at":"2026-10-16T10:00:00+02:00"}])

if __name__ == "__main__":
    unittest.main()
