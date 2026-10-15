#!/usr/bin/env python3
"""Join original source snapshots with cached translations and reviewed overrides.

This step is offline and never calls a translation API. Audit the outputs with
``audit_core_and_translation_dataset.py`` to regenerate model_ready files.
"""
from __future__ import annotations
import argparse
import os
import sqlite3
from pathlib import Path

import pandas as pd
from config import env_path
from build_azsembench import clean

PAIR_KEYS = ['sentence1_en', 'sentence2_en', 'task', 'label_key']
REVIEW_KEYS = ['source_dataset', 'original_id', 'split', 'sentence1_en', 'sentence2_en', 'label_key']
METADATA = ['sentence1_az', 'sentence2_az', 'translation_model', 'translation_version', 'translation_cached_at']


def with_keys(df):
    df = df.copy()
    for col in ['sentence1_en', 'sentence2_en']:
        df[col] = df[col].map(clean)
    if 'task' not in df:
        df['task'] = 'paraphrase_detection'
    df['label_key'] = [str(float(v)) if t == 'semantic_similarity' else str(int(float(v))) for v, t in zip(df.label, df.task)]
    return df


def load_translation_cache(path):
    if not path.is_file():
        raise FileNotFoundError(path)
    with sqlite3.connect(f'file:{path.resolve()}?mode=ro', uri=True) as conn:
        cache = pd.read_sql_query('SELECT * FROM pair_translations', conn)
    cache = with_keys(cache).rename(columns={'model_name': 'translation_model', 'created_at': 'translation_cached_at'})
    for col in ['sentence1_az', 'sentence2_az']:
        cache[col] = cache[col].map(clean)
    cache = cache.sort_values('translation_cached_at').drop_duplicates(PAIR_KEYS, keep='last')
    return cache[PAIR_KEYS + METADATA]


def build(source_path, cache, reviewed_path=None):
    source = with_keys(pd.read_csv(source_path, dtype=str, keep_default_na=False))
    out = source.merge(cache, on=PAIR_KEYS, how='left', validate='many_to_one').fillna('')
    if reviewed_path and reviewed_path.is_file():
        reviewed = pd.read_csv(reviewed_path, dtype=str, keep_default_na=False)
        reviewed['task'] = reviewed.source_dataset.str.lower().map(lambda s: 'semantic_similarity' if 'sts' in s else 'paraphrase_detection')
        reviewed = with_keys(reviewed)
        if reviewed.duplicated(REVIEW_KEYS).any():
            raise ValueError(f'Duplicate reviewed keys in {reviewed_path}')
        reviewed['_reviewed'] = True
        out = out.merge(reviewed[REVIEW_KEYS + METADATA + ['_reviewed']], on=REVIEW_KEYS, how='left', suffixes=('', '_review'), validate='many_to_one')
        mask = out['_reviewed'].eq(True)
        for col in METADATA:
            out.loc[mask, col] = out.loc[mask, col + '_review']
        out = out.drop(columns=['_reviewed'] + [c + '_review' for c in METADATA])
        print(f'{source_path.name}: applied {int(mask.sum()):,} reviewed overrides')
    # Keep reviewed sentence text verbatim, including its original spacing.
    out['translation_complete'] = out.sentence1_az.ne('') & out.sentence2_az.ne('')
    out['translation_status'] = out.translation_complete.map({True: 'TRANSLATED', False: 'MISSING'})
    return out.drop(columns='label_key')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=env_path('TRANSLATION_CACHE', 'data/cache/translations_openai_gpt54_batch.sqlite'))
    parser.add_argument('--source-dir', type=Path, default=env_path('SOURCE_DIR', 'data/source'))
    parser.add_argument('--reviewed-dir', type=Path, default=env_path('REVIEWED_DIR', 'data/reviewed'))
    parser.add_argument('--output-dir', type=Path, default=env_path('BUILD_DIR', 'data/build'))
    parser.add_argument('--ignore-reviewed', action='store_true', help='Build from API cache only; omit the preserved snapshot corrections.')
    args = parser.parse_args()
    cache = load_translation_cache(args.cache)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, filename in [('core', 'azsembench_core.csv'), ('pawsx', 'pawsx_multilingual_with_az.csv')]:
        reviewed = None if args.ignore_reviewed else args.reviewed_dir / f'{name}_overrides.csv'
        df = build(args.source_dir / f'{name}.csv.gz', cache, reviewed)
        df.to_csv(args.output_dir / filename, index=False, encoding='utf-8-sig')
        print(f'{filename}: {len(df):,} rows; {int(df.translation_complete.sum()):,} translated')


if __name__ == '__main__':
    main()
