import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import audit_repos
import build_report
import collect_data
import refresh
from schedule_window import active


class RefreshTests(unittest.TestCase):
    def test_refresh_preserves_application_readme_content(self):
        before = '# App\n\nRun: npm start\n'
        after = '\n## Development\nRun: npm test\n'
        old = before + '<!-- competitors:start -->old<!-- competitors:end -->' + after
        new = build_report.update_snapshot(old, 'new metrics')
        self.assertTrue(new.startswith(before))
        self.assertTrue(new.endswith(after))
        self.assertIn('new metrics', new)
        for invalid in ['# Missing markers', '<!-- competitors:end --><!-- competitors:start -->']:
            with self.assertRaises(ValueError):
                build_report.update_snapshot(invalid, 'new metrics')

    def test_schedule_stops_at_brisbane_date_and_year(self):
        self.assertTrue(active('schedule',datetime(2026,10,27,22,tzinfo=timezone.utc)))
        self.assertFalse(active('schedule',datetime(2026,10,28,14,tzinfo=timezone.utc)))
        self.assertFalse(active('schedule',datetime(2027,10,27,22,tzinfo=timezone.utc)))
        self.assertTrue(active('workflow_dispatch',datetime(2027,1,1,tzinfo=timezone.utc)))

    def test_loc_unknown_is_not_zero(self):
        self.assertEqual(audit_repos.loc_bucket(None),'Unknown')
        self.assertEqual(audit_repos.loc_bucket(0),'0')
        for n,label in [(999,'1–999'),(1000,'1k–4.9k'),(4999,'1k–4.9k'),(5000,'5k–14.9k')]:
            self.assertEqual(audit_repos.loc_bucket(n),label)

    def test_source_excludes_bundled_libraries_but_keeps_authored_dist(self):
        for path in ['web/node_modules/x.ts','wwwroot/lib/bootstrap/dist/js/bootstrap.js',
                     'build/app.js','.github/skills/x.js','types/generated.d.ts']:
            self.assertFalse(audit_repos.eligible_source(path),path)
        self.assertTrue(audit_repos.eligible_source('dist/engine.mjs'))

    def test_repo_urls_reject_other_hosts_and_paths(self):
        self.assertEqual(audit_repos.slug_from_url('https://github.com/owner/repo.git'),'owner/repo')
        for url in ['https://github.com.evil.test/o/r','file:///tmp/r','https://github.com/o/r/tree/main']:
            self.assertIsNone(audit_repos.slug_from_url(url))

    def test_data_review_does_not_silently_follow_a_new_sha(self):
        repo={'slug':'a/b','status':'ok','sha':'new'}
        review={'a/b':{'sha':'old','bucket':'Synthetic generator','detail':'old review','evidence':[]}}
        self.assertFalse(build_report.review_for(repo,review)['current'])
        self.assertEqual(build_report.review_for(repo,{} )['bucket'],'Needs review')

    def test_changed_submission_invalidates_editorial_hash(self):
        before={'title':'A','description':'One idea','tagline':'x'}
        self.assertNotEqual(build_report.source_hash(before),
                            build_report.source_hash({**before,'description':'Different idea'}))

    def test_dataset_selection_does_not_copy_config_or_generated_reports(self):
        self.assertTrue(collect_data.candidate('backend/data/sample_matches/match/opta.json'))
        for path in ['data/schema.json','data/sample-overlay.json','package.json','data/config.json']:
            self.assertFalse(collect_data.candidate(path),path)
        self.assertEqual(collect_data.record_count(b'{"Events":[{},{}]}','.json'),2)

    def test_failed_export_keeps_previous_data_and_refreshes_repos(self):
        with tempfile.TemporaryDirectory() as name:
            data=Path(name)
            (data/'snapshot.json').write_text(json.dumps({'exported_at':'old','refresh_status':'ok'}))
            (data/'projects.json').write_text('[{"id":"old"}]')
            failure=subprocess.CompletedProcess([],1,stdout=b'',stderr=b'sensitive parser output')
            with patch.object(refresh,'DATA',data),patch('sys.argv',['refresh.py','--search-request',
                     'search.txt','--detail-request','details.txt']),patch.object(refresh.subprocess,'run',
                     side_effect=[failure,subprocess.CompletedProcess([],0),
                                  subprocess.CompletedProcess([],0),subprocess.CompletedProcess([],0)]) as run:
                self.assertEqual(refresh.main(),2)
                self.assertEqual((data/'projects.json').read_text(),'[{"id":"old"}]')
                snapshot=json.loads((data/'snapshot.json').read_text())
                self.assertEqual(snapshot['exported_at'],'old')
                self.assertEqual(snapshot['refresh_status'],'export_failed')
                self.assertEqual(run.call_count,4)

    def test_wrong_hackathon_cannot_replace_snapshot(self):
        with tempfile.TemporaryDirectory() as name:
            data=Path(name);(data/'snapshot.json').write_text('{"exported_at":"old"}')
            def bad_export(command,**kwargs):
                out=Path(command[command.index('--output-dir')+1]);out.mkdir()
                (out/'projects.json').write_text('[{"id":"x","hackathonId":"wrong"}]')
                return subprocess.CompletedProcess([],0)
            with patch.object(refresh,'DATA',data),patch('sys.argv',['refresh.py','--search-request',
                     'search.txt','--detail-request','details.txt']),patch.object(refresh.subprocess,'run',side_effect=bad_export):
                with self.assertRaises(SystemExit):refresh.main()


if __name__=='__main__':unittest.main()
