# HateLens

**An explainable hate speech detection system with bias auditing and human feedback, built using traditional NLP.**

HateLens is a working local research application: a FastAPI server, a TF-IDF + Logistic Regression classifier trained on HateXplain, a SQLite review workflow, and a responsive browser dashboard with light and dark modes. It does not use an LLM, a transformer, or an external inference API.

## Run it

Python 3.11–3.13 and [uv](https://docs.astral.sh/uv/) are supported. From this directory:

```bash
uv sync --extra dev
uv run python -m hatelens.train --download --compare
uv run python -m hatelens
```

Open **http://127.0.0.1:8000**. If the model has already been trained, only the last command is needed. Training creates `artifacts/model.joblib` locally; trained artifacts, downloaded datasets, and the workspace database are excluded from Git. A fresh clone needs the training step before analysis is available.

Alternatively, without uv:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m hatelens.train --download --compare
python -m hatelens
```

Use `python -m hatelens --port 8001` if the default port is occupied. The server binds to loopback. After the initial dataset/dependency download, analysis, auditing, and feedback work offline.

## What works

- **Overview:** live counts and recent saved analyses. There are no simulated analytics.
- **Analysis:** one comment or a batch of up to 50 comments, one per line; maximum 3,000 characters per comment.
- **YouTube and X imports:** paste a video/post link, copied comments, or upload TXT/CSV/JSON. Preview, edit, select, and analyze up to 500 comments in batches of 50. Filter results by category, review status, or source. Download cleaned comments as JSON.
- **Explanations:** class scores, highlighted supporting word features, and exact linear feature contributions relative to the runner-up category. Character fragments remain visible in the explanation breakdown.
- **Review queue:** low-score, ambiguous, unfamiliar, short, or manually queued comments; reversible local approval/hiding decisions.
- **Human feedback:** confirmation, correction, or missing-context submissions; explicit acceptance/rejection with an adjudicated label.
- **Bias audit:** group-level false-positive/false-negative rates, denominators, 95% Wilson intervals, and 56 handcrafted identity-swap probes.
- **Model & methods:** dataset provenance, three-model validation comparison, held-out class metrics, confusion matrix, and limitations.
- **Export:** JSON evaluation/audit report and workspace counts. User comment text is excluded.

`Ctrl+Enter` / `⌘+Enter` analyzes the current comment. The theme follows the OS initially and remembers the selected mode. Browser API documentation is at `/api/docs`.

## Import YouTube or X comments

Open **Import comments** and choose **YouTube** or **X / Twitter**.

- **YouTube link:** paste a watch, Shorts, live, or youtu.be URL, choose a limit (1–500), select top/newest, and optionally include replies. Click **Fetch comments**. Uses yt-dlp for public comments without an API key, video download, browser cookies, or login. Public availability can change; disabled comments, restricted videos, or provider changes may prevent retrieval.
- **X link:** paste an x.com or twitter.com post URL. Enter an X API bearer token in the password field, or start the server with `X_BEARER_TOKEN` configured in its environment. The app looks up the conversation and searches its replies from the last **7 days**, newest first. Replies can be anywhere in the conversation; the original post is excluded. Post lookup/search access and applicable API credits are required. The token field is cleared after submission; tokens are not saved in SQLite or browser storage.
- **Text or files:** no credentials or internet are needed. YouTube clipboard extraction recognizes handles/times and separates trailing controls/counts. X clipboard extraction recognizes handle–dot–timestamp headers but preserves ambiguous display names, counts, and “Replying to” lines for manual editing. Prefer structured exports for X. CSV supports a chosen text column; JSON supports arrays, YouTube comment threads, X API `data` with user expansions, and archive-style `tweet.full_text` objects. JavaScript archive files must first be exported as JSON; the app never executes them.

Check the preview, edit boundaries if needed, deselect unwanted rows, and click **Analyze selected**. Source metadata is saved separately and never passed to the model. Duplicate text is marked and retained unless **Skip repeated text** is enabled. Text longer than 3,000 characters stays visible for editing instead of being silently truncated. Preview/fetch alone does not save analyses. Retrying an interrupted analysis within the same preview session avoids duplicate saves; starting a new preview is a new import session.

Live fetches have a 55-second deadline and at most two concurrent workers. A fetched sample is **not** proof that all comments were retrieved or a representative estimate of the whole audience. Provider errors and partial X pages are shown explicitly. Link imports contact YouTube/X; classification, explanations, and feedback remain local. Moderation decisions never hide or remove a comment on those platforms.

## Initial evaluation

Measured from the actual training run; these are baseline results, not target-domain guarantees.

| Measure | Result |
| --- | ---: |
| Training posts | 15,348 |
| Validation posts | 1,921 |
| Test posts | 1,923 |
| TF-IDF features | 74,651 |
| Test macro-F1 | 0.6511 |
| Test accuracy | 0.6635 |
| Project diagnostic probes matching expected labels | 34 / 56 |

On the validation split, macro-F1 was **0.6388** for Logistic Regression, **0.6166** for Linear SVM, and **0.5833** for Multinomial Naive Bayes. The serving model is Logistic Regression; its direct feature contributions support inspectable explanations.

The welcoming example included in the interface can be misclassified by this baseline and is routed to review. This demonstrates a real limitation of the dataset/domain, not a known-good assertion about the sample. Corrections do not instantly fix the model. The workspace may contain a few explicitly documented demo analyses from end-to-end verification.

Full results are in `artifacts/model.report.json`. The source dataset revision, file checksums, preprocessing rules, evaluation definitions, and limitations are documented in [the model card](docs/MODEL_CARD.md).

## Feedback and retraining

1. Analyze a comment and submit feedback.
2. Open **Human feedback** and review the submission. Acceptance requires a final category.
3. Train a separate candidate using accepted feedback:

```bash
uv run python -m hatelens.train \
  --with-feedback data/hatelens.sqlite3 \
  --output artifacts/candidate.joblib
```

Only accepted, labeled feedback is applied. Normalized text matching validation/test data is excluded; a correction matching an existing training example replaces that example rather than giving it duplicate weight. Pending/rejected feedback cannot affect training.

4. Compare `artifacts/candidate.report.json` with the active model’s report, including class metrics, group error counts, intervals, and diagnostic failures. Do not repeatedly choose candidates based on the same test set; use validation data for iteration and reserve fresh evaluation data for a release decision.
5. After deciding a candidate is suitable, run it explicitly:

```bash
HATELENS_MODEL=artifacts/candidate.joblib uv run python -m hatelens
```

Stop the existing server first, or use a different port. This does not overwrite the baseline artifact. There is deliberately no automatic promotion, and acceptance of feedback does not itself prove that a candidate is better. The `--with-feedback` command refuses the default active artifact as its output path.

## Test

```bash
uv run python -m pytest
node --check hatelens/web/app.js
node --check hatelens/web/imports.js
```

Tests cover exact explanation reconstruction, Unicode spans, retained negation, model serialization, input/batch validation, persistence, moderation, reviewed feedback, held-out exclusion, bias denominators/intervals, and missing-model recovery. Import tests cover the supplied 23-comment YouTube paste, structured exports, URL validation, pagination, timeouts, credential redaction, source filters, and retry-safe saves. Network behavior is mocked in automated tests. Parser fixtures and synthetic examples are never used as the research training dataset.

## Project structure

```text
hatelens/
  app.py           REST API and local browser app
  imports.py       Conservative clipboard, CSV, and JSON extraction
  social.py        Validated YouTube/X URLs and read-only provider clients
  social_worker.py Bounded subprocess for live fetches
  dataset.py       Pinned download, majority labels, split deduplication
  model.py         TF-IDF classifier, exact contributions, review routing
  evaluation.py    Class metrics, group audits, diagnostic probes
  storage.py       SQLite predictions, moderation, feedback review
  train.py         Offline training, baselines, candidate retraining
  text.py          Shared normalization and highlight offsets
  web/             HTML, CSS, JavaScript, and original SVG icon
tests/             Isolated automated tests
docs/              Model card and architecture
data/raw/          Downloaded research data (ignored by Git)
data/hatelens.sqlite3  Local analysis and feedback history (ignored)
artifacts/         Trained models and measured reports (ignored)
```

Set `HATELENS_MODEL` or `HATELENS_DATABASE` to select a different local artifact or database. Joblib files must be locally trained/trusted: loading a pickle is not a safe way to import arbitrary models.

## Scope

This is an **English, single-user research MVP**, including the reviewer role. It has no subscriber accounts, subscription billing, platform moderation permissions, or production access controls. Social connections only retrieve text on demand. Moderation decisions only affect local records. It should not be exposed directly to the public Internet.

Analyzed comments, source metadata, and feedback are saved in the local SQLite file until the workspace owner removes or archives that file. Comment text is not sent to an inference provider. Live imports send the selected video/post identifier and, for X, its API token to the relevant provider. The public training corpus contains hateful/offensive language; raw data and trained artifacts are excluded from Git.

## Sources

- [HateXplain dataset and code](https://github.com/hate-alert/HateXplain), Binny Mathew et al., AAAI 2021. Cite the dataset authors in academic work. The upstream repository is distributed under MIT; its provenance does not imply the authors endorse this application.
- [HateCheck research](https://arxiv.org/html/2012.15606v2), Paul Röttger et al. Our handcrafted probes cover related failure types, but do not reproduce the published benchmark.
- [Davidson et al., 2017](https://arxiv.org/abs/1703.04009), classical detection and the distinction between hate speech and offensive language. This project does not train on the Davidson dataset.
- [scikit-learn TF-IDF documentation](https://scikit-learn.org/stable/modules/generated/sklearn.feature_extraction.text.TfidfVectorizer.html) and [Logistic Regression documentation](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html).
- [yt-dlp extractor arguments](https://github.com/yt-dlp/yt-dlp#extractor-arguments), [X recent search](https://docs.x.com/x-api/posts/search-recent-posts), and [X conversation IDs](https://docs.x.com/x-api/fundamentals/conversation-id).
