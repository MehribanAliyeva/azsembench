# AzSemBench

AzSemBench is an Azerbaijani sentence-pair benchmark for semantic textual similarity (STS) and paraphrase detection. English STS-B, PAWS-Wiki and PAWS-X sentences were translated into Azerbaijani, then filtered with explicit translation and pair-consistency checks. Original labels and splits are retained. The repository includes the model-ready datasets, their source snapshots and translation provenance, evaluation and fine-tuning notebooks, and supplied experiment results.

## Repository contents

| Path | Purpose |
|---|---|
| `data/model_ready/core_model_ready.csv` | Azerbaijani STS-B and PAWS-Wiki used by all four notebooks |
| `data/model_ready/pawsx_translation_model_ready.csv` | PAWS-X multilingual rows with usable Azerbaijani translations |
| `data/model_ready/*status_stats.csv` | Counts of retained and excluded rows by reason |
| `data/source/core.csv.gz`, `pawsx.csv.gz` | Original source sentences, labels, IDs and splits extracted from the supplied project snapshot; no Azerbaijani translation columns |
| `data/cache/translations_openai_gpt54_batch.sqlite` | Existing translation cache that contributed to the dataset; new translations use the same table |
| `data/reviewed/*_overrides.csv` | Snapshot translations that differ from the cache, retained to reproduce the supplied dataset |
| `build_azsembench.py` | Resumable OpenAI Batch translation from source files to SQLite |
| `build_final_benchmark_from_cache.py` | Offline join of originals, cache and preserved overrides |
| `audit_core_and_translation_dataset.py` | Recompute readiness and write model-ready CSVs and statistics |
| `notebooks/` | Existing-model evaluation and fine-tuning workflows |
| `results/` | Supplied metrics and predictions, kept separate from future runs |
| `data/manifest.json` | File hashes, row counts and source/result provenance for this snapshot |

Runtime requests, audit copies and intermediate builds live in ignored directories. Model weights and checkpoints are generated under `outputs/` and are not committed. Large paraphrase predictions are gzip-compressed so every committed file stays below GitHub's per-file limit; pandas reads `.csv.gz` directly.

The `reviewed` directory is a provenance layer, not evidence of an independent human review. There are **42,108 core overrides** and **0 PAWS-X overrides**: they preserve differences found between the current project CSVs and the historical API cache. Overrides include the original pair, label, dataset, split and ID so they cannot accidentally attach to a different example. They take precedence over the API cache during rebuilding. Edit or remove an override explicitly to replace it with a new cached translation.

## Dataset snapshot

| Dataset/task | Train | Dev | Test | Total |
|---|---:|---:|---:|---:|
| STS-B / semantic similarity | 5,749 | 1,500 | 1,378 | 8,627 |
| PAWS-Wiki / paraphrase detection | 49,301 | 7,991 | 4,980 | 62,272 |
| Core combined | 55,050 | 9,491 | 6,358 | 70,899 |
| PAWS-X / multilingual translation | 18,450 | 0 | 0 | 18,450 |

The original snapshot has 74,029 core rows and 53,401 PAWS-X rows. PAWS-X translation is incomplete, and the supplied model-ready snapshot contains training rows only. The notebooks evaluate **core**, not PAWS-X. Completing the remaining Batch translations and rebuilding can change these counts; saved results describe the supplied snapshot, not a future expanded dataset.

STS labels are continuous scores from 0 (unrelated) to 5 (equivalent). PAWS labels are binary: 1 denotes a paraphrase and 0 a non-paraphrase. PAWS deliberately contains sentence pairs with high word overlap but different meaning.

Audit rules remove missing translations; source-identical negative paraphrase pairs; negative paraphrase pairs that become identical after translation; and identical Azerbaijani STS pairs with gold score below 4.0. Identical positive paraphrases and identical STS pairs with score at least 4.0 are retained. Equality lowercases text and removes the punctuation defined in the audit script. These automated checks detect specific consistency issues, not every possible mistranslation.

