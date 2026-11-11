# AzSemBench

AzSemBench is an Azerbaijani sentence-pair benchmark for semantic textual similarity (STS) and paraphrase detection. English STS-B, PAWS-Wiki and PAWS-X sentences were translated into Azerbaijani, then filtered with explicit translation and pair-consistency checks. Original labels and splits are retained. The repository includes the model-ready datasets, their source snapshots and translation provenance, evaluation and fine-tuning notebooks, and supplied experiment results.

## Repository contents

| Path | Purpose |
|---|---|
| `data/model_ready/core_model_ready.csv` | Azerbaijani STS-B and PAWS-Wiki used by the notebooks |
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
| [finetune_paws.ipynb](notebooks/finetune_paws.ipynb) | Fine-tune four multilingual cross-encoders for binary paraphrase classification; supplied results included |
| [llm_sts_llama.ipynb](notebooks/llm_sts_llama.ipynb) | Llama 3.2 3B: zero-shot and QLoRA STS |
| [llm_paws_qwen.ipynb](notebooks/llm_paws_qwen.ipynb) | Qwen3-4B: zero-shot and QLoRA PAWS |
| [llm_paws_gemma.ipynb](notebooks/llm_paws_gemma.ipynb) | Gemma 3 4B: zero-shot and QLoRA PAWS |
| [llm_paws_llama.ipynb](notebooks/llm_paws_llama.ipynb) | Llama 3.2 3B: zero-shot and QLoRA PAWS |

Open the notebook in Colab or Kaggle, enable Internet and a GPU, then run every cell from top to bottom. The first code cell installs dependencies. Each notebook downloads `core_model_ready.csv` **from this repository itself**, using `https://raw.githubusercontent.com/MehribanAliyeva/azsembench/main/data/model_ready/core_model_ready.csv`. No dataset upload or Kaggle input is required. The initial publication must include that file before notebook downloads work.

For local execution:

```bash
python -m pip install -r requirements-notebooks.txt
jupyter lab
```

The notebook configuration reads `AZSEMBENCH_REPO` and `AZSEMBENCH_REF` from environment variables or `.env`. Set the ref to a commit SHA to reproduce a fixed dataset. The download cell prints the URL and SHA-256. `AZSEMBENCH_OUTPUT_DIR` overrides each notebook's default `outputs/<workflow>/` path. CSV results are linked at the end; model weights are not bundled into an automatic ZIP.

Existing STS models: `LocalDoc/az-en-MiniLM-L6-v2`, LaBSE, multilingual MPNet, multilingual E5-large. Paraphrase evaluation also includes multilingual MiniLM-L12-v2. E5 uses `query: ` on both sentences for symmetric similarity. Embeddings are L2-normalized.

Both encoder fine-tuning notebooks use only `FacebookAI/xlm-roberta-base`, `google-bert/bert-base-multilingual-cased`, `distilbert/distilbert-base-multilingual-cased`, and `microsoft/mdeberta-v3-base`. Each encodes the sentence pair jointly. STS selects the best checkpoint by **dev Pearson**; PAWS selects by **dev F1**. Test is held out from checkpoint and threshold selection. Seed is 42; max sequence length is 192; learning rate is 2e-5; weight decay is 0.01; training batch size is 8 with 2 gradient-accumulation steps; evaluation batch size is 32. STS allows 5 epochs with early-stopping patience 2; PAWS allows 4 epochs with patience 1. These are the prepared notebook settings, not a recovered log of the supplied runs.

STS uses float32 regression loss and reports raw and clipped [0,5] predictions separately. Its tokenizer uses a fast implementation where available and falls back to a slow tokenizer. PAWS neural predictions use paraphrase probability at least 0.5. Its lexical baselines choose thresholds by dev F1, breaking ties by accuracy. Temporary checkpoints are deleted after saving the best model; CSV progress is saved after each model. Models run sequentially to limit GPU memory usage.

### Small-LLM notebooks

