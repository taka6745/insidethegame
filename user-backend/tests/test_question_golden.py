"""The question golden set with scripted model decisions: the real question agent, planner,
compiler, rule engine and ETL-row answers over the shipped recording and ETL's stat catalogue."""
import json
import sys
from pathlib import Path

import pytest

from benchmarks import question_inprocess

ROOT = Path(__file__).resolve().parents[2]
SUITE = json.loads(Path(question_inprocess.__file__).with_name('question_cases.json').read_text())


@pytest.mark.skipif(not ((ROOT / SUITE['recording']).exists() and (ROOT / 'etl/reference/catalogue.py').exists()),
                    reason='Run from the repository checkout')
def test_every_scripted_golden_case_passes(tmp_path, monkeypatch):
    output = tmp_path / 'report.json'
    monkeypatch.setattr(sys, 'argv', ['question_inprocess', '--agent', 'fixture', '--output', str(output)])
    question_inprocess.main()
    report = json.loads(output.read_text())
    scripted = [case['id'] for case in SUITE['cases'] if 'fixture' in case]
    assert [row['id'] for row in report['cases']] == scripted and len(scripted) >= 23
    assert [row['id'] for row in report['cases'] if not row['ok']] == []
