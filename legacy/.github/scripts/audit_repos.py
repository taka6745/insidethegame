#!/usr/bin/env python3
"""Read GitHub metadata and source without running competitor code (stdlib + git)."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
SOURCE_EXTENSIONS = {'.py', '.js', '.mjs', '.cjs', '.jsx', '.ts', '.tsx', '.cs', '.rs', '.go', '.dart',
                     '.java', '.kt', '.swift', '.c', '.h', '.cpp', '.hpp', '.css',
                     '.scss', '.html', '.vue', '.svelte', '.sh', '.ps1', '.bicep', '.sql'}
EXCLUDE_DIRS = {'.git', 'node_modules', 'vendor', 'build', '.next', 'coverage',
                'bin', 'obj', '.venv', 'venv', '__pycache__', '.agents', '.claude', '.ai'}
PATTERNS = {
    'Kaggle reference': r'kaggle\.com|\bkagglehub\b|\bkaggle\b',
    'Hugging Face reference': r'huggingface\.co|\bload_dataset\s*\(|\bhf_hub_download\s*\(',
    'StatsBomb reference': r'statsbomb|\bsb\.events\s*\(',
    'Other vendor reference': r'\bopta\b|wyscout|sportmonks|football-data\.org|api-football',
    'Synthetic generator candidate': r'\b(seedrandom|random\.Random|random\.seed|default_rng)\b|'
                                     r'(function|def|class|public|export|fn).{0,90}(generat|simulat)|'
                                     r'(generat|simulat).{0,90}(event|match|synthetic)',
    'Fixture / replay candidate': r'(readFile|read_text|json\.load|JSON\.parse|fetch\().{0,120}'
                                  r'(match|fixture|event|synthetic)|'
                                  r'(fixture|synthetic|replay).{0,100}\.(json|csv|jsonl)',
}


def slug_from_url(url):
    parsed = urlparse(url)
    parts = parsed.path.strip('/').split('/')
    if parsed.scheme != 'https' or parsed.hostname != 'github.com' or len(parts) != 2:
        return None
    slug = '/'.join(parts).removesuffix('.git')
    return slug if re.fullmatch(r'[\w.-]+/[\w.-]+', slug) else None


def api(path, token):
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'InsideTheGame-audit',
               'X-GitHub-Api-Version': '2022-11-28'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    for attempt in range(3):
        try:
            with urlopen(Request('https://api.github.com/' + path, headers=headers), timeout=45) as r:
                return json.load(r)
        except HTTPError as e:
            if e.code not in {429, 500, 502, 503, 504} or attempt == 2:
                raise RuntimeError('GitHub HTTP ' + str(e.code)) from None
        except (URLError, TimeoutError):
            if attempt == 2:
                raise RuntimeError('GitHub request timed out or failed') from None
        time.sleep(2 ** attempt)


def git(repo, *args):
    r = subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', '-C', str(repo), *args],
                       capture_output=True, timeout=120)
    if r.returncode:
        raise RuntimeError('Git read failed')
    return r.stdout


def loc_bucket(lines):
    if lines is None:
        return 'Unknown'
    if lines == 0:
        return '0'
    if lines < 1000:
        return '1–999'
    if lines < 5000:
        return '1k–4.9k'
    if lines < 15000:
        return '5k–14.9k'
    if lines < 50000:
        return '15k–49.9k'
    return '50k+'


def eligible_source(path):
    p = Path(path)
    return (p.suffix.lower() in SOURCE_EXTENSIONS and
            not any(part in EXCLUDE_DIRS for part in p.parts) and
            not re.search(r'\.min\.|\.g\.cs$|\.generated\.|\.d\.ts$|wwwroot/lib/|\.github/skills/', path))


def is_test(path):
    return bool(re.search(r'(^|/)(tests?|__tests__)(/|$)|[./_-](test|spec)[./_-]|Tests?\.cs$', path, re.I))


def inspect_repo(url, token, cache):
    slug = slug_from_url(url)
    result = {'url': url, 'listed_url': url, 'slug': slug, 'status': 'unavailable', 'commits': None,
              'source_lines': None, 'test_lines': None, 'loc_bucket': 'Unknown'}
    if not slug:
        return dict(result, error='Unsupported repository URL')
    try:
        meta = api('repos/' + slug, token)
        result.update(slug=meta['full_name'], url=meta['html_url'],
                      license=(meta.get('license') or {}).get('spdx_id'),
                      default_branch=meta['default_branch'], description=meta['description'])
        latest = api('repos/' + meta['full_name'] + '/commits?per_page=1&sha=' +
                     quote(meta['default_branch'], safe=''), token)
        sha = latest[0]['sha']
        result.update(sha=sha, last_commit_at=latest[0]['commit']['committer']['date'])
        target = cache / meta['full_name'].replace('/', '__')
        if not target.exists():
            command = ['git', '-c', 'core.hooksPath=/dev/null', '-c', 'credential.helper=',
                       'clone', '--bare', '--single-branch', '--branch', meta['default_branch'],
                       'https://github.com/' + meta['full_name'] + '.git', str(target)]
            r = subprocess.run(command, capture_output=True, timeout=180,
                               env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'})
            if r.returncode:
                raise RuntimeError('Repository clone failed (public HTTPS read)')
        else:
            git(target, 'fetch', 'origin', meta['default_branch'])
        # Pin both metrics and evidence to the same observed commit.
        git(target, 'cat-file', '-e', sha + '^{commit}')
        result['commits'] = int(git(target, 'rev-list', '--count', sha))
        tree = git(target, 'ls-tree', '-r', '-z', '-l', sha).split(b'\0')
        files, evidence, lines, test_lines, languages = [], [], 0, 0, Counter()
        per_signal = Counter()
        for item in tree:
            if not item:
                continue
            info, raw_path = item.split(b'\t', 1)
            mode, kind, blob, size = info.decode().split()
            path = raw_path.decode('utf-8', errors='replace')
            # Never follow symlinks/submodules; scan bounded UTF-8 blobs only.
            if kind != 'blob' or mode == '120000':
                continue
            size = int(size)
            files.append({'path': path, 'bytes': size})
            if size > 2_000_000 or any(p in EXCLUDE_DIRS for p in Path(path).parts) or re.search(r'wwwroot/lib/|\.github/skills/',path):
                continue
            suffix = Path(path).suffix.lower()
            source = eligible_source(path)
            if not source and suffix not in {'.md', '.txt', '.json', '.csv', '.yaml', '.yml'}:
                continue
            content = git(target, 'cat-file', 'blob', blob)
            if b'\0' in content[:8192]:
                continue
            text = content.decode('utf-8', errors='replace')
            if source:
                count = sum(bool(line.strip()) for line in text.splitlines())
                lines += count
                test_lines += count if is_test(path) else 0
                languages[suffix] += count
            for signal, pattern in PATTERNS.items():
                for number, line in enumerate(text.splitlines(), 1):
                    if len(line) > 800 or not re.search(pattern, line, re.I):
                        continue
                    if re.search(r'api[_-]?key|authorization|bearer\s|token\s*[:=]|password', line, re.I):
                        continue
                    # Candidate references are never labelled as verified dataset use.
                    if per_signal[signal] >= 12:
                        break
                    evidence.append({'signal': signal, 'path': path, 'line': number,
                                     'source_code': source and not is_test(path),
                                     'url': meta['html_url'] + '/blob/' + sha + '/' +
                                            quote(path, safe='/') + '#L' + str(number)})
                    per_signal[signal] += 1
        result.update(status='ok', source_lines=lines, test_lines=test_lines,
                      app_lines=lines-test_lines, loc_bucket=loc_bucket(lines),
                      language_lines=dict(languages), files=files, evidence=evidence)
    except (RuntimeError, IndexError, KeyError, ValueError, subprocess.TimeoutExpired) as e:
        result.update(error=str(e) if isinstance(e, RuntimeError) else 'Repository inspection incomplete')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-dir', type=Path)
    args = parser.parse_args()
    projects = json.loads((ROOT/'competitors/data/projects.json').read_text())
    urls = sorted({url for p in projects for url in p.get('repoUrls', [])})
    token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if not token:
        token = subprocess.run(['gh', 'auth', 'token'], capture_output=True, text=True,
                               check=True).stdout.strip()
    with tempfile.TemporaryDirectory(prefix='insidethegame-repos-') as temp:
        cache = args.cache_dir or Path(temp)
        cache.mkdir(parents=True, exist_ok=True)
        with ThreadPoolExecutor(max_workers=4) as pool:
            records = list(pool.map(lambda url: inspect_repo(url, token, cache), urls))
    # Auth/rate-limit/service failures must not be presented as ordinary private repos.
    fatal = [r for r in records if r.get('error') and r['error'] != 'GitHub HTTP 404']
    if fatal:
        raise SystemExit('Audit failed: ' + '; '.join(r['slug'] + ': ' + r['error'] for r in fatal))
    output = {'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'commit_scope': 'all ancestors of the observed default-branch HEAD',
              'loc_method': 'nonblank source lines including comments and tests; excludes dependencies, '
                            'builds, generated declarations, lockfiles, datasets, and docs',
              'repositories': records}
    (ROOT/'competitors/data/repositories.json').write_text(json.dumps(output, indent=2) + '\n')
    print('Audited', len(records), 'repos;', sum(r['status']=='ok' for r in records), 'readable.')


if __name__ == '__main__':
    main()