Use a fresh CUDA GPU session for each notebook; Gemma uses Unsloth while Qwen and Llama use Transformers/PEFT/TRL. Run the dependency cell first, then the configuration, data, zero-shot, training and adapted evaluation cells in order. Llama checkpoints require approved Hugging Face access. Set `HF_TOKEN` in an environment variable, an ignored local `.env`, Kaggle Secrets or Colab Secrets. The notebooks never embed personal credentials and their published outputs are cleared.

These notebooks fetch `core_model_ready.csv` from this repo, print its SHA-256, explicitly select Azerbaijani columns and the relevant task, and preserve split assignments. PAWS IDs combine split and source ID because source IDs repeat between partitions. No Kaggle dataset mount is needed. `AZSEMBENCH_REPO` / `AZSEMBENCH_REF` select a repository revision, optional `AZSEMBENCH_DATA_SHA256` verifies its content, and `AZSEMBENCH_OUTPUT_DIR` sets the parent of each notebook's separate output directory. Pin the ref and expected hash for a reproducible run. Configuration metadata prevents reusing outputs with a different model, dataset or main training settings; choose a fresh output directory when changing prompts or other experimental settings.

All three PAWS notebooks retain the submitted workflow's **15,000 stratified training examples**, **one epoch**, seed **42**, maximum sequence length **256**, learning rate **2e-4**, training batch **1**, gradient accumulation **4**, inference batch **16**, and LoRA rank **16**. Gemma uses alpha **16**, dropout **0.0** and Unsloth; Qwen and Llama use alpha **32**, dropout **0.05** and 4-bit NF4 base weights with float32 trainable adapters. Training uses 50 warmup steps, packing and completion-only loss when supported by the installed TRL configuration. No development evaluation or intermediate checkpoint selection is performed in these PAWS runs. Runtime versions and accepted trainer arguments are printed.

PAWS decisions compare the next-token logits of `0` and `1`; probabilities normalize those two logits, and the larger logit determines the label. Left padding is used for batched classification. Qwen disables thinking in its chat template. The fine-tuned evaluation reloads a fresh base plus the saved adapter and recomputes its predictions. The cleaned Gemma workflow also corrects a copied Qwen model label in prediction records. These maintenance changes apply to future runs; imported historical metrics remain unchanged.

Llama STS uses the submitted notebook's two epochs, maximum length 384, learning rate 2e-4, batch size 1, accumulation 8, and LoRA rank 16 / alpha 32 / dropout 0.05. Its Azerbaijani prompt requests a 0–5 score with deterministic generation. Adapters, predictions, run configuration and trainer logs are saved under the configured output directory, which is ignored by Git. The cleaned workflows have not been retrained here.

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

### Small-LLM results: STS and PAWS

The current study compares zero-shot and QLoRA conditions for **Gemma 3 4B IT**, **Qwen3-4B** and **Llama 3.2 3B Instruct**, superseding the earlier LLM experiment. All three STS and all three PAWS result summaries are available. Qwen PAWS metrics come from stored notebook outputs; Gemma and Llama PAWS metrics come from separately supplied result dictionaries/logs. Cleaned PAWS workflows for all three models and the supplied Llama STS workflow are included.

#### STS test results

The STS test partition contains **1,378 pairs**. All submitted LLM conditions use seed **42**. The Gemma checkpoint is `unsloth/gemma-3-4b-it-unsloth-bnb-4bit` (4B class); Qwen is `Qwen/Qwen3-4B` (4.0B); Llama is `meta-llama/Llama-3.2-3B-Instruct` (3B class).

| Model | Condition | Pearson ↑ | Spearman ↑ | Kendall τ ↑ | MAE ↓ | RMSE ↓ | R² ↑ |
|---|---|---:|---:|---:|---:|---:|---:|
| Gemma 3 4B | Zero-shot | 0.727112 | 0.699668 | 0.541051 | 0.896255 | 1.143963 | 0.437422 |
| Gemma 3 4B | QLoRA | 0.849855 | 0.840079 | 0.697510 | 0.608261 | 0.812432 | 0.716253 |
| Qwen3-4B | Zero-shot | 0.543180 | 0.546786 | 0.454500 | 1.073342 | 1.331572 | 0.237767 |
| Qwen3-4B | QLoRA | 0.857257 | 0.849847 | 0.712752 | 0.572309 | 0.793223 | 0.729597 |
| Llama 3.2 3B | Zero-shot | 0.372201 | 0.361005 | 0.274297 | 1.371843 | 1.738498 | -0.299291 |
| Llama 3.2 3B | QLoRA | 0.829205 | 0.822093 | 0.684659 | 0.656667 | 0.874682 | 0.671104 |

