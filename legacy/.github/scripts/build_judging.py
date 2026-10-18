"""Render cached, source-limited judgements; queue only new or changed evidence.

This script never invents scores or calls a model. Agent reviews are immutable
records in judgements.json. Daily refreshes only reconcile their input versions.
"""
from collections import Counter
from hashlib import sha256
from html import escape
import json
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[2]
CRITERIA = {
    'technology': 'Technology', 'agent_innovation': 'Agent innovation',
    'impact': 'Impact', 'experience': 'Experience', 'category_fit': 'Category',
}
CORE = ['synthetic_truth', 'ingest_live', 'interpret', 'explain_why',
        'render_on_screen', 'personalise', 'live_narrative', 'automated_recap']
SIGNALS = {
    'player_identity': 'Player ID', 'player_speed_distance': 'Player speed',
    'pass_quality': 'Pass quality', 'ball_shot_speed': 'Ball speed',
    'video_auto_eventing': 'Video events', 'pressure_control_rhythm': 'Pressure',
    'player_club_modes': 'Player/club', 'analyst_casual_modes': 'Depth',
    'multilingual': 'Languages', 'synchronised_overlays': 'Timed overlay',
}
COVERAGE = set(CORE) | set(SIGNALS)
STATES = {'implemented', 'partial', 'specified', 'not_found', 'unknown'}


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(',', ':')).encode()).hexdigest()


def inputs(project, repo, rubric):
    # Include pitch, category/award and demo metadata, not fluctuating likes/views.
    description = {k: project.get(k) for k in
                   ['title', 'description', 'tagline', 'keywords', 'awards',
                    'videoData', 'executiveChallenge', 'repoUrls']}
    challenge = project.get('executiveChallenge') or {}
    # Exported cover images contain expiring signed URLs, unrelated to judging.
    description['executiveChallenge'] = {k: challenge.get(k) for k in ['id', 'name']}
    description['keywords'] = sorted(
        ({k: word.get(k) for k in ['key', 'name']} if isinstance(word, dict) else word
         for word in project.get('keywords') or []), key=lambda x: json.dumps(x, sort_keys=True))
    description['repoUrls'] = sorted({url.casefold().removesuffix('.git').rstrip('/')
                                      for url in project.get('repoUrls') or []})
    description['awards'] = sorted(project.get('awards') or [], key=lambda x: json.dumps(x, sort_keys=True))
    return {'project_id': str(project['id']), 'repository': repo['slug'].casefold(),
            'repository_sha': repo.get('sha'), 'description_sha256': digest(description),
            'rubric_version': rubric['version'], 'rules_sha': rubric['rules_sha'],
            'track': 'repository_evidence'}


def validate_record(record):
    assert record['input_key'] == digest(record['inputs']), 'Incorrect input fingerprint'
    assert record['assessment_id'] == digest({k: v for k, v in record.items()
                                            if k != 'assessment_id'}), 'Changed immutable review'
    assert set(record['criteria']) == set(CRITERIA), 'Missing named criterion'
    for criterion in record['criteria'].values():
        score = criterion['score']
        assert score is None or (type(score) is int and 0 <= score <= 5), 'Invalid score'
        assert criterion['rationale'] and criterion['uncertainty'], 'Missing judgement limits'
        assert criterion['evidence'] or score is None, 'Missing source evidence'
    assert set(record['coverage']) == COVERAGE, 'Missing description coverage'
    assert set(record['coverage'].values()) <= STATES, 'Invalid coverage state'
    assert record['reviewer_id'] and record['reviewed_at'] and record['name']


def assess(project, repo, ledger):
    current = inputs(project, repo, ledger['rubric'])
    key = digest(current)
    history = [r for r in ledger['assessments']
               if r['inputs']['project_id'] == str(project['id']) and
               r['inputs']['repository'] == repo['slug'].casefold()]
    matches = [r for r in history if r['input_key'] == key]
    if repo['status'] != 'ok':
        return {'state': 'unavailable', 'input_key': key, 'inputs': current, 'records': []}
    return {'state': 'current' if matches else 'stale' if history else 'pending',
            'input_key': key, 'inputs': current, 'records': matches}


