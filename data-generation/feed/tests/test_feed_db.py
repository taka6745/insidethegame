"""FeedRepository against a real Postgres: set FEED_TEST_DATABASE_URL (a throwaway database)."""
import os
import unittest
import uuid
from datetime import datetime, timezone

URL = os.environ.get("FEED_TEST_DATABASE_URL")


@unittest.skipUnless(URL, "FEED_TEST_DATABASE_URL not set")
class FeedRepositoryTests(unittest.TestCase):
    def setUp(self):
        from feed.repositories.feed_db import FeedRepository
        self.repository = FeedRepository(URL)
        self.repository.migrate()
        self.repository.migrate()  # idempotent

    def test_runs_progress_and_purge(self):
        repo, run_id = self.repository, str(uuid.uuid4())
        match_id = f"test-{run_id[:8]}"
        kickoff = datetime(2026, 10, 20, 15, tzinfo=timezone.utc)
        row = repo.create_run(run_id, match_id, "riverton-forgeham", kickoff, hold_seconds=1200.0, hold_point="20")
        self.assertEqual((row["run_id"], row["status"], row["position"], row["hold_point"]),
                         (run_id, "scheduled", 0, "20"))  # a recording run keeps its point (006)
        repo.progress(run_id, 12, 7, "live")
        mine = next(r for r in repo.runs() if r["match_id"] == match_id)
        self.assertEqual((mine["position"], mine["seq"], mine["status"]), (12, 7, "live"))
        repo.tombstone([match_id])
        self.assertNotIn(match_id, [r["match_id"] for r in repo.runs()])  # gone before delete
        self.assertEqual(repo.delete_runs([match_id]), 1)
        self.assertIsNone(repo.create_run(str(uuid.uuid4()), match_id, "riverton-forgeham", kickoff))

    def test_skip_ahead_shifts_an_unfinished_runs_kickoff_only(self):
        repo, run_id = self.repository, str(uuid.uuid4())
        match_id = f"skip-{run_id[:8]}"
        kickoff = datetime(2026, 10, 20, 15, tzinfo=timezone.utc)
        repo.create_run(run_id, match_id, "riverton-forgeham", kickoff)
        moved = repo.shift_kickoff(match_id, 600)
        self.assertEqual(moved["kickoff"], datetime(2026, 10, 20, 14, 50, tzinfo=timezone.utc))
        repo.progress(run_id, 1, 0, "finished")
        self.assertIsNone(repo.shift_kickoff(match_id, 60))  # a finished run stays put
        repo.tombstone([match_id])
        repo.delete_runs([match_id])

    def test_catalogue_sync(self):
        entry = {"fixture": "test-fixture", "source_match_id": "m", "description": "d",
                 "teams": [{"id": "a", "name": "A", "position": "home"}], "duration_seconds": 1.5,
                 "capabilities": {"video": False}, "synthetic": True, "sha256": "0" * 64}
        self.repository.sync_recordings([entry])
        self.assertEqual(self.repository.recordings(), [{k: v for k, v in entry.items() if k != "sha256"}])

    def test_cutoff_hides_older_runs(self):
        repo, run_id = self.repository, str(uuid.uuid4())
        repo.create_run(run_id, f"cut-{run_id[:8]}", "riverton-forgeham", datetime.now(timezone.utc))
        repo.tombstone([], cutoff=True)
        self.assertNotIn(run_id, [r["run_id"] for r in repo.runs()])


@unittest.skipUnless(URL, "FEED_TEST_DATABASE_URL not set")
class DemoSettingsTests(unittest.TestCase):
    def test_seeded_settings_save_with_a_revision_check(self):
        from feed.repositories.feed_db import FeedRepository
        repo = FeedRepository(URL)
        repo.migrate()
        current = repo.demo_settings()
        self.assertEqual(len(current["fixtures"]), current["max_active_runs"])
        self.assertEqual(current["start_points"][0]["id"], "kickoff")
        self.assertEqual((current["main_fixture"], current["fixtures"][0]), ("redcastle-portalbion", "redcastle-portalbion"))
        settings = {k: current[k] for k in ("fixtures", "main_fixture", "stagger_seconds", "max_active_runs",
                                            "start_points")}
        saved = repo.save_demo_settings({**settings, "stagger_seconds": 60}, current["revision"])
        self.assertEqual((saved["stagger_seconds"], saved["revision"]), (60, current["revision"] + 1))
        self.assertIsNone(repo.save_demo_settings(settings, current["revision"]))  # stale
        self.assertEqual([t["id"] for t in saved["skip_targets"]], ["10", "20", "ht"])  # kept when left out (007)
        repo.save_demo_settings(settings, saved["revision"])
