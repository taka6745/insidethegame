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
        row = repo.create_run(run_id, match_id, "chelsea-united", kickoff)
        self.assertEqual((row["run_id"], row["status"], row["position"]), (run_id, "scheduled", 0))
        repo.progress(run_id, 12, 7, "live")
        mine = next(r for r in repo.runs() if r["match_id"] == match_id)
        self.assertEqual((mine["position"], mine["seq"], mine["status"]), (12, 7, "live"))
        repo.tombstone([match_id])
        self.assertNotIn(match_id, [r["match_id"] for r in repo.runs()])  # gone before delete
        self.assertEqual(repo.delete_runs([match_id]), 1)
        self.assertIsNone(repo.create_run(str(uuid.uuid4()), match_id, "chelsea-united", kickoff))

    def test_catalogue_sync(self):
        entry = {"fixture": "test-fixture", "source_match_id": "m", "description": "d",
                 "teams": [{"id": "a", "name": "A", "position": "home"}], "duration_seconds": 1.5,
                 "capabilities": {"video": False}, "synthetic": True, "sha256": "0" * 64}
        self.repository.sync_recordings([entry])
        self.assertEqual(self.repository.recordings(), [{k: v for k, v in entry.items() if k != "sha256"}])

    def test_cutoff_hides_older_runs(self):
        repo, run_id = self.repository, str(uuid.uuid4())
        repo.create_run(run_id, f"cut-{run_id[:8]}", "chelsea-united", datetime.now(timezone.utc))
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
        self.assertEqual((current["main_fixture"], current["fixtures"][0]), ("arsenal-liverpool", "arsenal-liverpool"))
        settings = {k: current[k] for k in ("fixtures", "main_fixture", "stagger_seconds", "max_active_runs",
                                            "start_points")}
        saved = repo.save_demo_settings({**settings, "stagger_seconds": 60}, current["revision"])
        self.assertEqual((saved["stagger_seconds"], saved["revision"]), (60, current["revision"] + 1))
        self.assertIsNone(repo.save_demo_settings(settings, current["revision"]))  # stale
        repo.save_demo_settings(settings, saved["revision"])