Reported Pearson gains are **0.122743** for Gemma, **0.314077** for Qwen and approximately **0.457004** for Llama. RMSE falls by approximately **29.0%**, **40.4%** and **49.7%**, respectively. Qwen has the highest LLM Pearson (0.857257), while fine-tuned mDeBERTa retains the highest overall Pearson (0.866624) and lower RMSE (0.773136). Qwen's MAE (0.572309) is slightly lower than mDeBERTa's (0.575873), and its Kendall correlation (0.712752) is higher, so rankings depend on the metric.

All three adapted LLMs exceed the strongest existing-model cosine Pearson (E5-large: 0.768788) and the strongest lexical Pearson (char-3 Jaccard: 0.687902). Cross-system differences combine architecture, inference, dataset and training choices; they are descriptive, with no statistical significance claim.

Sources: [Gemma STS metrics](results/llm_gemma_sts/gemma_sts_metrics.csv), [Qwen STS metrics](results/llm_qwen_sts/qwen_sts_metrics.csv), and [Llama STS metrics](results/llm_llama_sts/llama_sts_metrics.csv). Gemma and Qwen values come from six-decimal screenshots. Llama's zero-shot dictionary retains full precision; its fine-tuned summary is displayed to six decimals in the supplied notebook. Provenance files record the origins of each export. Raw LLM predictions and weights were not supplied.

#### Small-LLM PAWS test results

All reported conditions evaluate **4,980 test pairs** with seed **42**. The submitted PAWS training workflows use a **15,000-example stratified subset** and **one epoch**.

| Model | Condition | Accuracy ↑ | Precision ↑ | Recall ↑ | F1 ↑ | MCC ↑ |
|---|---|---:|---:|---:|---:|---:|
| Gemma 3 4B | Zero-shot | 0.730120 | 0.882250 | 0.453478 | 0.599045 | 0.479352 |
| Gemma 3 4B | QLoRA | 0.909639 | 0.895516 | 0.901987 | 0.898740 | 0.817178 |
| Qwen3-4B | Zero-shot | 0.587952 | 0.521463 | 0.888889 | 0.657315 | 0.273703 |
| Qwen3-4B | QLoRA | 0.784337 | 0.887755 | 0.589431 | 0.708469 | 0.577160 |
| Llama 3.2 3B | Zero-shot | 0.508434 | 0.426783 | 0.308040 | 0.357817 | -0.024616 |
| Llama 3.2 3B | QLoRA | 0.555422 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |

**Gemma** improves F1 from **0.599045 to 0.898740** (+0.299695) and accuracy from **0.730120 to 0.909639** (+17.95 percentage points). Recall rises from 0.453478 to 0.901987 while precision remains high (0.882250 → 0.895516). Gemma QLoRA is the strongest tested LLM on PAWS F1, **0.014868 below** fine-tuned mDeBERTa (0.913607) and **0.281991 above** the strongest existing encoder F1 (MPNet: 0.616749).

**Qwen** improves accuracy by **19.64 percentage points**, F1 by **0.051154**, and MCC by **0.303457**. Precision rises from 0.521463 to 0.887755 while recall decreases from 0.888889 to 0.589431. False positives fall from 1,806 to 165, but false negatives rise from 246 to 909. Qwen QLoRA F1 (0.708469) exceeds MPNet by 0.091720 while remaining 0.205138 below mDeBERTa.

**Llama** behaves differently: QLoRA predicts **every test pair as non-paraphrase** (TN=2,766, FP=0, FN=2,214, TP=0). Its accuracy rises from 0.508434 to 0.555422 because non-paraphrases are the majority class, while F1 falls from 0.357817 to **0.000000** and MCC is **0.000000**. This run does not provide a useful positive-class detector. The result is retained rather than omitted. Diagnosing the training objective, completion labels, adapter behavior and decision scores requires further investigation; the aggregate metrics do not identify a cause.

