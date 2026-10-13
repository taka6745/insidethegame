#!/usr/bin/env python3
"""Generate competitor Markdown, metrics, CSV and SVG graphics from saved evidence."""

from collections import Counter
import csv
from datetime import datetime, timezone
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'competitors'
DATA = BASE / 'data'
COLORS = ['#69baff', '#73e3ae', '#f3c678', '#c2a4ff', '#fa9dac', '#78d6e5']
RULES = [
    ('Data normalisation', r'vendoriq|normalis|normaliz|vendor.format'),
    ('Accessible audio', r'blind|visually impaired|spatial audio|low.vision|accessib'),
    ('Fantasy engagement', r'fantasy'),
    ('Coaching & what-if', r'coach|what.if|simulat.*(alternative|decision)|half.time lab|decision.fit|teaches young'),
    ('Video & scouting', r'computer vision|scouting|training footage|image processing'),
    ('Conversational companion', r'conversational|conversation|talk to|ask questions|companion.*answers'),
    ('Narrative verification', r'narrative var|checks whether|audited|fact.check|checks evidence|human approval'),
    ('Broadcast production', r'broadcast|producer|studio|overlay|production'),
    ('Tactical analytics', r'momentum|pressure|possession|tactic|turning point|control.*chaos|fatigue|chasing|attacking patterns|opportunities'),
    ('Match event pipeline', r'generates match events'),
    ('Match replay', r'replay|replays|simulat.*match'),
    ('Match explanations', r'explain|explan|insights|match intelligence|football intelligence|commentary|stories|story|match events.*evidence|analyse teams'),
    ('Other project', r'pet.products|energy management'),
]
TAG_RULES = [
    ('Multi-agent', r'multi.agent|agents|crew'), ('Multilingual', r'multilingual|bilingual|languages|swahili'),
    ('Evidence-backed', r'evidence|verified|verifi|fact.check|audit'),
    ('Personalised', r'personali|persona|audience|viewer'), ('Replay', r'replay|playback'),
    ('Predictive / what-if', r'predict|forecast|what.if|simulat'),
    ('Broadcast overlays', r'overlay|broadcast graphics'), ('Azure', r'azure|foundry'),
]


