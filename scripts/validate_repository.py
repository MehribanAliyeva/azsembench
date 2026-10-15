#!/usr/bin/env python3
"""Validate notebook syntax/metadata and GitHub file size without executing models."""
import ast
import hashlib
import json
from pathlib import Path

import nbformat

ROOT = Path(__file__).resolve().parents[1]


def main():
    for path in sorted((ROOT / 'notebooks').glob('*.ipynb')):
        nb = nbformat.read(path, as_version=4)
        nbformat.validate(nb)
        for i, cell in enumerate(nb.cells):
            if cell.cell_type != 'code':
                continue
            assert not cell.outputs and cell.execution_count is None, f'{path}: stored outputs'
            source = '\n'.join(line for line in cell.source.splitlines() if not line.startswith(('%', '!')))
            ast.parse(source, filename=f'{path.name}:cell {i}')
        print(f'Validated: {path.name}')
    for path in ROOT.glob('*.py'):
        ast.parse(path.read_text(), filename=str(path))
    for directory in ['data', 'results']:
        for path in (ROOT / directory).rglob('*'):
            if path.is_file() and 'build' not in path.parts and 'batch_jobs' not in path.parts:
                assert path.stat().st_size < 100 * 1024**2, f'GitHub file too large: {path}'
    manifest_path = ROOT / 'data/manifest.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        for item in manifest['files']:
            path = ROOT / item['path']
            assert hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256'], f'Changed snapshot: {path}'
    print('Python syntax, notebook structure, snapshot hashes and file sizes passed.')


if __name__ == '__main__':
    main()