Upstream datasets: [STS-B on Hugging Face](https://huggingface.co/datasets/mteb/stsbenchmark-sts), [PAWS-Wiki](https://huggingface.co/datasets/google-research-datasets/paws), [PAWS-X](https://huggingface.co/datasets/google-research-datasets/paws-x). The included source files preserve the project's actual input snapshot so offline rebuilding does not depend on changes to upstream datasets. Consult upstream dataset and model cards for attribution and use terms; no new license for third-party data is implied here.

## Local setup

Use Python 3.11 or 3.12, particularly for the model notebooks.

```bash
git clone https://github.com/MehribanAliyeva/azsembench.git
cd azsembench
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

On Windows activate with `.venv\Scripts\activate`. Add your own `OPENAI_API_KEY` to `.env` only if you will translate additional sentences. `.env` is ignored; `.env.example` contains no credentials. All local scripts read `.env` through `config.py`. Existing shell environment variables override `.env`, and command-line arguments override environment defaults. Paths configured in `.env` resolve relative to the repository.

The model notebooks download pretrained checkpoints from Hugging Face; they do not require an OpenAI key. A local `.env` with blank credentials is enough for offline dataset rebuilding.

## Translate originals in batches

Preview missing pairs without sending API requests:

```bash
python build_azsembench.py --dry-run
```

Translate all missing source pairs and keep collecting results until the cache is complete:

```bash
python build_azsembench.py
```

The default input is both `data/source/core.csv.gz` and `data/source/pawsx.csv.gz`. To use another original CSV:

```bash
python build_azsembench.py --csv path/to/original.csv --state-dir data/cache/batch_jobs_custom
```

Required columns are `sentence1_en`, `sentence2_en`, and `label`; include `task` (`semantic_similarity` or `paraphrase_detection`). When `task` is absent, `source_dataset` containing `sts` identifies STS; otherwise the script assumes paraphrase detection. Empty source sentences and invalid labels raise an error.

The script groups sentence pairs into requests (default 10 pairs), submits requests through OpenAI's `/v1/responses` Batch endpoint (default 100 requests per job), polls, validates returned IDs and translations, and commits successful pairs to SQLite. It submits the next job only after collecting the current job. Original files are never edited. Gold labels are used solely to identify cache entries and are **not sent to the translator**. Pair context is retained to preserve meaning-changing differences.

Completed cache entries are matched by source text, task and label, including historical cache hashes. Repeated source pairs are translated once and reused. The script reuses existing translations even if their model/version differs from the configured model; choose a separate `--cache` and `--state-dir` to make a new translation experiment.

`--once` submits or collects one job without waiting. Running the same command again resumes the saved job. Successful responses from expired/cancelled jobs are collected, and only missing pairs are retried. Missing, malformed, truncated and failed responses are logged under `data/cache/batch_jobs/`. Repeated failures stop at `MAX_RETRIES`; fix their cause before using `--reset-retries`. Model access and Batch token quotas depend on your account. Reduce `REQUESTS_PER_BATCH` or `PAIRS_PER_REQUEST` when necessary.

If submission is interrupted before its receipt is saved, the script looks for the remote job using its saved metadata. An ambiguous result stops with recovery instructions rather than submitting a duplicate job. Use only one running translator per state directory. Translation jobs incur API charges; `--dry-run`, cache joining, audits and repository tests do not call the API.

Environment settings are listed in `.env.example`. The implementation follows the [official OpenAI Batch API documentation](https://developers.openai.com/api/docs/guides/batch).

## Rebuild model-ready data offline

```bash
python build_final_benchmark_from_cache.py
python audit_core_and_translation_dataset.py
```

The builder writes `data/build/azsembench_core.csv` and `data/build/pawsx_multilingual_with_az.csv`. The audit writes the two model-ready CSVs and three status-statistics files under `data/model_ready/`; full audit copies stay under ignored `data/build/` as `.csv.gz`. Use `--ignore-reviewed` on the builder for a cache-only build. This intentionally differs from the supplied snapshot because the preserved overrides are omitted.

To inspect a new build without replacing the checked-in model-ready files:

```bash
python audit_core_and_translation_dataset.py --out-dir /tmp/azsembench-model-ready
```

`--core`, `--translation`, `--out-dir` and `--sts-threshold` customize the audit. The default STS identity threshold is 4.0. If you intentionally replace checked-in data, run `python scripts/update_manifest.py --snapshot-date YYYY-MM-DD` and update provenance descriptions in `data/manifest.json` before publishing it.

## Run the notebooks

| Notebook | Workflow |
|---|---|
| [evaluate_sts.ipynb](notebooks/evaluate_sts.ipynb) | Evaluate existing sentence encoders on STS; no weight updates; embedding and lexical scores |
| [evaluate_paraphrase.ipynb](notebooks/evaluate_paraphrase.ipynb) | Evaluate existing sentence encoders on PAWS-Wiki; choose a cosine threshold on dev F1 |
| [finetune_sts.ipynb](notebooks/finetune_sts.ipynb) | Fine-tune four multilingual cross-encoders with a 1-output STS regression head |
| [finetune_paws.ipynb](notebooks/finetune_paws.ipynb) | Fine-tune four multilingual cross-encoders for binary paraphrase classification; results pending |

Open the notebook in Colab or Kaggle, enable Internet and a GPU, then run every cell from top to bottom. The first code cell installs dependencies. Each notebook downloads `core_model_ready.csv` **from this repository itself**, using `https://raw.githubusercontent.com/MehribanAliyeva/azsembench/main/data/model_ready/core_model_ready.csv`. No dataset upload or Kaggle input is required. The initial publication must include that file before notebook downloads work.

For local execution:

```bash
python -m pip install -r requirements-notebooks.txt
jupyter lab
```

The notebook configuration reads `AZSEMBENCH_REPO` and `AZSEMBENCH_REF` from environment variables or `.env`. Set the ref to a commit SHA to reproduce a fixed dataset. The download cell prints the URL and SHA-256. `AZSEMBENCH_OUTPUT_DIR` overrides each notebook's default `outputs/<workflow>/` path. CSV results are linked at the end; model weights are not bundled into an automatic ZIP.

Existing STS models: `LocalDoc/az-en-MiniLM-L6-v2`, LaBSE, multilingual MPNet, multilingual E5-large. Paraphrase evaluation also includes multilingual MiniLM-L12-v2. E5 uses `query: ` on both sentences for symmetric similarity. Embeddings are L2-normalized.

Both fine-tuning notebooks use only `FacebookAI/xlm-roberta-base`, `google-bert/bert-base-multilingual-cased`, `distilbert/distilbert-base-multilingual-cased`, and `microsoft/mdeberta-v3-base`. Each encodes the sentence pair jointly. STS selects the best checkpoint by **dev Pearson**; PAWS selects by **dev F1**. Test is held out from checkpoint and threshold selection. Seed is 42; max sequence length is 192; learning rate is 2e-5; weight decay is 0.01; training batch size is 8 with 2 gradient-accumulation steps; evaluation batch size is 32. STS allows 5 epochs with early-stopping patience 2; PAWS allows 4 epochs with patience 1. These are the prepared notebook settings, not a recovered log of the supplied runs.

STS uses float32 regression loss and reports raw and clipped [0,5] predictions separately. Its tokenizer uses a fast implementation where available and falls back to a slow tokenizer. PAWS neural predictions use paraphrase probability at least 0.5. Its lexical baselines choose thresholds by dev F1, breaking ties by accuracy. Temporary checkpoints are deleted after saving the best model; CSV progress is saved after each model. Models run sequentially to limit GPU memory usage.

## Metrics and score functions

A score function computes a similarity per pair; an evaluation metric compares those scores or decisions with gold labels. A high surface-overlap score alone does not establish semantic equivalence.

### STS evaluation and regression

| Metric | Meaning | Better |
|---|---|---|
| Pearson `pearson` | Linear correlation between predicted and gold scores, range [-1,1] | Higher |
| Spearman `spearman` | Correlation of ranks, range [-1,1] | Higher |
| Kendall `kendall_tau` | Tau-b rank concordance accounting for ties, range [-1,1] | Higher |
| MSE `mse` | Mean squared prediction error in squared STS units | Lower |
| RMSE `rmse` | Square root of MSE, in STS score units | Lower |
| MAE `mae` | Mean absolute prediction error | Lower |
| Median absolute error | Median of absolute errors; less sensitive to outliers | Lower |
| R² `r2` | 1 minus residual squared error divided by gold-score variance sum; can be negative | Higher |
| Explained variance | 1 minus error variance divided by gold variance; does not penalize constant bias as R² does | Higher |
| Max error | Largest absolute prediction error | Lower |

Correlations are undefined (saved as blank/NaN) for constant predictions, constant labels, or fewer than two examples. Uncalibrated lexical and embedding similarities are not STS scores in [0,5], so their supplied evaluation reports correlations rather than regression errors. The fine-tuning notebook reports regression errors for neural outputs and correlations for lexical baselines.

The supplied fine-tuned STS CSV also reports `binary_*` metrics: both gold and predicted scores are converted to positive when they are **>=4.0**. This is an auxiliary high-similarity diagnostic, not the PAWS paraphrase task. The cleaned notebook retains it.

### Paraphrase and binary STS metrics

| Metric | Meaning | Better |
|---|---|---|
| Accuracy | Fraction of all decisions that are correct | Higher |
| Precision | TP / (TP + FP): correctness among predicted positives | Higher |
| Recall | TP / (TP + FN): fraction of actual positives found | Higher |
| F1 | Harmonic mean of precision and recall | Higher |
| Balanced accuracy | Mean recall of the two classes | Higher |
| MCC `mcc` | Matthews correlation of binary labels and predictions, range [-1,1] | Higher |
| ROC-AUC `roc_auc` | Ranking performance across thresholds; 0.5 is chance ranking | Higher |
| Average precision | Recall-weighted precision across score thresholds; summarizes the precision-recall curve | Higher |
| Brier score | Mean squared difference between predicted probability and binary label | Lower |
| TN / FP / FN / TP | True negatives, false positives, false negatives, true positives | Context |

Precision, recall and F1 use zero when a denominator is undefined. ROC-AUC and average precision are saved as NaN for single-class splits. PAWS fine-tuning also reports Pearson/Spearman/Kendall between positive-class scores and binary labels as diagnostics. Brier scores on lexical similarities are computed as a diagnostic using their [0,1] scores; those scores are not calibrated probabilities.

`threshold` is the decision cutoff, `selection_split` records where it was chosen, and `selection_metric` records the objective. Existing paraphrase evaluation maximizes dev F1 and uses accuracy to break ties, then fixes that threshold for train/test/overall. Because thresholds are tuned, this is pretrained-weight evaluation with dev calibration, not a label-free zero-shot experiment. Neural PAWS fine-tuning uses 0.5. `binary_threshold` in STS results is fixed at 4.0.

### Embedding similarities

For L2-normalized embeddings u and v, cosine is their dot product. `dot_product` is therefore identical to `cosine_similarity` here. `euclidean_similarity` is 1 / (1 + ||u-v||₂); `manhattan_similarity` is 1 / (1 + ||u-v||₁); `angular_similarity` is 1 - arccos(clipped cosine) / π. Higher values indicate greater similarity. Cosine, Euclidean and angular scores have the same mathematical ranking after normalization; floating-point ties can cause tiny differences in rank metrics. Their Pearson values can differ because the transformations are nonlinear.

### Lexical similarities

| Score | Definition |
|---|---|
| Normalized Levenshtein | 1 minus edit distance normalized by the longer string length |
| Jaro-Winkler | Character match/transposition similarity with a shared-prefix adjustment |
| SequenceMatcher ratio | Twice the matched character count divided by total string lengths |
| Token Jaccard | Size of token-set intersection / union |
| Token Dice | Twice intersection size / total token-set sizes |
| Token overlap coefficient | Intersection size / smaller token-set size |
| Char-3 / char-4 Jaccard | Jaccard overlap of character n-gram sets |

Token and n-gram baselines lowercase and use whitespace tokenization/character windows as implemented in the notebooks. String metrics use the cleaned original case. All lexical similarities range from 0 to 1. Set measures ignore duplicate tokens and most word-order information, making them useful diagnostics but limited on PAWS.

`n` is the number of evaluated pairs; `split` identifies train/dev/test/overall; `overall` pools splits and is descriptive, not a held-out estimate. `prediction_variant` distinguishes raw neural output, clipping and lexical surface scores. Training summaries record best dev metric, checkpoint path, elapsed seconds and training loss; train metrics are in-sample for fine-tuned models.

## Supplied results

Results are imported from the attached files, without retraining models or changing reported values. Use **test** for held-out comparisons. The original run environments, complete logs and fine-tuned weights were not supplied, so the prepared notebooks are executable workflows rather than a guarantee of bit-for-bit historical reproduction.

### Existing models: STS test (1,378 pairs, cosine)

| Model | Pearson | Spearman | Kendall τ |
|---|---:|---:|---:|
| LocalDoc az-en MiniLM | 0.7651 | 0.7731 | 0.5897 |
| LaBSE | 0.7181 | 0.7139 | 0.5311 |
| Multilingual MPNet | 0.7428 | 0.7482 | 0.5648 |
| Multilingual E5-large | 0.7688 | 0.7720 | 0.5855 |

E5 has the highest cosine Pearson; LocalDoc has the highest cosine Spearman. Among the supplied lexical baselines, char-3 Jaccard has the strongest test correlations (Pearson 0.6879, Spearman 0.6995). Other embedding score variants and every split are in [all STS metrics](results/semantic_similarity/semantic_similarity_all_metrics.csv). Pair-level embedding and lexical predictions are stored alongside it.

### Fine-tuned models: STS test (1,378 pairs)

| Model | Pearson | Spearman | Kendall τ | RMSE | MAE | R² | Binary F1 (>=4) |
|---|---:|---:|---:|---:|---:|---:|---:|
| XLM-RoBERTa-base | 0.8359 | 0.8275 | 0.6468 | 0.8452 | 0.6356 | 0.6929 | 0.5413 |
| Multilingual DistilBERT | 0.7872 | 0.7824 | 0.6012 | 0.9482 | 0.7151 | 0.6135 | 0.5618 |
| Multilingual BERT | 0.8099 | 0.7977 | 0.6174 | 0.8969 | 0.6751 | 0.6542 | 0.5600 |
| mDeBERTa-v3-base | 0.8666 | 0.8627 | 0.6890 | 0.7731 | 0.5759 | 0.7430 | 0.6688 |

mDeBERTa is strongest among the four supplied fine-tuned STS runs. Its Pearson exceeds the best supplied existing-model cosine Pearson by approximately 0.0978. This is a comparison of different systems, including different encoders and joint pair encoding; it is not a controlled estimate of the effect of fine-tuning alone.

[Fine-tuned STS metrics](results/sts_finetuned/sts_finetuned_all_metrics.csv) contain 12 rows (four models × three splits). This supplied CSV has no prediction-variant column, fine-tuned predictions, training logs, or additional regression/lexical metrics. The new notebook emits raw/clipped variants and additional diagnostics on future runs. The supplied values are not relabeled as either variant.

### Existing models: paraphrase test (4,980 pairs)

| Model | Dev threshold | Accuracy | Precision | Recall | F1 | ROC-AUC |
|---|---:|---:|---:|---:|---:|---:|
| Multilingual MiniLM-L12 | 0.7827 | 0.4484 | 0.4458 | 0.9901 | 0.6148 | 0.6540 |
| Multilingual MPNet | 0.8697 | 0.4532 | 0.4480 | 0.9896 | 0.6167 | 0.6786 |
| LaBSE | 0.8592 | 0.4450 | 0.4447 | 0.9986 | 0.6154 | 0.6459 |
| LocalDoc az-en MiniLM | 0.9102 | 0.4466 | 0.4452 | 0.9937 | 0.6149 | 0.6472 |
| Multilingual E5-large | 0.9197 | 0.4450 | 0.4446 | 0.9968 | 0.6149 | 0.6853 |

MPNet has the highest supplied test F1; E5 has the highest ROC-AUC. Recall is near 1 while precision and accuracy remain around 0.45: these dev-F1 thresholds produce many positive decisions, so F1 alone overstates the balance of performance on difficult negative pairs. Inspect accuracy, ROC-AUC and pair-level errors alongside F1.

[Paraphrase metrics](results/paraphrase_detection/paraphrase_detection_results.csv), [dev thresholds](results/paraphrase_detection/paraphrase_detection_thresholds.csv), and compressed predictions are retained. **PAWS fine-tuned results are pending** and no numbers have been invented for them. The prepared PAWS notebook can be run now; add the completed results when available.

## Validation and publishing

```bash
python -m pip install 'nbformat>=5.10,<6'
python -m unittest discover -s tests -v
python scripts/validate_repository.py
```

Tests use mocked Batch responses and temporary SQLite caches. They cover resumable jobs, partial/expired output, malformed/truncated responses, retries, legacy cache matching, preserved overrides and audit rules. Validation checks notebook schema, Python syntax, cleared outputs, snapshot hashes and file sizes. GitHub Actions runs these checks without credentials or model downloads. Full GPU evaluation and fine-tuning must be run separately.

Once the prepared files are reviewed, publish from this folder:

```bash
git remote add origin https://github.com/MehribanAliyeva/azsembench.git
git add .
git commit -m "Prepare AzSemBench datasets, pipelines, notebooks and results"
git push -u origin main
```

If `origin` already exists, inspect `git remote -v` rather than adding it again. The local `.env`, `.venv`, intermediate builds and model outputs are ignored. The first push makes the notebook dataset-download URLs available. Source snapshots, cache and overrides are retained because they contributed to `model_ready`; experimental caches, backups, IDE files and obsolete weights are excluded.