| Model | Condition | TN | FP | FN | TP |
|---|---|---:|---:|---:|---:|
| Gemma 3 4B | Zero-shot | 2632 | 134 | 1210 | 1004 |
| Gemma 3 4B | QLoRA | 2533 | 233 | 217 | 1997 |
| Qwen3-4B | Zero-shot | 960 | 1806 | 246 | 1968 |
| Qwen3-4B | QLoRA | 2601 | 165 | 909 | 1305 |
| Llama 3.2 3B | Zero-shot | 1850 | 916 | 1532 | 682 |
| Llama 3.2 3B | QLoRA | 2766 | 0 | 2214 | 0 |

The encoder PAWS workflow uses the full 49,301-row training split, while the submitted LLM PAWS workflow uses 15,000 examples and one epoch. These descriptive comparisons do not isolate architecture or fine-tuning effectiveness. ROC-AUC, average precision and Brier scores were not supplied for these LLM PAWS runs and are not inferred from hard labels. No lexical PAWS result is supplied.

Sources: [Gemma PAWS metrics](results/llm_gemma_paws/gemma_paws_metrics.csv), [Qwen PAWS metrics](results/llm_qwen_paws/qwen_paws_metrics.csv), and [Llama PAWS metrics](results/llm_llama_paws/llama_paws_metrics.csv). Each directory includes provenance; reported values and confusion-matrix counts are imported unchanged. Raw LLM predictions and adapters were not supplied.

| Model | STS metrics | STS notebook | PAWS metrics | PAWS notebook |
|---|---|---|---|---|
| Gemma 3 4B IT | Available | Awaiting intended attachment | Available | [Ready](notebooks/llm_paws_gemma.ipynb) |
| Qwen3-4B | Available | Awaiting intended attachment | Available | [Ready](notebooks/llm_paws_qwen.ipynb) |
| Llama 3.2 3B Instruct | Available | [Ready](notebooks/llm_sts_llama.ipynb) | Available | [Ready](notebooks/llm_paws_llama.ipynb) |

The earlier [Gemma and Qwen STS supplement](presentations/AzSemBench_Gemma_Qwen_STS_Supplement.pptx) is a historical STS presentation. The tables above contain the latest supplied results.

### Model-size reference

Counts below describe published checkpoint/base-model parameters, **including embeddings**, using the rounding shown on the linked model cards. They are not measurements of trained LoRA parameters, GPU memory, disk size or inference speed. A task head or adapter can add parameters. `M` means million and `B` means billion.

