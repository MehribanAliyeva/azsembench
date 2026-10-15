#!/usr/bin/env python3
"""
Audit and filter:
  1) AzSemBench Core CSV = STS-B + PAWS-Wiki
  2) PAWS-X multilingual translation CSV produced by the benchmark builder

Expected PAWS-X wide format:
    source_dataset
    original_id
    split
    label
    label_type
    sentence1_en / sentence2_en
    sentence1_de / sentence2_de
    ...
    sentence1_az / sentence2_az
    translation_status
    translation_complete
    translation_flag
    pair_status
    issue_origin
    source_pair_equal
    az_pair_equal
    model_ready

The script RECOMPUTES model readiness from the actual current sentence columns,
so manually edited Azerbaijani translations are respected even if other metadata
columns are stale.

Rules
-----
CORE / STS-B:
    OK                                  -> keep
    IDENTICAL_AFTER_TRANSLATION_HIGH_STS -> keep
    INVALID_IDENTICAL_LOW_STS           -> exclude
    MISSING_TRANSLATION                 -> exclude

CORE / PAWS-Wiki:
    OK                                  -> keep
    SOURCE_IDENTICAL_POSITIVE           -> keep
    IDENTICAL_AFTER_TRANSLATION_POSITIVE -> keep
    SOURCE_IDENTICAL_NEGATIVE           -> exclude
    TRANSLATION_COLLAPSE_NEGATIVE       -> exclude
    UNASSESSED_MISSING_TRANSLATION      -> exclude

PAWS-X multilingual translation file:
    Same paraphrase rules as PAWS-Wiki, based on EN source vs AZ translation.

Default STS threshold = 4.0.

Example
-------
python audit_core_and_translation_dataset.py \
    --core data/build/azsembench_core.csv \
    --translation data/build/pawsx_multilingual_with_az.csv \
    --out-dir data/model_ready
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd
from config import env_path


# ---------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------

def clean_text(value) -> str:
    if value is None or pd.isna(value):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def normalized_text(value) -> str:
    text = clean_text(value).lower()
    text = re.sub(r"[“”\"'`´]", "", text)
    text = re.sub(r"[.,!?;:()\[\]{}]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def has_text(value) -> bool:
    return bool(clean_text(value))


# ---------------------------------------------------------------------
# Status rules
# ---------------------------------------------------------------------

def core_task(row: pd.Series) -> str:
    task = clean_text(row.get("task", "")).lower()
    source_dataset = clean_text(row.get("source_dataset", "")).lower()
    label_type = clean_text(row.get("label_type", "")).lower()

    if "semantic_similarity" in task or "similarity" in task:
        return "semantic_similarity"
    if "paraphrase" in task:
        return "paraphrase_detection"
    if "sts" in source_dataset:
        return "semantic_similarity"
    if "paws" in source_dataset:
        return "paraphrase_detection"
    if "regression" in label_type:
        return "semantic_similarity"
    if "binary" in label_type:
        return "paraphrase_detection"

    raise ValueError(
        "Could not determine task for core row. "
        f"task={row.get('task')!r}, source_dataset={row.get('source_dataset')!r}"
    )


def paraphrase_status(
    sentence1_en,
    sentence2_en,
    sentence1_az,
    sentence2_az,
    label,
):
    en1 = clean_text(sentence1_en)
    en2 = clean_text(sentence2_en)
    az1 = clean_text(sentence1_az)
    az2 = clean_text(sentence2_az)

    complete = bool(az1 and az2)
    source_equal = bool(en1 and en2) and normalized_text(en1) == normalized_text(en2)

    label = int(float(label))

    # Source issue can be identified even if AZ is missing.
    if source_equal and label == 0:
        return {
            "pair_status": "SOURCE_IDENTICAL_NEGATIVE",
            "issue_origin": "SOURCE",
            "source_pair_equal": True,
            "az_pair_equal": (
                complete and normalized_text(az1) == normalized_text(az2)
            ),
            "translation_complete": complete,
            "model_ready": False,
        }

    if source_equal and label == 1:
        return {
            "pair_status": "SOURCE_IDENTICAL_POSITIVE",
            "issue_origin": "SOURCE",
            "source_pair_equal": True,
            "az_pair_equal": (
                complete and normalized_text(az1) == normalized_text(az2)
            ),
            "translation_complete": complete,
            "model_ready": complete,
        }

    if not complete:
        return {
            "pair_status": "UNASSESSED_MISSING_TRANSLATION",
            "issue_origin": "NONE",
            "source_pair_equal": False,
            "az_pair_equal": False,
            "translation_complete": False,
            "model_ready": False,
        }

    az_equal = normalized_text(az1) == normalized_text(az2)

    if az_equal and label == 0:
        return {
            "pair_status": "TRANSLATION_COLLAPSE_NEGATIVE",
            "issue_origin": "TRANSLATION",
            "source_pair_equal": False,
            "az_pair_equal": True,
            "translation_complete": True,
            "model_ready": False,
        }

    if az_equal and label == 1:
        return {
            "pair_status": "IDENTICAL_AFTER_TRANSLATION_POSITIVE",
            "issue_origin": "TRANSLATION",
            "source_pair_equal": False,
            "az_pair_equal": True,
            "translation_complete": True,
            "model_ready": True,
        }

    return {
        "pair_status": "OK",
        "issue_origin": "NONE",
        "source_pair_equal": False,
        "az_pair_equal": False,
        "translation_complete": True,
        "model_ready": True,
    }


def sts_status(sentence1_az, sentence2_az, label, threshold: float):
    az1 = clean_text(sentence1_az)
    az2 = clean_text(sentence2_az)

    complete = bool(az1 and az2)

    if not complete:
        return {
            "pair_status": "MISSING_TRANSLATION",
            "issue_origin": "NONE",
            "source_pair_equal": False,
            "az_pair_equal": False,
            "translation_complete": False,
            "model_ready": False,
        }

    az_equal = normalized_text(az1) == normalized_text(az2)
    score = float(label)

    if not az_equal:
        return {
            "pair_status": "OK",
            "issue_origin": "NONE",
            "source_pair_equal": False,
            "az_pair_equal": False,
            "translation_complete": True,
            "model_ready": True,
        }

    if score >= threshold:
        return {
            "pair_status": "IDENTICAL_AFTER_TRANSLATION_HIGH_STS",
            "issue_origin": "TRANSLATION",
            "source_pair_equal": False,
            "az_pair_equal": True,
            "translation_complete": True,
            "model_ready": True,
        }

    return {
        "pair_status": "INVALID_IDENTICAL_LOW_STS",
        "issue_origin": "TRANSLATION",
        "source_pair_equal": False,
        "az_pair_equal": True,
        "translation_complete": True,
        "model_ready": False,
    }


# ---------------------------------------------------------------------
# Auditing
# ---------------------------------------------------------------------

def audit_core(df: pd.DataFrame, sts_threshold: float) -> pd.DataFrame:
    required = {
        "sentence1_en",
        "sentence2_en",
        "sentence1_az",
        "sentence2_az",
        "label",
    }
    missing = required - set(df.columns)
    if missing:
        raise RuntimeError(
            "Core dataset is missing columns: " + ", ".join(sorted(missing))
        )

    out = df.copy()
    results = []
    tasks = []

    for _, row in out.iterrows():
        task = core_task(row)
        tasks.append(task)

        if task == "semantic_similarity":
            result = sts_status(
                row["sentence1_az"],
                row["sentence2_az"],
                row["label"],
                sts_threshold,
            )
        else:
            result = paraphrase_status(
                row["sentence1_en"],
                row["sentence2_en"],
                row["sentence1_az"],
                row["sentence2_az"],
                row["label"],
            )

        results.append(result)

    out["recomputed_task"] = tasks

    for col in [
        "pair_status",
        "issue_origin",
        "source_pair_equal",
        "az_pair_equal",
        "translation_complete",
        "model_ready",
    ]:
        out[col] = [r[col] for r in results]

    # Compatibility with existing benchmark columns.
    out["translation_flag"] = out["pair_status"]

    return out


def audit_translation_dataset(df: pd.DataFrame) -> pd.DataFrame:
    """
    PAWS-X wide multilingual file.

    We only audit the English source pair against the Azerbaijani translation.
    Other original PAWS-X languages are preserved unchanged.
    """
    required = {
        "sentence1_en",
        "sentence2_en",
        "sentence1_az",
        "sentence2_az",
        "label",
    }
    missing = required - set(df.columns)
    if missing:
        raise RuntimeError(
            "Translation dataset is missing columns: "
            + ", ".join(sorted(missing))
        )

    out = df.copy()
    results = []

    for _, row in out.iterrows():
        results.append(
            paraphrase_status(
                row["sentence1_en"],
                row["sentence2_en"],
                row["sentence1_az"],
                row["sentence2_az"],
                row["label"],
            )
        )

    for col in [
        "pair_status",
        "issue_origin",
        "source_pair_equal",
        "az_pair_equal",
        "translation_complete",
        "model_ready",
    ]:
        out[col] = [r[col] for r in results]

    out["translation_flag"] = out["pair_status"]

    if "translation_status" in out.columns:
        out["translation_status"] = out["translation_complete"].map(
            {True: "TRANSLATED", False: "MISSING"}
        )

    return out


# ---------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------

def status_stats(df: pd.DataFrame, name: str) -> pd.DataFrame:
    total = len(df)

    group_cols = []
    for col in [
        "source_dataset",
        "recomputed_task",
        "split",
        "pair_status",
        "issue_origin",
        "model_ready",
    ]:
        if col in df.columns:
            group_cols.append(col)

    stats = (
        df.groupby(group_cols, dropna=False)
        .size()
        .reset_index(name="rows")
    )

    stats.insert(0, "dataset_file", name)
    stats["percent"] = stats["rows"] / total * 100 if total else 0.0

    return stats


def print_summary(df: pd.DataFrame, name: str):
    total = len(df)
    ready = int(df["model_ready"].astype(bool).sum())
    excluded = total - ready

    print("\n" + "=" * 78)
    print(name)
    print("=" * 78)
    print(f"Total rows:   {total:,}")
    print(f"Model-ready:  {ready:,} ({100 * ready / total:.2f}%)" if total else "Model-ready: 0")
    print(f"Excluded:     {excluded:,} ({100 * excluded / total:.2f}%)" if total else "Excluded: 0")

    print("\nStatus distribution:")
    counts = df["pair_status"].value_counts(dropna=False)
    for status, n in counts.items():
        pct = 100 * n / total if total else 0.0
        print(f"  {str(status):42s} {n:8,d}  {pct:7.2f}%")


# ---------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------

def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(
        path,
        dtype=object,
        keep_default_na=False,
        encoding="utf-8-sig",
    )


def save(df: pd.DataFrame, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def parse_args():
    p = argparse.ArgumentParser()

    p.add_argument(
        "--core",
        type=Path,
        default=env_path("BUILD_DIR", "data/build") / "azsembench_core.csv",
        help="AzSemBench Core CSV: STS-B + PAWS-Wiki.",
    )

    p.add_argument(
        "--translation",
        type=Path,
        default=env_path("BUILD_DIR", "data/build") / "pawsx_multilingual_with_az.csv",
        help="PAWS-X multilingual_with_az CSV produced by the builder.",
    )

    p.add_argument(
        "--out-dir",
        type=Path,
        default=env_path("MODEL_READY_DIR", "data/model_ready"),
    )

    p.add_argument(
        "--sts-threshold",
        type=float,
        default=4.0,
    )

    return p.parse_args()


def main():
    args = parse_args()

    core_path = args.core.expanduser().resolve()
    translation_path = args.translation.expanduser().resolve()
    out_dir = args.out_dir.expanduser().resolve()

    if not core_path.exists():
        raise FileNotFoundError(core_path)

    if not translation_path.exists():
        raise FileNotFoundError(translation_path)

    core_raw = read_csv(core_path)
    translation_raw = read_csv(translation_path)

    core = audit_core(core_raw, args.sts_threshold)
    translation = audit_translation_dataset(translation_raw)

    core_ready = core[core["model_ready"].astype(bool)].copy()
    translation_ready = translation[
        translation["model_ready"].astype(bool)
    ].copy()

    # Large diagnostic copies stay in the ignored build directory.
    audit_dir = env_path("BUILD_DIR", "data/build")
    audit_dir.mkdir(parents=True, exist_ok=True)
    save(core, audit_dir / "core_audited.csv.gz")
    save(translation, audit_dir / "pawsx_translation_audited.csv.gz")

    # Model-ready outputs
    save(core_ready, out_dir / "core_model_ready.csv")
    save(
        translation_ready,
        out_dir / "pawsx_translation_model_ready.csv",
    )

    # Statistics
    core_stats = status_stats(core, "core")
    translation_stats = status_stats(
        translation,
        "pawsx_translation",
    )

    save(core_stats, out_dir / "core_status_stats.csv")
    save(
        translation_stats,
        out_dir / "pawsx_translation_status_stats.csv",
    )

    combined_stats = pd.concat(
        [core_stats, translation_stats],
        ignore_index=True,
        sort=False,
    )
    save(
        combined_stats,
        out_dir / "all_translation_status_stats.csv",
    )

    print_summary(core, "AZSEMBENCH CORE (STS-B + PAWS-Wiki)")
    print_summary(
        translation,
        "PAWS-X MULTILINGUAL TRANSLATION DATASET",
    )

    print("\n" + "=" * 78)
    print("OUTPUT FILES")
    print("=" * 78)
    for name in [
        "core_model_ready.csv",
        "pawsx_translation_model_ready.csv",
        "core_status_stats.csv",
        "pawsx_translation_status_stats.csv",
        "all_translation_status_stats.csv",
    ]:
        print(out_dir / name)
    print(audit_dir / "core_audited.csv.gz")
    print(audit_dir / "pawsx_translation_audited.csv.gz")


if __name__ == "__main__":
    main()
