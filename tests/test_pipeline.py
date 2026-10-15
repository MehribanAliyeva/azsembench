import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
from build_azsembench import load_pairs, missing_pairs, open_cache, ingest, request_body, pair_key, run
from build_final_benchmark_from_cache import build, load_translation_cache
from audit_core_and_translation_dataset import audit_core, paraphrase_status, sts_status


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cache_path = self.root / 'cache.sqlite'
        self.conn = open_cache(self.cache_path)
        self.items = [{'sentence1_en': 'A cat sleeps.', 'sentence2_en': 'A cat is asleep.', 'label': '4.0', 'task': 'semantic_similarity'},
                      {'sentence1_en': 'A dog chases a cat.', 'sentence2_en': 'A cat chases a dog.', 'label': '0', 'task': 'paraphrase_detection'}]

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def response(self, cid='pair-0', items=None):
        items = self.items if items is None else items
        values = [{'id': i, 'sentence1_az': 'Pişik yatır.' if i == 0 else 'İt pişiyi qovur.',
                   'sentence2_az': 'Pişik yuxudadır.' if i == 0 else 'Pişik iti qovur.'} for i in range(len(items))]
        return json.dumps({'custom_id': cid, 'response': {'status_code': 200,
                'body': {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps({'translations': values})}]}]}}})

    def test_cache_reuses_historical_hashes_and_is_idempotent(self):
        manifest = {'pair-0': self.items}
        output = self.response()
        self.assertEqual(ingest(output, manifest, self.conn, 'test', 'v2'), (2, []))
        self.conn.execute("UPDATE pair_translations SET cache_key='legacy' WHERE task='semantic_similarity'")
        self.conn.commit()
        pairs = {pair_key(i): i for i in self.items}
        self.assertEqual(missing_pairs(pairs, self.conn), {})
        ingest(output, manifest, self.conn, 'test', 'v2')
        self.assertEqual(missing_pairs(pairs, self.conn), {})

    def test_bad_ids_and_partial_output_retry_only_missing(self):
        record = json.loads(self.response())
        record['response']['body']['output'][0]['content'][0]['text'] = json.dumps({'translations': [{'id': 0, 'sentence1_az': 'a', 'sentence2_az': 'b'}]})
        n, errors = ingest(json.dumps(record), {'pair-0': self.items}, self.conn, 'test', 'v2')
        self.assertEqual(n, 0); self.assertEqual(len(errors), 1)
        output = self.response('good', self.items[:1])
        n, errors = ingest(output, {'good': self.items[:1], 'missing': self.items[1:]}, self.conn, 'test', 'v2')
        self.assertEqual(n, 1); self.assertEqual(errors[0]['custom_id'], 'missing')
        self.assertEqual(len(missing_pairs({pair_key(i): i for i in self.items}, self.conn)), 1)

    def test_labels_not_sent_and_original_file_not_modified(self):
        body = request_body(self.items, 'test', 1024)
        payload = json.loads(body['input'])
        self.assertNotIn('label', payload[0]); self.assertNotIn('task', payload[0])
        source = self.root / 'source.csv'
        pd.DataFrame(self.items).to_csv(source, index=False)
        before = source.read_bytes()
        self.assertEqual(len(load_pairs([source, source])), 2)
        self.assertEqual(source.read_bytes(), before)

    def test_reviewed_override_then_audit(self):
        ingest(self.response(), {'pair-0': self.items}, self.conn, 'test', 'v2')
        src = pd.DataFrame(self.items)
        src['source_dataset'] = ['sts-b', 'paws-wiki']; src['split'] = 'test'; src['original_id'] = ['0', '1']
        source = self.root / 'source.csv'; src.to_csv(source, index=False)
        review = src.iloc[[1]].copy(); review['sentence1_az'] = 'Eyni'; review['sentence2_az'] = 'Eyni'
        review['translation_model'] = 'review'; review['translation_version'] = 'edited'; review['translation_cached_at'] = ''
        overrides = self.root / 'overrides.csv'; review.to_csv(overrides, index=False)
        df = build(source, load_translation_cache(self.cache_path), overrides)
        audited = audit_core(df, 4.0)
        self.assertEqual(audited.pair_status.tolist(), ['OK', 'TRANSLATION_COLLAPSE_NEGATIVE'])
        self.assertEqual(audited.model_ready.tolist(), [True, False])

    def test_audit_preserves_valid_identical_positive(self):
        self.assertTrue(paraphrase_status('same', 'same', 'eyni', 'eyni', 1)['model_ready'])
        self.assertFalse(paraphrase_status('same', 'same', 'eyni', 'eyni', 0)['model_ready'])
        self.assertTrue(sts_status('eyni', 'eyni', 5, 4)['model_ready'])
        self.assertFalse(sts_status('eyni', 'eyni', 1, 4)['model_ready'])

    def args(self):
        return SimpleNamespace(state_dir=self.root / 'jobs', cache=self.cache_path, model='test', version='v2',
                               max_retries=2, pairs_per_request=1, requests_per_batch=2, max_output_tokens=1024,
                               once=True, poll_seconds=1)

    def test_resume_remote_job_and_collect_expired_partial(self):
        args = self.args(); created = []
        def create(**kwargs):
            created.append(kwargs)
            return SimpleNamespace(id='batch-1')
        batch = SimpleNamespace(id='batch-1', status='in_progress', output_file_id=None, error_file_id=None, errors=None)
        client = SimpleNamespace(files=SimpleNamespace(create=lambda **kw: SimpleNamespace(id='file-1'), content=lambda _id: SimpleNamespace(text=self.response('pair-0', self.items[:1]))),
                                 batches=SimpleNamespace(create=create, retrieve=lambda _id: batch))
        pairs = {pair_key(i): i for i in self.items}
        run(args, client, self.conn, pairs)
        run(args, client, self.conn, pairs)
        self.assertEqual(len(created), 1)
        batch.status = 'expired'; batch.output_file_id = 'out-1'
        run(args, client, self.conn, pairs)
        self.assertEqual(len(created), 1)
        self.assertEqual(len(missing_pairs(pairs, self.conn)), 1)
        state = json.loads((args.state_dir / 'state.json').read_text())
        self.assertIsNone(state['active']); self.assertEqual(state['failures'], 1)

    def test_failed_batches_stop_at_retry_limit(self):
        args = self.args(); args.once = False
        batch = SimpleNamespace(id='failed-1', status='failed', output_file_id=None, error_file_id=None, errors='invalid model')
        calls = []
        def create(**kwargs):calls.append(kwargs); return batch
        client = SimpleNamespace(files=SimpleNamespace(create=lambda **kw: SimpleNamespace(id='file-1')),
                                 batches=SimpleNamespace(create=create, retrieve=lambda _id: batch))
        with self.assertRaisesRegex(RuntimeError, 'Retry limit'):
            run(args, client, self.conn, {pair_key(i): i for i in self.items})
        self.assertEqual(len(calls), 2)

    def test_incomplete_responses_are_not_cached(self):
        record = json.loads(self.response()); record['response']['body']['status'] = 'incomplete'
        count, errors = ingest(json.dumps(record), {'pair-0': self.items}, self.conn, 'test', 'v2')
        self.assertEqual(count, 0); self.assertEqual(len(errors), 1)

    def test_interrupted_submission_recovers_receipt(self):
        args = self.args(); pairs = {pair_key(i): i for i in self.items}
        recovered = []
        def create(**kwargs):
            recovered.append(SimpleNamespace(id='remote-1', metadata=kwargs['metadata']))
            raise ConnectionError('Lost response after remote creation')
        batch = SimpleNamespace(id='remote-1', status='in_progress', output_file_id=None, error_file_id=None, errors=None)
        client = SimpleNamespace(files=SimpleNamespace(create=lambda **kw: SimpleNamespace(id='file-1')),
            batches=SimpleNamespace(create=create, retrieve=lambda _id: batch, list=lambda **kw: recovered))
        with self.assertRaises(ConnectionError):run(args, client, self.conn, pairs)
        self.assertIsNone(json.loads((args.state_dir / 'state.json').read_text())['active']['batch_id'])
        run(args, client, self.conn, pairs)
        self.assertEqual(len(recovered), 1)
        self.assertEqual(json.loads((args.state_dir / 'state.json').read_text())['active']['batch_id'], 'remote-1')

    def test_malformed_line_keeps_other_valid_responses(self):
        n, errors = ingest('invalid json\n'+self.response(), {'pair-0': self.items}, self.conn, 'test', 'v2')
        self.assertEqual(n, 2); self.assertEqual(len(errors), 1)


