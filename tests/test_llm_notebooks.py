"""Exercise repository data loading without importing GPU libraries or downloading models."""
import contextlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


class LLMNotebookDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = pd.read_csv(ROOT / 'data/model_ready/core_model_ready.csv', dtype={'source_id': str}, low_memory=False)

    def test_loaders_use_azerbaijani_and_keep_original_partitions(self):
        # Source IDs repeat across PAWS partitions. This also checks globally
        # unambiguous prediction IDs and prevents STS examples entering PAWS.
        for path in sorted((ROOT / 'notebooks').glob('llm_*.ipynb')):
            with self.subTest(notebook=path.name):
                nb = json.loads(path.read_text())
                cells = [''.join(c['source']) for c in nb['cells'] if c['cell_type'] == 'code']
                loader = next(s for s in cells if 'raw = pd.read_csv(CSV_PATH' in s)
                ns = {'pd': SimpleNamespace(read_csv=lambda *a, **kw: self.data.copy(),
                                            to_numeric=pd.to_numeric, DataFrame=pd.DataFrame),
                      'CSV_PATH': 'unused', 'TRAIN_SUBSET_N': len(self.data) + 1,
                      'SEED': 42, 'SMOKE_TEST': False}
                with contextlib.redirect_stdout(io.StringIO()):
                    exec(compile(loader, str(path), 'exec'), ns)
                task = 'paraphrase_detection' if 'paws' in path.name else 'semantic_similarity'
                expected = self.data.loc[self.data.task.eq(task)]
                self.assertEqual(len(expected), len(ns['df']))
                self.assertFalse(ns['df']['id'].duplicated().any())
                self.assertEqual(ns['df'].sentence1.tolist(), expected.sentence1_az.tolist())
                self.assertEqual(ns['df'].sentence2.tolist(), expected.sentence2_az.tolist())
                ids = []
                for split in ['train', 'dev', 'test']:
                    frame = ns['full_train_df' if split == 'train' and task == 'paraphrase_detection'
                               else split + '_df']
                    self.assertEqual(len(frame), int(expected.split.eq(split).sum()))
                    self.assertTrue(frame['split'].eq(split).all())
                    ids.append(set(frame['id']))
                self.assertFalse(ids[0] & ids[1] or ids[0] & ids[2] or ids[1] & ids[2])

    def test_loader_rejects_missing_azerbaijani_instead_of_using_english(self):
        path = ROOT / 'notebooks/llm_paws_qwen.ipynb'
        nb = json.loads(path.read_text())
        loader = next(''.join(c['source']) for c in nb['cells']
                      if c['cell_type'] == 'code' and 'raw = pd.read_csv(CSV_PATH' in ''.join(c['source']))
        ns = {'pd': SimpleNamespace(read_csv=lambda *a, **kw: self.data.drop(columns='sentence1_az')),
              'CSV_PATH': 'unused'}
        with self.assertRaisesRegex(ValueError, 'Missing columns'):
            exec(compile(loader, str(path), 'exec'), ns)


if __name__ == '__main__':
    unittest.main()
