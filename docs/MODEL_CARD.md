# HateLens model card

## Intended use

An inspectable English-language research baseline for reviewing social-media comments, exploring classical text classification, investigating mistakes, and collecting reviewed corrections. Outputs support human judgment; they are not determinations about a person or proof that content is harmless/hateful.

The application distinguishes `hate` (upstream `hatespeech`), `offensive`, and `neither` (upstream `normal`). Definitions follow the training corpus’s annotation policy, which is imperfect and context dependent.

## Data provenance and split integrity

Source: [hate-alert/HateXplain](https://github.com/hate-alert/HateXplain), revision `01d742279dac941981f53806154481c0e15ee686`. These files are downloaded from that immutable revision:

| File | SHA-256 |
| --- | --- |
| `Data/dataset.json` | `63bb3340fee0ec469b09690d04cb68f7c187787dd8b83807f071892c084967fb` |
| `Data/post_id_divisions.json` | `c2fb0d89862e7897b11ea3e9380753f15a793482b4b70ad0532dfb1212212835` |

Post tokens are joined with spaces. A classification label requires at least two annotators to agree. A target-group label also requires at least two annotators; `None` and `Other` are omitted from group reporting. Group annotations describe referenced/targeted communities, not author identities.

The authors’ splits are retained. Exact duplicates after shared normalization are removed with priority **test → validation → train**, so no normalized held-out text enters training. This removed 37 duplicated texts, leaving 15,348 training, 1,921 validation, and 1,923 test posts. Near-duplicates are not detected; author-disjoint splitting and cross-platform transfer were not validated.

## Model

- Unicode NFKC, lowercase, curly-apostrophe normalization, whitespace collapse.
- URLs and mentions become shared placeholder tokens.
- No stop-word deletion or stemming. Negation is preserved.
- Word TF-IDF: unigrams/bigrams, `min_df=2`, at most 45,000 features, sublinear TF.
- Character TF-IDF: `char_wb` 3–5 grams, `min_df=2`, at most 30,000 features, sublinear TF.
- Feature union weights: word 1.0, character 0.6. The initial model has 74,651 features.
- Multiclass Logistic Regression: SAGA, `C=3`, balanced class weights, `max_iter=500`, `tol=0.001`, random seed 42. Training refuses to save a nonconverged model.
- Initial run: scikit-learn 1.9.1. The lockfile pins the full environment.

The parameters were set before the first test evaluation. Naive Bayes and Linear SVM were compared on validation data. No neural model, embedding service, transformer, or LLM is involved.

## Initial evaluation

| Class | Precision | Recall | F1 | Test support |
| --- | ---: | ---: | ---: | ---: |
| Hate speech | 0.7179 | 0.7542 | 0.7356 | 594 |
| Offensive language | 0.5238 | 0.4818 | 0.5019 | 548 |
| Neither | 0.7094 | 0.7222 | 0.7157 | 781 |

Test macro-F1: **0.6511**. Accuracy: **0.6635**.

Confusion matrix (rows: actual; columns: predicted; order: hate, offensive, neither):

```text
448   90   56
109  264  175
 67  150  564
```

Validation macro-F1: Logistic Regression **0.6388**; Linear SVM **0.6166**; Multinomial Naive Bayes **0.5833**. Reported scores are specific to this dataset and are not claims of production performance.

## Explanations

For predicted class `a` and runner-up class `b`, each nonzero TF-IDF feature contributes:

```text
contribution_j = x_j × (weight_a,j − weight_b,j)
decision_margin = intercept_a − intercept_b + sum(contribution_j)
```

The UI displays the ten largest absolute contributions, the remainder, and the intercept. Their sum reconstructs the pairwise logit difference. Positive word features may be highlighted in the original text; character fragments appear only in the breakdown. Unicode offsets use code points consistently across Python and JavaScript.

These are model-behavior explanations, not causal or moral explanations. A highlighted identity word can reveal a spurious association. They do not establish that words are intrinsically hateful. Although HateXplain contains human rationales, this MVP does not train on them or evaluate explanation agreement against them.

## Scores and review routing

Softmax outputs are shown as **model scores**, not calibrated confidence. Balanced class weighting and domain shift affect their interpretation. They are not a severity scale.

Route a prediction to review if any of these heuristic conditions hold:

- Largest model score is below 0.60.
- Top-two score gap is below 0.15.
- Fewer than 35% of normalized word tokens are in the learned unigram vocabulary, or no features are recognized.
- Fewer than three word tokens are present.
- A conservative non-ASCII/Latin-character heuristic suggests unsupported language. This is not a language identification model and does not reliably recognize Hinglish or other Latin-script languages.

These thresholds are starting heuristics, not tuned guarantees. Comments with high scores can also be wrong. The interface lets people review any saved comment.

## Bias auditing

The baseline reports 13 target groups observed in the held-out test set. Groups overlap, so group counts must not be added to obtain the total number of posts.

For each group, treating `hate` as the positive class:

- False-positive rate = incorrect hate predictions / all annotated non-hateful posts in that group.
- False-negative rate = missed hate / all annotated hateful posts in that group.
- A zero denominator is shown as unavailable, never as a zero error rate.
- Each estimate includes raw numerator/denominator and a 95% Wilson interval.
- Fewer than 20 positive or negative examples triggers a small-sample marker.

The separate diagnostic suite contains **56 project-authored examples**: seven templates crossed with eight group names. It covers everyday mention, support, welcome, negation, opposing hate, exclusion, and dehumanization. The baseline matches **34/56** expected labels. Failure examples and group-swap score spreads are visible. These probes are not the published HateCheck dataset, an unbiased population sample, a statistical fairness certification, or evidence of equal treatment in deployment. Templates containing exclusion/dehumanization are synthetic research examples.

## Human feedback

Feedback is never applied immediately. Submissions enter SQLite as pending, then receive an explicit accepted/rejected reviewer decision. Acceptance requires an adjudicated label. Training consumes only accepted records and excludes normalized validation/test text. Existing training text is replaced rather than duplicated; multiple reviewed submissions for the same normalized text are resolved in chronological review order.

Retraining creates a separate candidate artifact and report. Promotion is a manual release decision, not an automatic consequence of a favorable metric. Repeated examination of a test set can itself cause leakage through model selection; use validation data during iteration and fresh held-out data for later release evaluation.

## Limitations

- Dataset/platform bias and limited context; welcoming or neutral comments can be mislabeled.
- Offensive-language F1 is about 0.502; this class is particularly difficult.
- Sarcasm, irony, quoted hate, reclaimed language, and implicit hate remain unreliable.
- English evaluation only; no multilingual performance claim.
- No conversation threads, images, video, speaker history, or reliable intent inference.
- No dialect subgroup evaluation or annotation of users’ protected characteristics.
- No explanation-rationale validation, calibration study, or prospective field study.
- The local MVP has one user/reviewer role, no authentication, no billing, no remote moderation, and no deployment-level access controls.

## Reference

Binny Mathew, Punyajoy Saha, Seid Muhie Yimam, Chris Biemann, Pawan Goyal, and Animesh Mukherjee. **HateXplain: A Benchmark Dataset for Explainable Hate Speech Detection.** AAAI 2021, 35(17):14867–14875. [Dataset repository](https://github.com/hate-alert/HateXplain).
