#!/usr/bin/env python3
"""Refresh snapshot file hashes/counts after intentionally replacing checked-in data."""
import argparse
import csv
import gzip
import hashlib
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot-date', help='Snapshot date YYYY-MM-DD; defaults to the existing manifest date.')
    args = parser.parse_args()
    path = ROOT / 'data/manifest.json'
    manifest = json.loads(path.read_text())
    if args.snapshot_date:
        manifest['snapshot_date'] = args.snapshot_date
    files = []
    for directory in ['data/source', 'data/reviewed', 'data/model_ready', 'results']:
        for file in sorted((ROOT / directory).rglob('*')):
            if not file.is_file():
                continue
            entry = {'path': str(file.relative_to(ROOT)), 'bytes': file.stat().st_size,
                     'sha256': hashlib.sha256(file.read_bytes()).hexdigest()}
            if file.name.endswith(('.csv', '.csv.gz')):
                opener = gzip.open if file.suffix == '.gz' else open
                with opener(file, 'rt', encoding='utf-8-sig', newline='') as handle:
                    reader = csv.reader(handle)
                    entry['columns'] = next(reader)
                    entry['rows'] = sum(1 for _ in reader)
            files.append(entry)
    cache = ROOT / 'data/cache/translations_openai_gpt54_batch.sqlite'
    with sqlite3.connect(f'file:{cache.resolve()}?mode=ro', uri=True) as conn:
        rows = conn.execute('SELECT COUNT(*) FROM pair_translations').fetchone()[0]
    files.append({'path': str(cache.relative_to(ROOT)), 'bytes': cache.stat().st_size,
                  'sha256': hashlib.sha256(cache.read_bytes()).hexdigest(), 'table': 'pair_translations', 'rows': rows})
    manifest['files'] = files
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(f'Updated {len(files)} files. Review provenance descriptions if the data source changed.')


if __name__ == '__main__':
    main()