def text(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def md(value):
    return escape(text(value), quote=False).replace('|', '&#124;').replace('[', '&#91;').replace(']', '&#93;')


def source_hash(project):
    fields = {key: project.get(key) for key in ['title', 'description', 'tagline']}
    return sha256(json.dumps(fields, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def classify(summary, description, title):
    if 'No clear project idea' in summary or 'no concrete project description' in summary:
        return 'Unspecified', []
    combined = ' '.join([summary, title])
    category = next((name for name, pattern in RULES if re.search(pattern, combined, re.I)), 'Unspecified')
    tags = [name for name, pattern in TAG_RULES if re.search(pattern, combined, re.I)]
    return category, tags


def fallback_summary(project):
    desc = text(re.sub(r'<[^>]+>', '', project.get('description') or ''))
    tagline = text(project.get('tagline'))
    candidate = tagline if len(tagline) > 20 else desc
    if not candidate or candidate.lower() in {'tbd', 'tba', 'more to come'}:
        return 'No clear project idea supplied yet.'
    return candidate[:220].rstrip() + ('…' if len(candidate) > 220 else '')


def svg_text(x, y, value, size=15, color='#edf5fa', extra=''):
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" {extra}>{escape(str(value))}</text>'


def graphic(title, subtitle, rows, filename):
    height = 116 + 34 * len(rows)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="{height}" '
             f'viewBox="0 0 1000 {height}" role="img" aria-labelledby="title desc">',
             f'<title id="title">{escape(title)}</title><desc id="desc">' +
             escape('; '.join(f'{name}: {count}' for name,count in rows)) + '</desc>',
             f'<rect width="1000" height="{height}" rx="14" fill="#101e2b"/>',
             '<g font-family="Arial, Helvetica, sans-serif">',
             svg_text(28, 36, title, 23, extra='font-weight="700"'),
             svg_text(28, 63, subtitle, 13, '#a4bbc9')]
    maximum = max([count for _,count in rows] + [1])
    for i, (label, count) in enumerate(rows):
        y = 88 + 34*i
        parts += [svg_text(28, y+18, label, 14),
                  f'<rect x="340" y="{y}" width="592" height="23" rx="4" fill="#192d3b"/>',
                  f'<rect x="340" y="{y}" width="{592*count/maximum:.2f}" height="23" '
                  f'rx="4" fill="{COLORS[i%len(COLORS)]}"/>',
                  svg_text(963, y+17, count, 14, extra='text-anchor="end" font-weight="700"')]
    parts += ['</g></svg>']
    (BASE/filename).write_text('\n'.join(parts)+'\n')


def overview_graphic(projects, repos, files, sampled_repos):
    parts=['<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="246" viewBox="0 0 1000 246" role="img" aria-labelledby="title desc">',
           '<title id="title">Inside the Game competitors</title>',
           f'<desc id="desc">{projects} projects, {repos} listed repositories, {files} data files from {sampled_repos} competitors.</desc>',
           '<rect width="1000" height="246" rx="14" fill="#101e2b"/>',
           '<g font-family="Arial, Helvetica, sans-serif">',
           svg_text(28,34,'INSIDE THE GAME / COMPETITORS',13,'#a4bbc9','letter-spacing="2" font-weight="700"')]
    for i,(value,label) in enumerate([(projects,'Projects'),(repos,'Listed repos'),(files,'Data files collected')]):
        x=28+i*324
        parts += [f'<rect x="{x}" y="56" width="296" height="138" rx="8" fill="#192d3b"/>',
                  f'<rect x="{x}" y="56" width="296" height="4" rx="2" fill="{COLORS[i]}"/>',
                  svg_text(x+20,124,value,52,COLORS[i],'font-weight="700"'),
                  svg_text(x+20,163,label,16)]
    parts += [svg_text(28,225,f'Sample data from {sampled_repos} competitors · daily refresh through 28 October 2026',13,'#a4bbc9'),'</g></svg>']
    (BASE/'overview.svg').write_text('\n'.join(parts)+'\n')


def review_for(repo, reviews):
    if repo['status'] != 'ok':
        return {'bucket': 'Unavailable', 'detail': 'GitHub returned 404; no source could be inspected.',
                'evidence': [], 'current': False}
    review = reviews.get(repo['slug'])
    if not review:
        return {'bucket': 'Needs review', 'detail': 'New repository; automatic references need source review.',
                'evidence': [], 'current': False}
    return {**review, 'current': review['sha'] == repo['sha']}


def main():
    projects = json.loads((DATA/'projects.json').read_text())
    audit = json.loads((DATA/'repositories.json').read_text())
    snapshot = json.loads((DATA/'snapshot.json').read_text())
    editorial = json.loads((DATA/'editorial.json').read_text())
    reviews = json.loads((DATA/'reviews.json').read_text())
    repos = {r.get('listed_url',r['url']).lower().removesuffix('.git'):r for r in audit['repositories']}
    # Also resolve originally listed aliases / casing to the audited canonical repository.
    from audit_repos import slug_from_url
    by_slug = {r['slug'].lower():r for r in audit['repositories'] if r['slug']}
    items = []
    for p in projects:
        saved = editorial.get(str(p['id']), {})
        unchanged = saved.get('source_hash') == source_hash(p)
        summary = saved['summary'] if unchanged else fallback_summary(p)
        name = saved.get('name',text(p['title'])) if unchanged else text(p['title'])
        category, tags = classify(summary, text(p.get('description')), text(p['title']))
        matches = [by_slug.get((slug_from_url(url) or '').lower()) or
                   repos.get(url.lower().removesuffix('.git')) for url in p.get('repoUrls', [])]
        items.append({'id':str(p['id']), 'name':name, 'summary':summary, 'category':category,
                      'tags':tags, 'repo_urls':p.get('repoUrls', []),
                      'repositories':[{k:r.get(k) for k in ['slug','url','commits','source_lines','loc_bucket','sha','status']} for r in matches if r],
                      'data_claim': 'Synthetic described' if re.search(r'synthetic|fictional|simulat',
                                     text(p.get('description'))+' '+text(p.get('tagline')),re.I)
                                    else 'Not specified'})
    items.sort(key=lambda p:(p['name'].casefold(),p['id']))
    type_counts = Counter(p['category'] for p in items)
    size_counts = Counter(r['loc_bucket'] for r in audit['repositories'])
    data_counts = Counter(review_for(r,reviews)['bucket'] if
                          (r['status']!='ok' or review_for(r,reviews)['current']) else
                          'Changed; re-review needed' for r in audit['repositories'])
    stamp = audit['checked_at'].replace('T',' ').split('+')[0]+' UTC'
    graphic('Project types', 'All submissions · inferred from project summaries and titles',
            type_counts.most_common(), 'types.svg')
    sizes = ['0','1–999','1k–4.9k','5k–14.9k','15k–49.9k','50k+','Unknown']
    graphic('Repository size', 'Nonblank source lines, including comments and tests · '+stamp,
            [(s,size_counts[s]) for s in sizes], 'loc.svg')
    graphic('Data sources', 'Source-reviewed repos · changed SHAs are flagged for re-review',
            data_counts.most_common(), 'data.svg')
    linked = sum(bool(p['repo_urls']) for p in items)
    graphic('Inside the Game · competitor snapshot',
            'Project export: '+snapshot['exported_at']+' · GitHub audit: '+stamp,
            [('Projects',len(items)), ('Projects with repo links',linked),
             ('Repos readable',sum(r['status']=='ok' for r in audit['repositories'])),
             ('Repo links unavailable',sum(r['status']!='ok' for r in audit['repositories']))], 'overview.svg')
    metrics = {'exported_at':snapshot['exported_at'], 'github_checked_at':audit['checked_at'],
               'projects':len(items), 'linked_projects':linked, 'unique_repos':len(audit['repositories']),
               'project_types':dict(type_counts), 'loc_buckets':dict(size_counts),
               'data_buckets':dict(data_counts), 'catalogue':items}
    (DATA/'metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2)+'\n')
    with (DATA/'catalogue.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f,lineterminator='\n');w.writerow(['id','name','category','tags','summary','repo_urls','data_claim'])
        for p in items:
            row=[p['id'],p['name'],p['category'],'; '.join(p['tags']),p['summary'],
                 '; '.join(p['repo_urls']),p['data_claim']]
            w.writerow(["'"+v if v.lstrip().startswith(('=','+','-','@')) else v for v in row])
    inventory=json.loads((DATA/'datasets.json').read_text())
    samples={}
    for sample in inventory['files']:
        samples.setdefault(sample['repo'],[]).append(sample)
    source_buckets=Counter()
    for r in audit['repositories']:
        review=review_for(r,reviews)
        if r['slug'] in samples:kind='Sample files collected'
        elif r['status']!='ok':kind='Cannot inspect'
        elif review['bucket'] in {'Synthetic generator','Synthetic scenarios'}:kind='Generator only'
        else:kind='Plans / starter app only'
        source_buckets[kind]+=1
    graphic('Data we actually collected','Files from source repos and starter ZIPs; static VYBE fixture extracted as JSON',
            source_buckets.most_common(),'data.svg')
    commit_counts=Counter('Unknown' if r['commits'] is None else
                          '1–5 commits' if r['commits']<=5 else
                          '6–20 commits' if r['commits']<=20 else
                          '21–50 commits' if r['commits']<=50 else '51+ commits'
                          for r in audit['repositories'])
    graphic('Repository activity','Default-branch history · '+stamp,
            [(b,commit_counts[b]) for b in ['1–5 commits','6–20 commits','21–50 commits','51+ commits','Unknown']],
            'commits.svg')
    metrics.update(data_files=len(inventory['files']),repos_with_samples=len(samples),
                   data_bytes=sum(f['bytes'] for f in inventory['files']),
                   collected_data_buckets=dict(source_buckets),commit_buckets=dict(commit_counts))
    (DATA/'metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2)+'\n')
    overview_graphic(len(items),len(audit['repositories']),len(inventory['files']),len(samples))
    root=f"""# Inside the Game

Research for our hackathon entry: the brief, the business opportunity, the competitors, and the data we can inspect.

→ [What should we build?](research/README.md) · [Working instructions for AI assistants](AGENTS.md)

![Research direction](research/opportunity.svg)

![Current competitor snapshot](competitors/overview.svg)

**{len(inventory['files'])} data files collected from {len(samples)} competitors.** The initial inspected samples are synthetic; no real match dataset or Kaggle/Hugging Face dataset use was verified.

→ [Competitors, repo activity, and their data](competitors/README.md) · [Raw project list](competitors/data/projects.json)

[GitHub Actions](https://github.com/taka6745/insidethegame/actions/workflows/competitors.yml) refreshes the list, metrics, data files, and graphics daily at **8 am Brisbane through 28 October 2026**. Expired login requests produce a visible failure and keep the last successful project export.
"""
    (ROOT/'README.md').write_text(root)
    report=['# Competitors','','[← Home](../README.md) · [Project JSON](data/projects.json) · [CSV](data/projects.csv)', '',
            '![Overview](overview.svg)','',
            f"**{len(inventory['files'])} files · {len(samples)} competitors with data · {metrics['data_bytes']/1_000_000:.1f} MB.**",'',
            'These samples are fictional match events, generated CSVs, vendor-shaped examples, and demo scenarios. '
            'No real match dataset or Kaggle/Hugging Face dataset use was verified in the initial readable repos.','',
            '## What they are building','','![Project types](types.svg)','',
            '## Repositories','','![Commits](commits.svg)','','![Code size](loc.svg)','',
            '| Project | What it does | Commits | LOC bucket | Data |',
            '| --- | --- | ---: | --- | --- |']
    names={}
    for p in items:
        for r in p['repositories']:names[r['slug']]=p
    for r in sorted(audit['repositories'],key=lambda r:names.get(r['slug'],{}).get('name',r['slug']).casefold()):
        p=names.get(r['slug'],{'name':r['slug'],'summary':'New repo; needs a closer look.'})
        review=review_for(r,reviews)
        files=samples.get(r['slug'],[])
        if files:label=f"[{len(files)} sample {'file' if len(files)==1 else 'files'}](data/{r['slug'].replace('/','__')}/)"
        elif r['status']!='ok':label='Cannot inspect'
        elif review['bucket'] in {'Synthetic generator','Synthetic scenarios'}:label='Generator only'
        elif review['bucket']=='Starter scaffold':label='No football data found'
        else:label='Planned only'
        if r['status']=='ok' and not review['current']:label+=' · review older'
        report.append(f"| [{md(p['name'])}]({r['url']}) | {md(p['summary'])} | "
                      f"{r['commits'] if r['commits'] is not None else 'Unknown'} | {r['loc_bucket']} | {label} |")
    report+=['','Commit and LOC numbers measure size and activity, not whether a product works. '
              'LOC counts nonblank source lines, including comments and tests, excluding bundled dependencies.','',
              '## Their data','','![Data collected](data.svg)','',
              '<details>','<summary>Open the collected files</summary>','',
              '| Competitor | File | Events / rows | Source |','| --- | --- | ---: | --- |']
    for f in inventory['files']:
        name=names.get(f['repo'],{}).get('name',f['repo'])
        label='/'.join(f['source_path'].split('/')[-3:])
        report.append(f"| {md(name)} | [{md(label)}](data/{f['file']}) | "
                      f"{f['records'] if f['records'] is not None else '—'} | [Original]({f['source_url']}) |")
    report+=['','</details>','','<details>','<summary>What data does each repo use?</summary>','',
              '| Project | Data source | Evidence |','| --- | --- | --- |']
    for r in audit['repositories']:
        review=review_for(r,reviews)
        evidence=' · '.join(f"[Source {i+1}]({r['url']}/blob/{review['sha']}/{e['path']}#L{e['line']})"
                          for i,e in enumerate(review['evidence']))
        if r['status']=='ok' and not review['current']:evidence='Older review · '+evidence
        report.append(f"| {md(names.get(r['slug'],{}).get('name',r['slug']))} | {md(review['detail'])} | {evidence or 'Unavailable'} |")
    report+=['','</details>','','<details>',
              f"<summary>Projects without a listed repo ({len(items)-linked})</summary>",'',
              '| Project | Type | What it does |','| --- | --- | --- |']
    for p in items:
        if not p['repo_urls']:
            url='https://innovationstudio.microsoft.com/hackathons/insidethegamedeveloperhackathon/project/'+p['id']
            report.append(f"| [{md(p['name'])}]({url}) | {md(p['category'])} | {md(p['summary'])} |")
    report+=['','</details>','','<details>','<summary>Refresh and measurement details</summary>','',
              f"Project export: **{snapshot['exported_at']}** · status: **{snapshot['refresh_status']}**. "
              f"GitHub checked: **{stamp}**.",'',
              'Types are inferred from what a project does. Commit counts include merges on the default branch. '
              'LOC includes comments and tests; dense single-line code counts as one line. '
              'Data-source reviews link to the SHA inspected; changed repos are flagged for re-review. '
              'Collected files retain original bytes and SHA-256 checksums in [datasets.json](data/datasets.json). '
              'VYBE is extracted from its static TypeScript fixture; ZIP samples are marked in the manifest.','',
              'Local refresh requires Python 3.12+, Git and an authenticated GitHub CLI. '
              'Keep copied requests in the ignored `.local/` directory.','',
              '```bash','python3 .github/scripts/refresh.py --search-request .local/search-request.txt \\',
              '  --detail-request .local/detail-request.txt','```','',
              'The workflow uses encrypted `INNOVATION_SEARCH_CURL` and `INNOVATION_DETAIL_CURL` secrets. '
              'Replace them with fresh copied requests if the session expires. Manual runs remain available after 28 October.','',
              '[Refresh scripts](../.github/scripts/) · [Structured metrics](data/metrics.json) · '
              '[Reviewed sources](data/reviews.json) · [GitHub audit](data/repositories.json)','', '</details>','']
    (BASE/'README.md').write_text('\n'.join(report))
    print('Generated two READMEs, metrics, CSV and five SVG graphics.')


if __name__ == '__main__':
    main()
