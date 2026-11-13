# Verification — 13 November 2026

## Automated checks

- `python -m pytest`: **80 passed**.
- `node --check hatelens/web/app.js` and `node --check hatelens/web/imports.js`: passed.
- `python -m compileall -q hatelens`: passed.
- Test-client dependency emits one upstream deprecation notice about future migration from httpx to httpx2; there are no test failures.

## Browser checks

Verified against the running local application:

- A single comment produces real class scores, highlighted features, review reasons, and a saved history entry.
- A correction becomes pending feedback, can be adjudicated, and appears under accepted history without changing the original model prediction.
- Local approval removes a comment from the moderation queue.
- A three-comment batch creates three distinct analysis records, including a Unicode/emoji example.
- Bias-audit reruns produce the actual 34/56 result and retain per-group denominators/intervals.
- The JSON report downloads successfully and contains model evaluation, bias audit, and workspace counts without submitted comment text.
- Navigation, light/dark appearance, desktop layout, and mobile navigation work. Audit and methods views fit a 390-pixel viewport without document-level horizontal overflow; data tables scroll within their panels.
- No browser console warnings or errors were observed during these flows.

Four example analyses and one accepted demonstration correction remain in the local workspace. They are real test interactions, not simulated analytics. The welcoming sample was incorrectly predicted as offensive; its score triggered human review, and the example correction records `neither`. Another insulting example was incorrectly predicted as `neither`; it was also routed to review. These are documented model limitations.

## Retraining verification

Ran candidate training with the one accepted demonstration correction:

```bash
python -m hatelens.train --with-feedback data/hatelens.sqlite3 --output artifacts/feedback-candidate.joblib
```

The candidate used 15,349 training posts and the same protected validation/test splits. Its validation macro-F1 was **0.6365**, compared with **0.6388** for the baseline. Its test macro-F1 was **0.6501**, compared with **0.6511**, and diagnostic probes remained **34/56**. This does not establish an improvement. The candidate was not promoted; `artifacts/model.joblib` remains the active baseline.

Use fresh evaluation data for future release decisions after repeated model iteration. A single accepted correction is a workflow test, not evidence that feedback reliably improves aggregate model quality.


## Social import verification

- The user's copied YouTube fixture extracts **23 comments**, separating **105** metadata/control lines. Actual TXT file upload produced the same preview; the first comment without a username was retained.
- Pasting that whole fixture into the single-comment box automatically opened the import preview before the 3,000-character input limit could truncate it.
- Live YouTube retrieval succeeded for video `SOwUWPtXQ9I` using public access, without video downloads, cookies, or an API key. The final browser flow fetched and analyzed **20 top-level comments**, keeping author/time/like metadata out of the classifier. Source links, editable preview, selection, analysis details, and category filtering were checked.
- A two-row X CSV with a custom `Message` column was uploaded through the browser. Column selection, multiline/emoji preservation, clear/select controls, and analysis of only the selected row worked. The saved-source filter returned the single X demonstration record.
- Cleaned JSON downloaded successfully with both X preview rows and preserved multiline text.
- X missing-token handling was verified through the interface. No real X bearer token was configured, so authenticated live X retrieval has **not** been verified. Mocked tests cover conversation lookup, pagination, duplicate removal, full text, partial-page failure, token-safe errors, and current/legacy field names.
- URL validation rejects lookalike hosts, embedded credentials, unsupported schemes/ports, profile URLs, and malformed identifiers before network access. Tests also verify fetch deadlines, released worker slots, source provenance, and retry-safe analysis.
- X copied-section preview extracted two demonstration comments with their handles and timestamps separate. Light desktop and dark mobile layouts were checked; at 390px and the default 515px widths, document width matched viewport width. No browser console warnings/errors were present in the final checks. The temporary viewport override was removed and light mode restored.
- Screenshots: [YouTube light](import-youtube-light.jpg), [X light](import-x-light.jpg), [X dark mobile](import-x-dark-mobile.jpg).

The workspace now also contains 20 analyses from the supplied YouTube link and one clearly labeled `HateLens verification` X import example. Earlier user records and feedback were preserved. These are pipeline checks, not a new accuracy or fairness evaluation of YouTube/X comments.