def latest_reviews(records):
    # Preserve every review, but only the latest round by each reviewer votes.
    latest = {}
    for r in sorted(records, key=lambda r: (r['reviewed_at'], r['round'])):
        latest[r['reviewer_id']] = r
    return list(latest.values())


def aggregate(records):
    latest = latest_reviews(records)
    scores, ranges = {}, {}
    for key in CRITERIA:
        values = [r['criteria'][key]['score'] for r in latest]
        if not values or any(v is None for v in values):
            scores[key], ranges[key] = None, None
        else:
            scores[key], ranges[key] = median(values), [min(values), max(values)]
    total = None if any(v is None for v in scores.values()) else 4 * sum(scores.values())
    return scores, total, ranges


def markdown(value):
    return escape(' '.join(str(value).split()), quote=False).replace('|', '&#124;').replace('[', '&#91;').replace(']', '&#93;')


def source_link(repo, evidence):
    from urllib.parse import quote
    path = quote(evidence['path'], safe='/')
    return f"https://github.com/{repo['slug']}/blob/{repo['sha']}/{path}#L{evidence['line']}"


def score_graph(rows, path):
    """Stack earned criterion points; keep incomplete assessments out of the ranking."""
    colours = ['#69baff', '#c2a4ff', '#73e3ae', '#f3c678', '#fa9dac']
    complete = sorted((r for r in rows if r['total'] is not None),
                      key=lambda r: (-r['total'], r['display_name'].casefold()))
    incomplete = sorted((r for r in rows if r['total'] is None),
                        key=lambda r: r['display_name'].casefold())
    width, left, plot, step = 1160, 350, 640, 38
    height = 198 + step * len(rows) + (40 if incomplete else 0)

    def label(x, y, value, size=14, colour='#e5edf4', extra=''):
        return f'<text x="{x}" y="{y}" fill="{colour}" font-size="{size}" {extra}>{escape(str(value))}</text>'

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
             '<title id="title">Public repository evidence scores</title>',
             '<desc id="desc">Stacked points from five equally weighted criteria. Incomplete assessments are separate; hatched points are unknown, not earned. No competitor code or demo was executed.</desc>',
             '<defs><pattern id="unknown" width="8" height="8" patternUnits="userSpaceOnUse"><path d="M-2,2 l4,-4 M0,8 l8,-8 M6,10 l4,-4" stroke="#64798b" stroke-width="2"/></pattern></defs>',
             f'<rect width="{width}" height="{height}" rx="14" fill="#101e2b"/>',
             '<g font-family="Arial, Helvetica, sans-serif">',
             label(24, 34, 'Public repository evidence · points out of 100', 23),
             label(24, 59, 'Source review, not tested performance or a prediction of winning. Each criterion contributes up to 20 points.', 13, '#a4bbc9')]
    for i, name in enumerate(CRITERIA.values()):
        x = 24 + i * 218
        parts += [f'<rect x="{x}" y="78" width="14" height="14" rx="2" fill="{colours[i]}"/>',
                  label(x + 22, 90, name, 13)]
    for tick in range(0, 101, 20):
        x = left + plot * tick / 100
        parts += [label(x, 122, tick, 12, '#a4bbc9', 'text-anchor="middle"'),
                  f'<line x1="{x}" x2="{x}" y1="132" y2="{height-46}" stroke="#263948" stroke-dasharray="2 6"/>']
    y = 142
    for group, title in [(complete, None), (incomplete, 'Incomplete / unavailable · not ranked')]:
        if not group:
            continue
        if title:
            parts += [f'<rect x="16" y="{y}" width="{width-32}" height="30" fill="#101e2b"/>', label(24, y + 20, title, 14, '#a4bbc9')]
            y += 40
        for row in group:
            name = row['display_name']
            shown = name if len(name) <= 40 else name[:37] + '…'
            parts += ['<g>', f'<title>{escape(name)}</title>', label(24, y + 19, shown)]
            known = [v for v in row['scores'].values() if v is not None]
            if not known:
                status = 'Unscored' if row['state'] == 'current' else row['state'].capitalize()
                parts.append(label(left, y + 19, status, 13, '#a4bbc9'))
            else:
                x = left
                for i, key in enumerate(CRITERIA):
                    score = row['scores'][key]
                    if score is None:
                        continue
                    points = 4 * score
                    span = plot * points / 100
                    parts += [f'<g><title>{escape(CRITERIA[key])}: {points:g}/20</title>',
                              f'<rect x="{x:g}" y="{y}" width="{span:g}" height="27" fill="{colours[i]}"/>', '</g>']
                    if points >= 8:
                        parts.append(label(x + span / 2, y + 19, f'{points:g}', 12, '#0f172a', 'text-anchor="middle"'))
                    x += span
                missing = sum(v is None for v in row['scores'].values())
                if missing:
                    span = plot * missing / 5
                    parts += [f'<rect x="{x:g}" y="{y}" width="{span:g}" height="27" fill="url(#unknown)"/>',
                              label(1010, y + 19, f'{4*sum(known):g} known + ?', 13, '#a4bbc9')]
                else:
                    parts.append(label(x + 10, y + 19, f"{row['total']:g}", 15, '#e5edf4', 'font-weight="700"'))
            parts.append('</g>')
            y += step
    parts += [label(24, height - 20, 'Hatching shows the possible 0–20 points per unscored criterion; it is not an awarded score.', 12, '#a4bbc9'), '</g></svg>']
    path.write_text('\n'.join(parts) + '\n')