class NotebookTests(unittest.TestCase):
    def test_tokenizer_uses_fast_factory_without_recursion(self):
        import ast
        root = Path(__file__).resolve().parents[1]
        notebook = json.loads((root / 'notebooks/finetune_sts.ipynb').read_text())
        source = '\n'.join(''.join(c['source']) for c in notebook['cells'] if c['cell_type'] == 'code')
        source = '\n'.join(line for line in source.splitlines() if not line.startswith('%'))
        nodes = ast.parse(source).body
        function = next(n for n in nodes if isinstance(n, ast.FunctionDef) and n.name == 'load_tokenizer_robust')
        calls = []
        def from_pretrained(name, use_fast):
            calls.append((name, use_fast))
            if use_fast:raise ValueError('fast tokenizer unavailable')
            return 'slow'
        ns = {'AutoTokenizer': SimpleNamespace(from_pretrained=from_pretrained)}
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<notebook>', 'exec'), ns)
        self.assertEqual(ns['load_tokenizer_robust']('example'), 'slow')
        self.assertEqual(calls, [('example', True), ('example', False)])
        self.assertNotIn('interneuronai', source)

    def test_fast_threshold_matches_original_brute_force(self):
        import ast
        import numpy as np
        root = Path(__file__).resolve().parents[1]
        notebook = json.loads((root / 'notebooks/evaluate_paraphrase.ipynb').read_text())
        source = next(''.join(c['source']) for c in notebook['cells'] if 'def choose_threshold' in ''.join(c['source']))
        function = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'choose_threshold')
        ns = {'np': np}; exec(compile(ast.Module(body=[function], type_ignores=[]), '<threshold>', 'exec'), ns)
        rng = np.random.default_rng(42)
        for size in [1, 2, 10, 100]:
            for _ in range(20):
                y = rng.integers(0, 2, size); scores = rng.integers(0, 10, size) / 10
                unique = np.unique(scores)
                candidates = unique if len(unique) == 1 else np.r_[unique[0]-1e-6, (unique[:-1]+unique[1:])/2, unique[-1]+1e-6]
                best_t, best_f, best_a = None, -1., -1.
                for t in candidates:
                    pred = scores >= t
                    tp = np.sum((y == 1) & pred); fp = np.sum((y == 0) & pred); fn = np.sum((y == 1) & ~pred)
                    f = 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.
                    a = np.mean(pred == y)
                    if f > best_f or (np.isclose(f, best_f) and a > best_a):best_t, best_f, best_a = float(t), float(f), float(a)
                self.assertEqual(ns['choose_threshold'](y, scores), (best_t, best_f))


if __name__ == '__main__':
    unittest.main()
