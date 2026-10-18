#!/usr/bin/env python3
"""Check report coverage, links, charts and collected data checksums."""
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]


def main():
    data=ROOT/'competitors/data'
    projects=json.loads((data/'projects.json').read_text())
    metrics=json.loads((data/'metrics.json').read_text())
    audit=json.loads((data/'repositories.json').read_text())
    snapshot=json.loads((data/'snapshot.json').read_text())
    assert snapshot['project_count']==len(projects),'Snapshot count mismatch'
    assert metrics['unique_repos']==len(audit['repositories']),'Repository count mismatch'
    assert metrics['readable_repos']==sum(r['status']=='ok' for r in audit['repositories']),'Readable repository count mismatch'
    assert metrics['github_checked_at']==audit['checked_at'],'GitHub audit date mismatch'
    ids=[p['id'] for p in metrics['catalogue']]
    assert len(ids)==len(set(ids))==len(projects),'Project coverage mismatch'
    assert set(ids)=={str(p['id']) for p in projects},'Missing project'
    assert metrics['linked_projects']==sum(bool(p.get('repoUrls')) for p in projects)
    assert sum(metrics['project_types'].values())==len(projects)
    assert sum(metrics['loc_buckets'].values())==metrics['unique_repos']
    inventory=json.loads((data/'datasets.json').read_text())
    assert inventory['path_base']=='repository_root'
    for f in inventory['files']:
        path=(ROOT/f['file']).resolve()
        assert path.is_relative_to((ROOT/'data/synthetic').resolve()),'Dataset escaped its directory'
        body=path.read_bytes()
        assert len(body)==f['bytes'] and sha256(body).hexdigest()==f['sha256'],f['file']
    assert len(inventory['files'])==metrics['data_files']
    for file in (ROOT/'competitors').glob('*.svg'):ET.parse(file)
    from build_judging import validate_record
    ledger=json.loads((data/'judgements.json').read_text())
    seen=set()
    for record in ledger['assessments']:
        validate_record(record)
        assert record['assessment_id'] not in seen, 'Duplicate assessment'
        seen.add(record['assessment_id'])
    # A file on disk is not enough: README targets must also ship in Git.
    tracked=set(subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0'))
    for path in [ROOT/'README.md',ROOT/'AGENTS.md',ROOT/'competitors/README.md',*sorted((ROOT/'research').rglob('*.md')),*sorted((ROOT/'data').rglob('README.md'))]:
        for target in re.findall(r'\]\(([^)]+)\)',path.read_text()):
            prefix='https://github.com/taka6745/insidethegame/blob/main/'
            if target.startswith(prefix):
                base=ROOT
                target=target[len(prefix):]
            elif target.startswith('https://'):
                continue
            else:
                base=path.parent
            file,_,anchor=target.partition('#')
            dest=(base/unquote(file)).resolve() if file else path.resolve()
            assert dest.is_relative_to(ROOT.resolve()) and dest.exists(),f'{path}: {target}'
            relative=dest.relative_to(ROOT).as_posix()
            assert relative in tracked or (dest.is_dir() and any(p.startswith(relative+'/') for p in tracked)),f'Link target not tracked in Git: {relative}'
    assert '(research/README.md)' in (ROOT/'README.md').read_text(),'Root generator lost research link'
    assert '(AGENTS.md)' in (ROOT/'README.md').read_text(),'Root generator lost assistant instructions'
    for file in (ROOT/'research').rglob('*.svg'):ET.parse(file)
    for file in (ROOT/'data/GoogleResearchFootball').glob('*.svg'):ET.parse(file)
    print('Verified',len(projects),'projects,',metrics['unique_repos'],'repos,',
          metrics['data_files'],'data checksums, Markdown links and all graphics.')


if __name__=='__main__':main()