def heatmap(rows, path, coverage=False):
    columns = SIGNALS if coverage else CRITERIA
    width, row_height = 1160, 36
    height = 140 + row_height * len(rows)
    cell = (width - 370) / len(columns)
    def label(x, y, text, size=14, colour='#e5edf4', anchor='start'):
        return f'<text x="{x}" y="{y}" fill="{colour}" font-size="{size}" text-anchor="{anchor}">{escape(str(text))}</text>'
    title = 'Description signals · inspected source' if coverage else 'Public repository evidence · five equal criteria'
    subtitle = ('● implemented  ◐ partial  ◇ specified  — not found  ? unknown; suggestions are not extra points'
                if coverage else '0–5 per criterion; ? unknown. Source review, not a working-demo test or predicted judge score.')
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
             f'<title id="title">{escape(title)}</title><desc id="desc">{escape(subtitle)}</desc>',
             f'<rect width="{width}" height="{height}" rx="14" fill="#101e2b"/>',
             '<g font-family="Arial, Helvetica, sans-serif">', label(24, 32, title, 22), label(24, 57, subtitle, 12, '#a4bbc9')]
    for col, name in enumerate(columns.values()):
        parts.append(label(346 + col * cell + cell / 2, 92, name, 11, '#a4bbc9', 'middle'))
    colours = {'implemented': '#73e3ae', 'partial': '#f3c678', 'specified': '#c2a4ff',
               'not_found': '#718599', 'unknown': '#c0cbd5'}
    symbols = {'implemented': '●', 'partial': '◐', 'specified': '◇', 'not_found': '—', 'unknown': '?'}
    for i, row in enumerate(rows):
        y = 106 + i * row_height
        name = row['display_name']
        if len(name) > 38:
            name = name[:35] + '…'
        parts.append(label(24, y + 21, name))
        records = latest_reviews(row['records'])
        for col, key in enumerate(columns):
            x = 346 + col * cell
            if coverage:
                states = {r['coverage'][key] for r in records}
                state = next(iter(states)) if len(states) == 1 else 'unknown'
                value, colour = symbols[state], colours[state]
            else:
                score = row['scores'][key]
                value = '?' if score is None else f'{score:g}'
                colour = '#718599' if score is None else ['#718599', '#859baf', '#c2a4ff', '#69baff', '#73e3ae', '#f3c678'][int(score)]
            tip = row['repo']['slug'] + ': ' + key + ' = ' + str(value)
            parts += [f'<g><title>{escape(tip)}</title><rect x="{x+4}" y="{y}" width="{cell-8}" height="29" rx="4" fill="#192d3b"/>',
                      label(x + cell / 2, y + 21, value, 17, colour, 'middle'), '</g>']
    parts.append('</g></svg>')
    path.write_text('\n'.join(parts) + '\n')


