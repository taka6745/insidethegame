#!/usr/bin/env python3
"""Collect competitors' committed sample data without executing their code."""
import argparse
import csv
from hashlib import sha256
import io
import json
from pathlib import Path
import re
from urllib.parse import quote
from urllib.request import urlopen
import zipfile

from audit_repos import git

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT/'competitors/data'
SAMPLES = ROOT/'data/synthetic'
LIMIT = 32_000_000


def candidate(path):
    return bool(re.search(r'(^|/)(data|datasets?|samples?|fixtures?)(/|$)',path,re.I) and
                re.search(r'\.(json|jsonl|ndjson|csv|tsv|xml|parquet)$',path,re.I) and
                not re.search(r'node_modules|/obj/|/bin/|\.claude|\.agents|schema|manifest|recap|'
                              r'report|overlay|index\.json|player-pulse|\.ai|package|config',path,re.I))


def event_count(value):
    if isinstance(value,list):
        return len(value)
    if isinstance(value,dict):
        for key in ['events','Events','event','result','data','timeline']:
            if isinstance(value.get(key),list):
                return len(value[key])
            if isinstance(value.get(key),dict):
                number=event_count(value[key])
                if number is not None:return number
    return None


def record_count(content,suffix):
    decoded=content.decode('utf-8-sig')
    if suffix=='.json':return event_count(json.loads(decoded))
    if suffix in {'.jsonl','.ndjson'}:
        rows=[line for line in decoded.splitlines() if line.strip()]
        for line in rows:json.loads(line)
        return len(rows)
    if suffix in {'.csv','.tsv'}:
        return len(list(csv.DictReader(io.StringIO(decoded),delimiter='\t' if suffix=='.tsv' else ',')))
    return None


def save(repo,content,path,url,seen,kind='Committed sample'):
    digest=sha256(content).hexdigest()
    if digest in seen:
        seen[digest]['also_at'].append(url)
        return
    directory=SAMPLES/repo['slug'].replace('/','__')
    directory.mkdir(parents=True,exist_ok=True)
    name=path.replace('/','__')
    destination=directory/name
    destination.write_bytes(content)
    try:rows=record_count(content,destination.suffix.lower())
    except (ValueError,UnicodeError):raise RuntimeError('Invalid sample data: '+repo['slug']+'/'+path)
    seen[digest]={'repo':repo['slug'],'sha':repo['sha'],'file':str(destination.relative_to(ROOT)),
                  'source_path':path,'source_url':url,'also_at':[],'sha256':digest,
                  'bytes':len(content),'records':rows,'kind':kind,
                  'repository_license':repo.get('license')}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-dir',type=Path,required=True)
    args=parser.parse_args()
    audit=json.loads((DATA/'repositories.json').read_text())
    records=[]
    for repo in audit['repositories']:
        if repo['status']!='ok':continue
        checkout=args.cache_dir/repo['slug'].replace('/','__')
        seen={}
        for f in repo['files']:
            path=f['path']
            examples=repo['slug']=='devgupta-9/reactcoach-11' and path=='docs/examples/open-play-request.json'
            if not candidate(path) and not examples:continue
            if f['bytes']>LIMIT:raise RuntimeError('Sample exceeds collection limit: '+path)
            content=git(checkout,'show',repo['sha']+':'+path)
            url=repo['url']+'/blob/'+repo['sha']+'/'+quote(path,safe='/')
            save(repo,content,path,url,seen)
        if repo['slug']=='Hapinam/vybe-ai':
            path='apps/web/src/match.ts'
            source=git(checkout,'show',repo['sha']+':'+path).decode()
            # Parse a JSON-compatible constant; never evaluate TypeScript or JS.
            match=re.search(r'export const demoMatch: Match = (\{.*?\n\});',source,re.S)
            if match:
                literal=re.sub(r'([,{]\s*)([A-Za-z_]\w*)\s*:',r'\1"\2":',match.group(1))
                fixture=json.loads(literal)
                content=(json.dumps(fixture,ensure_ascii=False,indent=2)+'\n').encode()
                save(repo,content,'demo-match.json',repo['url']+'/blob/'+repo['sha']+'/'+path+'#L38',
                     seen,'Extracted static fixture')
        if repo['slug']=='s70241963-afk/Sushmitha':
            readme=git(checkout,'show',repo['sha']+':README.md').decode()
            links=re.findall(r'https://github\.com/user-attachments/files/\d+/[\w.-]+\.zip',readme)
            for url in links:
                with urlopen(url,timeout=90) as response:
                    archive=response.read(LIMIT+1)
                if len(archive)>LIMIT:raise RuntimeError('Attachment exceeds collection limit')
                with zipfile.ZipFile(io.BytesIO(archive)) as z:
                    total=0
                    for member in z.infolist():
                        if member.is_dir() or not candidate(member.filename):continue
                        total+=member.file_size
                        if total>LIMIT:raise RuntimeError('Attachment data exceeds collection limit')
                        content=z.read(member)
                        source=url+'#'+quote(member.filename,safe='/')
                        save(repo,content,member.filename,source,seen,'Starter ZIP sample')
        records.extend(seen.values())
    inventory={'path_base':'repository_root','collected_at':audit['checked_at'],'files':records,
               'method':'Original committed bytes; duplicates deduplicated within each repo. '
                        'VYBE static TS fixture extracted as JSON; starter ZIPs inspected without execution.'}
    (DATA/'datasets.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2)+'\n')
    print('Collected',len(records),'unique data files from',len({r['repo'] for r in records}),'repos.')


if __name__=='__main__':main()