| Model | Approximate parameters | Source |
|---|---:|---|
| LocalDoc MiniLM | 30.2M | [Model card](https://huggingface.co/LocalDoc/az-en-MiniLM-L6-v2) |
| LaBSE | ~0.5B | [Model card](https://huggingface.co/sentence-transformers/LaBSE) |
| Multilingual MPNet | ~0.3B | [Model card](https://huggingface.co/sentence-transformers/paraphrase-multilingual-mpnet-base-v2) |
| Multilingual MiniLM-L12 | ~117.7M | [Model card](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2) |
| Multilingual E5-large | ~0.6B | [Model card](https://huggingface.co/intfloat/multilingual-e5-large) |
| XLM-RoBERTa-base | ~0.3B | [Model card](https://huggingface.co/FacebookAI/xlm-roberta-base) |
| Multilingual BERT | ~0.2B | [Model card](https://huggingface.co/google-bert/bert-base-multilingual-cased) |
| Multilingual DistilBERT | ~0.1B | [Model card](https://huggingface.co/distilbert/distilbert-base-multilingual-cased) |
| mDeBERTa-v3-base | ~276M | [Model card](https://huggingface.co/microsoft/mdeberta-v3-base) |
| Gemma 3 4B IT | 4B class | [Model card](https://huggingface.co/unsloth/gemma-3-4b-it-unsloth-bnb-4bit) |
| Qwen3-4B | 4.0B | [Model card](https://huggingface.co/Qwen/Qwen3-4B) |
| Llama 3.2 3B Instruct | 3B class | [Model card](https://huggingface.co/meta-llama/Llama-3.2-3B-Instruct) |

mDeBERTa’s approximately 276M total combines the model card’s 86M backbone and 190M embedding parameters. The source links and size conventions are also recorded in [model_sizes.json](docs/model_sizes.json). The Gemma experiment uses the Unsloth 4-bit checkpoint; **4-bit is a weight format, not a four-billion-parameter reduction**.

### Existing models: paraphrase test (4,980 pairs)

| Model | Dev threshold | Accuracy | Precision | Recall | F1 | ROC-AUC |
|---|---:|---:|---:|---:|---:|---:|
| Multilingual MiniLM-L12 | 0.7827 | 0.4484 | 0.4458 | 0.9901 | 0.6148 | 0.6540 |
| Multilingual MPNet | 0.8697 | 0.4532 | 0.4480 | 0.9896 | 0.6167 | 0.6786 |
| LaBSE | 0.8592 | 0.4450 | 0.4447 | 0.9986 | 0.6154 | 0.6459 |
| LocalDoc az-en MiniLM | 0.9102 | 0.4466 | 0.4452 | 0.9937 | 0.6149 | 0.6472 |
| Multilingual E5-large | 0.9197 | 0.4450 | 0.4446 | 0.9968 | 0.6149 | 0.6853 |

MPNet has the highest supplied test F1; E5 has the highest ROC-AUC. Recall is near 1 while precision and accuracy remain around 0.45: these dev-F1 thresholds produce many positive decisions, so F1 alone overstates the balance of performance on difficult negative pairs. Inspect accuracy, ROC-AUC and pair-level errors alongside F1.

[Paraphrase metrics](results/paraphrase_detection/paraphrase_detection_results.csv), [dev thresholds](results/paraphrase_detection/paraphrase_detection_thresholds.csv), and compressed predictions are retained.

### Fine-tuned models: PAWS-Wiki test (4,980 pairs)

All four supplied runs use a paraphrase-probability threshold of **0.5**.

| Model | Accuracy | Precision | Recall | F1 | Balanced accuracy | MCC | ROC-AUC | Average precision | Brier score |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| XLM-RoBERTa-base | 0.9112 | 0.8748 | 0.9341 | 0.9035 | 0.9135 | 0.8230 | 0.9666 | 0.9556 | 0.0754 |
| Multilingual BERT | 0.8984 | 0.8555 | 0.9282 | 0.8904 | 0.9014 | 0.7983 | 0.9599 | 0.9443 | 0.0891 |
| Multilingual DistilBERT | 0.8627 | 0.8253 | 0.8767 | 0.8502 | 0.8641 | 0.7247 | 0.9346 | 0.9191 | 0.1115 |
| mDeBERTa-v3-base | 0.9211 | 0.8899 | 0.9386 | 0.9136 | 0.9228 | 0.8421 | 0.9709 | 0.9603 | 0.0635 |

mDeBERTa-v3-base leads the four supplied PAWS fine-tuned runs on test F1 (0.9136), accuracy (0.9211), MCC (0.8421), ROC-AUC (0.9709), and average precision (0.9603), and has the lowest Brier score (0.0635). XLM-RoBERTa is next on F1 (0.9035).

The best supplied fine-tuned test F1 is approximately **0.2969 higher** than the best existing-model F1 (MPNet: 0.6167). The fine-tuned system combines a different encoder, joint sentence-pair encoding, supervised training and a different decision rule; this comparison does not isolate the effect of fine-tuning alone. Both result files evaluate the same split size, and no statistical significance claim is made.

[All PAWS fine-tuned metrics](results/paws_finetuned/paws_finetuned_all_metrics.csv) contain **12 rows**: four models × train/dev/test (49,301 / 7,991 / 4,980 pairs). The CSV also includes Pearson, Spearman, Kendall τ and confusion-matrix counts; their definitions are above. Train results are in-sample. These are the supplied run results, imported without modification; PAWS fine-tuned predictions, training summaries and weights were not supplied.

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
