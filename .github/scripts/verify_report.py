#!/usr/bin/env python3
"""Check report coverage, links, charts and collected data checksums."""
from hashlib import sha256
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]


def main():
    data=ROOT/'competitors/data'
    projects=json.loads((data/'projects.json').read_text())
    metrics=json.loads((data/'metrics.json').read_text())
    ids=[p['id'] for p in metrics['catalogue']]
    assert len(ids)==len(set(ids))==len(projects),'Project coverage mismatch'
    assert set(ids)=={str(p['id']) for p in projects},'Missing project'
    assert metrics['linked_projects']==sum(bool(p.get('repoUrls')) for p in projects)
    assert sum(metrics['project_types'].values())==len(projects)
    assert sum(metrics['loc_buckets'].values())==metrics['unique_repos']
    inventory=json.loads((data/'datasets.json').read_text())
    for f in inventory['files']:
        path=(data/f['file']).resolve()
        assert path.is_relative_to(data.resolve()),'Dataset escaped its directory'
        body=path.read_bytes()
        assert len(body)==f['bytes'] and sha256(body).hexdigest()==f['sha256'],f['file']
    assert len(inventory['files'])==metrics['data_files']
    for name in ['overview','types','loc','commits','data']:ET.parse(ROOT/'competitors'/f'{name}.svg')
    for path in [ROOT/'README.md',ROOT/'AGENTS.md',ROOT/'competitors/README.md',*sorted((ROOT/'research').glob('*.md'))]:
        for target in re.findall(r'\]\(([^)]+)\)',path.read_text()):
            if target.startswith('https://'):continue
            file,_,anchor=target.partition('#')
            dest=(path.parent/file).resolve()
            assert dest.is_relative_to(ROOT.resolve()) and dest.exists(),target
    assert '(research/README.md)' in (ROOT/'README.md').read_text(),'Root generator lost research link'
    assert '(AGENTS.md)' in (ROOT/'README.md').read_text(),'Root generator lost assistant instructions'
    for file in (ROOT/'research').glob('*.svg'):ET.parse(file)
    print('Verified',len(projects),'projects,',metrics['unique_repos'],'repos,',
          metrics['data_files'],'data checksums, Markdown links and all graphics.')


if __name__=='__main__':main()
