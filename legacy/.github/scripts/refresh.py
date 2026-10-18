#!/usr/bin/env python3
"""Refresh the export, audit listed repos, and regenerate the competitor report."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT/'competitors/data'


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repos-only', action='store_true', help='Keep the saved project export; refresh GitHub only')
    parser.add_argument('--search-request', type=Path)
    parser.add_argument('--detail-request', type=Path)
    parser.add_argument('--cache-dir', type=Path)
    args = parser.parse_args()
    snapshot = json.loads((DATA/'snapshot.json').read_text())
    failed = False
    if not args.repos_only:
        with tempfile.TemporaryDirectory(prefix='insidethegame-export-') as name:
            temp = Path(name)
            paths = []
            for local, variable, filename in [
                (args.search_request,'INNOVATION_SEARCH_CURL','search-request.txt'),
                (args.detail_request,'INNOVATION_DETAIL_CURL','detail-request.txt')]:
                if local:
                    paths.append(local.resolve())
                elif os.environ.get(variable):
                    path = temp/filename
                    path.write_text(os.environ[variable]); path.chmod(0o600)
                    paths.append(path)
            if len(paths) != 2:
                snapshot.update(refresh_status='credentials_missing', last_attempt_at=timestamp())
                print('Project refresh needs both Innovation Studio requests. Keeping the last successful export.')
                failed = True
            else:
                command = [sys.executable,str(ROOT/'.github/scripts/fetch_projects.py'),str(paths[0]),
                           '--detail-curl-file',str(paths[1]),'--page-size','50',
                           '--output-dir',str(temp/'export')]
                # Never expose copied request bodies or parser errors in CI logs.
                result = subprocess.run(command,capture_output=True,timeout=900)
                if result.returncode:
                    snapshot.update(refresh_status='export_failed',last_attempt_at=timestamp())
                    print('Project refresh failed; session may have expired. Keeping the last successful export.')
                    failed = True
                else:
                    projects = json.loads((temp/'export/projects.json').read_text())
                    if not projects or any(str(p.get('hackathonId')) != '34887' for p in projects):
                        raise SystemExit('Refusing to replace the snapshot with a different or empty hackathon.')
                    for file in ['projects.json','projects.csv']:
                        os.replace(temp/'export'/file, DATA/file)
                    snapshot.update(exported_at=timestamp(),refresh_status='ok',
                                    last_attempt_at=timestamp(),project_count=len(projects))
                    print('Refreshed',len(projects),'projects and their listed repo URLs.')
    (DATA/'snapshot.json').write_text(json.dumps(snapshot,indent=2)+'\n')
    with tempfile.TemporaryDirectory(prefix='insidethegame-research-') as cache:
        cache_dir = str(args.cache_dir or Path(cache))
        for script in ['audit_repos.py','collect_data.py']:
            subprocess.run([sys.executable,str(ROOT/'.github/scripts'/script),
                            '--cache-dir',cache_dir],check=True)
        subprocess.run([sys.executable,str(ROOT/'.github/scripts/build_report.py')],check=True)
    if failed:
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