def build(projects, audit, base, names=None):
    ledger = json.loads((base/'data/judgements.json').read_text())
    for record in ledger['assessments']:
        validate_record(record)
    rows, queue = [], []
    for repo in audit['repositories']:
        aliases = {repo['url'].casefold().removesuffix('.git'), repo.get('listed_url', repo['url']).casefold().removesuffix('.git')}
        for project in projects:
            if not any(url.casefold().removesuffix('.git') in aliases for url in project.get('repoUrls', [])):
                continue
            assessment = assess(project, repo, ledger)
            scores, total, ranges = aggregate(assessment['records'])
            row = {**assessment, 'project': project, 'repo': repo, 'scores': scores,
                   'display_name': (names or {}).get(str(project['id']), project['title']),
                   'total': total, 'ranges': ranges}
            rows.append(row)
            if assessment['state'] != 'current':
                queue.append({'project_id': str(project['id']), 'name': project['title'],
                              'repository': repo['slug'], 'state': assessment['state'],
                              'input_key': assessment['input_key'], 'inputs': assessment['inputs']})
    rows.sort(key=lambda r: (r['project']['title'].casefold(), r['repo']['slug']))
    (base/'data/review-queue.json').write_text(json.dumps({'rubric_version': ledger['rubric']['version'],
                                                       'entries': queue}, indent=2) + '\n')
    score_graph(rows, base/'judging.svg')
    heatmap(rows, base/'brief-coverage.svg', coverage=True)
    states = Counter(r['state'] for r in rows)
    lines = ['## Evidence scores', '',
             f"**{states['current']} current reviews · {states['stale'] + states['pending']} need review · {states['unavailable']} unavailable.** "
             'Each saved review names the project, repo, commit and reviewer. These are source-evidence scores; example-idea scores use a different scale.', '',
             '![Five judging criteria by repository](judging.svg)', '',
             '<details>', '<summary>Scores and each repo’s main gap</summary>', '',
             '| Project / pinned code | /100 | Main gap in the inspected evidence |',
             '| --- | ---: | --- |']
    for row in rows:
        repo, project, records = row['repo'], row['project'], row['records']
        url = repo['url'] + ('/tree/' + repo['sha'] if repo.get('sha') else '')
        score = f"{row['total']:g}" if row['total'] is not None else 'Incomplete' if records else row['state'].title()
        gap = ' / '.join(dict.fromkeys(r['main_gap'] for r in latest_reviews(records))) if records else 'No current assessment; see the review queue.'
        lines.append(f"| [{markdown(row['display_name'])}]({url}) | {score} | {markdown(gap)} |")
    lines += ['', '</details>', '']
    for key, name in CRITERIA.items():
        lines += ['<details>', f'<summary>{name} · scores and evidence</summary>', '',
                  'Each score is out of 5 (up to 20 weighted points). Unknown stays unscored.', '',
                  '| Project | /5 | Reviewer reasoning · pinned evidence |', '| --- | ---: | --- |']
        for row in rows:
            score = row['scores'][key]
            reasons = []
            for record in latest_reviews(row['records']):
                criterion = record['criteria'][key]
                label = markdown(record['reviewer_id'])
                if criterion['evidence']:
                    label = f"[{label}]({source_link(row['repo'], criterion['evidence'][0])})"
                reasons.append(f"{label}: {markdown(criterion['rationale'])}")
            value = '?' if score is None else f'{score:g}'
            lines.append(f"| {markdown(row['display_name'])} | {value} | {'<br>'.join(reasons) or 'No current assessment.'} |")
        lines += ['', '</details>', '']
    lines += ['<details>', '<summary>Brief coverage, scoring method and named review evidence</summary>', '',
              '![Coverage of the description’s specific suggestions](brief-coverage.svg)', '',
              '**Core path:** coherent synthetic data → live ingestion → interpretation → explanation → screen → personalisation; live stories and recaps. '
              'Every review also records these eight core checks. Suggested features receive explicit coverage, not bonus points.', '',
              '| Stable criterion | 20% each · evidence assessed |', '| --- | --- |',
              '| `technology` | Synthetic-data design, Microsoft use, maintainability and correctness. |',
              '| `agent_innovation` | Useful AI decisions; orchestration, MCP or collaboration; improvement over a simpler approach. |',
              '| `impact` | Important problem, production applicability, developer/business/user benefit; fan and League value separately examined. |',
              '| `experience` | Live user journey, UI/backend, personalisation and presentation. Demo execution remains unverified. |',
              '| `category_fit` | Category-specific evidence; reviewer-inferred categories are labelled. |', '',
              '**Local anchors:** 0 absent in inspected material; 1 prose claim; 2 partial; 3 connected source; '
              '4 strong implementation plus inspectable results; 5 exceptional reproducible evidence. Unknown = `?`, never zero. '
              'Equal weighting follows the [official rules](https://github.com/microsoft/insidethegamehackathon/blob/' + ledger['rubric']['rules_sha'] + '/OFFICIAL%20RULES.md#6-judges--criteria); these anchors are ours.', '',
              '**Limits:** no competitor code was executed; test files are not passed tests, and demo availability/functionality was not tested. '
              'A missing feature today is not a final eligibility verdict. Inferred category fit is provisional. '
              'Scores are not win probabilities or comparable with unbuilt design potential.', '',
              '| Named assessment | T / A / I / U / C | Category basis | Evidence / challenge |',
              '| --- | --- | --- | --- |']
    for row in rows:
        for record in latest_reviews(row['records']):
            vector = '/'.join('?' if record['criteria'][k]['score'] is None else str(record['criteria'][k]['score']) for k in CRITERIA)
            anchors = []
            for k in CRITERIA:
                if record['criteria'][k]['evidence']:
                    anchors.append(f"[{CRITERIA[k]}]({source_link(row['repo'], record['criteria'][k]['evidence'][0])})")
            label = f"{row['repo']['slug']} @ {row['repo']['sha'][:7]} · {record['reviewer_id']} r{record['round']}"
            category = record['category']['name'] or 'Unknown'
            lines.append(f"| {markdown(label)} | {vector} | {markdown(category)} ({record['category']['basis']}) | {' · '.join(anchors)} |")
    lines += ['', '**Reuse:** unchanged repo SHA + submission description/category/demo metadata + rules + rubric → reuse. '
              'Only new/changed entries enter the [review queue](data/review-queue.json). Historical scores remain in '
              '[named records](data/judgements.json); stale scores are hidden from the current chart. '
              'Daily Actions updates the queue and visuals, **not** fresh AI judgements. A later agent review fills the queue.', '',
              'Independent challengers inspect cited source and preserve disagreements in the record. '
              'Multiple reviewer scores use per-criterion medians; unknowns prevent a total. Related-model reviewers can share biases.', '',
              '</details>', '']
    return '\n'.join(lines)
