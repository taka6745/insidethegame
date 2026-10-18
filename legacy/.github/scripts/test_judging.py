import copy
from pathlib import Path
import tempfile
import unittest

from build_judging import CRITERIA, SIGNALS, aggregate, assess, digest, heatmap, inputs, score_graph


class JudgingTests(unittest.TestCase):
    def setUp(self):
        self.project = {'id': '42', 'title': 'Example', 'description': 'Pitch',
                        'repoUrls': ['https://github.com/a/b']}
        self.repo = {'slug': 'a/b', 'sha': 'abc', 'status': 'ok'}
        self.ledger = {'rubric': {'version': 'v2', 'rules_sha': 'rules'}, 'assessments': []}
        evidence = inputs(self.project, self.repo, self.ledger['rubric'])
        self.record = {'inputs': evidence, 'input_key': digest(evidence),
                       'reviewer_id': 'judge-1', 'round': 1, 'reviewed_at': '2026-10-13',
                       'criteria': {k: {'score': 3} for k in CRITERIA}}
        self.ledger['assessments'].append(self.record)

    def test_reuses_unchanged_and_ignores_social_counters(self):
        project = {**self.project, 'commentCount': 999, 'memberCount': 4}
        self.assertEqual(assess(project, self.repo, self.ledger)['state'], 'current')

    def test_new_project_does_not_invalidate_existing_review(self):
        new = {**self.project, 'id': '43'}
        self.assertEqual(assess(new, self.repo, self.ledger)['state'], 'pending')
        self.assertEqual(assess(self.project, self.repo, self.ledger)['records'], [self.record])

    def test_expiring_image_urls_and_unordered_tags_do_not_invalidate_scores(self):
        before = {**self.project, 'executiveChallenge': {'id': 1, 'name': 'Multi-agent',
                  'imageSrc': {'mediaData': {'image_url': 'image?st=1&se=2&sig=old'}}},
                  'keywords': [{'key': 'a', 'name': 'Azure'}, {'key': 'b', 'name': 'AI'}]}
        after = copy.deepcopy(before)
        after['executiveChallenge']['imageSrc']['mediaData']['image_url'] = 'image?st=3&se=4&sig=new'
        after['keywords'].reverse()
        after['repoUrls'] = ['https://github.com/A/B.git']
        self.assertEqual(inputs(before, self.repo, self.ledger['rubric']),
                         inputs(after, self.repo, self.ledger['rubric']))
        after['executiveChallenge']['name'] = 'Different category'
        self.assertNotEqual(inputs(before, self.repo, self.ledger['rubric']),
                            inputs(after, self.repo, self.ledger['rubric']))

    def test_code_pitch_demo_category_and_protocol_changes_go_stale(self):
        for field, value in [('description', 'new'), ('videoData', {'url': 'new'}),
                             ('awards', ['different category']), ('repoUrls', ['new'])]:
            self.assertEqual(assess({**self.project, field: value}, self.repo, self.ledger)['state'], 'stale')
        self.assertEqual(assess(self.project, {**self.repo, 'sha': 'def'}, self.ledger)['state'], 'stale')
        for field in ['version', 'rules_sha']:
            ledger = copy.deepcopy(self.ledger)
            ledger['rubric'][field] = 'new'
            self.assertEqual(assess(self.project, self.repo, ledger)['state'], 'stale')

    def test_unavailable_is_unscored_even_with_old_evidence(self):
        result = assess(self.project, {**self.repo, 'status': 'unavailable'}, self.ledger)
        self.assertEqual(result['state'], 'unavailable')
        self.assertEqual(result['records'], [])

    def test_unknown_never_becomes_zero_or_reweighted_total(self):
        self.record['criteria']['category_fit']['score'] = None
        scores, total, ranges = aggregate([self.record])
        self.assertIsNone(total)
        self.assertIsNone(scores['category_fit'])
        self.assertEqual(scores['technology'], 3)

    def test_revision_replaces_vote_not_history_and_preserves_dissent(self):
        newer = copy.deepcopy(self.record)
        newer['round'] = 2
        newer['criteria']['technology']['score'] = 1
        other = copy.deepcopy(self.record)
        other['reviewer_id'] = 'judge-2'
        scores, total, ranges = aggregate([self.record, newer, other])
        self.assertEqual(scores['technology'], 2)
        self.assertEqual(ranges['technology'], [1, 3])
        self.assertEqual(total, 56)

    def test_coverage_graph_shows_correction_instead_of_historical_disagreement(self):
        original = copy.deepcopy(self.record)
        original['coverage'] = dict.fromkeys(SIGNALS, 'implemented')
        corrected = copy.deepcopy(original)
        corrected['round'] = 2
        corrected['coverage'] = dict.fromkeys(SIGNALS, 'partial')
        row = {'display_name': 'Example', 'repo': self.repo,
               'records': [corrected, original]}
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)/'coverage.svg'
            heatmap([row], output, coverage=True)
            self.assertIn('player_identity = ◐', output.read_text())
            self.assertNotIn('player_identity = ?', output.read_text())

    def test_score_graph_separates_unknowns_from_earned_points(self):
        import xml.etree.ElementTree as ET
        scores = dict.fromkeys(CRITERIA, 4)
        rows = [
            {'display_name': 'Complete', 'scores': scores, 'total': 80, 'state': 'current'},
            {'display_name': 'Partial', 'scores': {**scores, 'impact': None}, 'total': None, 'state': 'current'},
            {'display_name': 'Missing', 'scores': dict.fromkeys(CRITERIA), 'total': None, 'state': 'unavailable'},
        ]
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)/'scores.svg'
            score_graph(rows, output)
            root = ET.fromstring(output.read_text())
            labels = list(root.itertext())
            self.assertIn('80', labels)
            self.assertIn('64 known + ?', labels)
            self.assertIn('Unavailable', labels)
            self.assertLess(labels.index('Complete'), labels.index('Incomplete / unavailable · not ranked'))
            rects = root.findall('.//{http://www.w3.org/2000/svg}rect')
            hatched = [r for r in rects if r.get('fill') == 'url(#unknown)']
            self.assertEqual(len(hatched), 1)
            self.assertEqual(float(hatched[0].get('width')), 128)  # One unknown 20-point criterion.
            earned = [r for r in rects if r.get('height') == '27' and r not in hatched]
            self.assertEqual(len(earned), 9)
            self.assertTrue(all(float(r.get('width')) == 102.4 for r in earned))


if __name__ == '__main__':
    unittest.main()
