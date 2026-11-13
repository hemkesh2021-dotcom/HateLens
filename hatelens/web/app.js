"use strict";

const names = { hate: "Hate speech", offensive: "Offensive language", neither: "Neither" };
const pageNames = { overview: "Overview", analyze: "Analyze comments", import: "Import comments", review: "Review queue", feedback: "Human feedback", audit: "Bias audit", model: "Model & methods" };
const state = { page: "overview", status: null, latest: null, batch: [], mode: "single", draft: "", label: "", query: "", offset: 0, feedbackStatus: "pending", feedbackOffset: 0, predictions: new Map(), feedback: new Map(), audit: null, busy: false, renderId: 0 };
state.source = "";
state.batchFilter = "";
const $ = (selector, parent = document) => parent.querySelector(selector);
const $$ = (selector, parent = document) => [...parent.querySelectorAll(selector)];
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character]));
const icon = (name, className = "") => `<svg class="icon ${className}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const number = (value) => Number(value || 0).toLocaleString();
const percent = (value, digits = 0) => value == null ? "—" : `${(value * 100).toFixed(digits)}%`;
const date = (value) => new Date(value).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
const badge = (value, label = names[value] || value) => `<span class="badge ${escapeHtml(value)}">${escapeHtml(label)}</span>`;

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  $$("[data-theme-choice]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.themeChoice === theme)));
  $("meta[name=theme-color]").content = theme === "dark" ? "#1c231f" : "#f3f4f0";
  try { localStorage.setItem("hatelens-theme", theme); } catch { /* Theme still works if storage is unavailable. */ }
}
let initialTheme;
try { initialTheme = localStorage.getItem("hatelens-theme"); } catch { /* Use the OS preference. */ }
setTheme(["dark", "light"].includes(initialTheme) ? initialTheme : (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));

async function api(path, body) {
  const response = await fetch(`/api${path}`, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok) {
    let message = data.detail || "Something went wrong. Please try again.";
    if (Array.isArray(message)) message = message.map((item) => item.msg).join(" ");
    throw new Error(message);
  }
  return data;
}

let toastTimeout;
function toast(message) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.add("visible");
  clearTimeout(toastTimeout);
  toastTimeout = setTimeout(() => element.classList.remove("visible"), 4500);
}

async function refreshStatus() {
  state.status = await api("/status");
  $("#review-count").textContent = state.status.summary.comments.review || "";
  $("#feedback-count").textContent = state.status.summary.feedback.pending || "";
  const ready = state.status.ready;
  $("#model-status").innerHTML = `<span class="live-dot"></span>${ready ? "Model ready" : "Model not loaded"}`;
  $("#model-status").classList.toggle("unready", !ready);
}

function heading(eyebrow, title, description, emblem = "leaf", action = "") {
  return `<div class="page-heading"><div><p class="eyebrow">${escapeHtml(eyebrow)}</p><h1>${escapeHtml(title)}</h1><p class="page-description">${escapeHtml(description)}</p></div>${action || `<div class="heading-emblem" aria-hidden="true">${icon(emblem)}</div>`}</div>`;
}

function stat(title, value, caption, symbol) {
  return `<div class="stat-card"><div class="stat-top"><span>${escapeHtml(title)}</span>${icon(symbol)}</div><div class="stat-value">${escapeHtml(value)}</div><div class="stat-caption"><span class="live-dot"></span>${escapeHtml(caption)}</div></div>`;
}

function stats() {
  const { comments, feedback } = state.status.summary;
  return `<section class="stat-grid" aria-label="Workspace statistics">${stat("Comments analyzed", number(comments.total), "In this workspace", "chat")}${stat("Awaiting review", number(comments.review), "A human perspective helps", "queue")}${stat("Hate speech flagged", number(comments.hate), "Model predictions · not verdicts", "shield")}${stat("Feedback reviewed", number(feedback.accepted + feedback.rejected), `${number(feedback.pending)} submissions awaiting review`, "check")}</section>`;
}

function composer() {
  const batch = state.mode === "batch";
  return `<section class="panel composer"><div class="panel-body"><div class="panel-heading"><div><h2 class="panel-title">Take a closer look.</h2><p class="panel-subtitle">Understand a comment before you make the call.</p></div><span class="icon-wrap">${icon("scan")}</span></div>
    <div class="segment" role="group" aria-label="Analysis mode"><button type="button" data-mode="single" aria-pressed="${!batch}">Single comment</button><button type="button" data-mode="batch" aria-pressed="${batch}">Batch analysis</button></div>
    <form id="analysis-form"><div class="input-label"><label for="comment-input">${batch ? "Comments · one per line" : "Your comment"}</label><span class="language-tag">English</span></div><textarea id="comment-input" name="text" maxlength="${batch ? 150049 : 3000}" rows="5" placeholder="${batch ? "Paste up to 50 comments, one per line…" : "Paste a social media comment here…"}" required>${escapeHtml(state.draft)}</textarea>
    <div class="example-row"><span>Try an example</span><button class="example-button" type="button" data-example="kind">A kind comment</button><button class="example-button" type="button" data-example="criticism">A sharp criticism</button><button class="example-button" type="button" data-example="context">Missing context</button></div>
    <div class="composer-bottom"><div><span class="character-count" id="character-count">${inputCount()}</span><span class="privacy-line">${icon("shield")}Analyzed and saved on your machine</span></div><button class="button primary" type="submit" ${state.busy || !state.status.ready ? "disabled" : ""}>${state.busy ? '<span class="spinner"></span>Analyzing…' : `${batch ? "Analyze batch" : "Analyze comment"}${icon("arrow")}`}</button></div><p class="form-error" role="alert"></p></form></div>
    <div class="composer-foot">${icon("info")}A prediction is a starting point. Context still matters.<a href="#import" class="import-shortcut">Import comments${icon("arrow")}</a></div></section>`;
}

function inputCount() {
  return state.mode === "batch" ? `${state.draft.split(/\r?\n/).filter((line) => line.trim()).length} / 50 comments` : `${number(state.draft.length)} / 3,000 characters`;
}

function emptyAnalysis() {
  return `<section class="panel empty-analysis" aria-label="Analysis results"><div class="lens-illustration" aria-hidden="true">${icon("lens")}<span class="lens-spark">${icon("check")}</span></div><h2>Clarity, before action.</h2><p>Every conversation has context. See the prediction, explore its reasoning, and add your perspective.</p><div class="three-steps"><span><b>1</b>Analyze</span><span><b>2</b>Understand</span><span><b>3</b>Review</span></div></section>`;
}

function highlightedText(prediction) {
  // Python offsets count Unicode code points, so avoid JavaScript UTF-16 slicing.
  const text = Array.from(prediction.text);
  let end = 0;
  let html = "";
  for (const span of prediction.explanation.highlights) {
    html += escapeHtml(text.slice(end, span.start).join(""));
    html += `<mark title="Supports the predicted category">${escapeHtml(text.slice(span.start, span.end).join(""))}</mark>`;
    end = span.end;
  }
  return html + escapeHtml(text.slice(end).join(""));
}

function resultContent(prediction, detail = false) {
  const explanation = prediction.explanation;
  const max = Math.max(...explanation.features.map((item) => Math.abs(item.contribution)), 0.001);
  return `<div class="result-content" id="${detail ? "detail-result" : "analysis-result"}" tabindex="-1"><div class="result-heading"><div><p class="result-kicker">A CLEARER LOOK</p>${badge(prediction.label)}</div><div class="score"><strong>${percent(prediction.score)}</strong><small>model score</small></div></div>
    ${renderImportProvenance(prediction)}
    <div class="comment-quote">${highlightedText(prediction)}</div><p class="result-hint">Highlights support this label. They do not make a word inherently hateful.</p>
    <div class="probability-list">${Object.keys(names).map((label) => `<div class="probability-row"><span>${names[label]}</span><div class="bar-track ${label}"><span style="width:${prediction.probabilities[label] * 100}%"></span></div><span>${percent(prediction.probabilities[label])}</span></div>`).join("")}</div>
    <p class="result-hint">Scores are uncalibrated model estimates, not a measure of certainty.</p>
    ${prediction.needs_review ? `<div class="review-note">${icon("info")}<div><strong>A human review would help.</strong><ul>${prediction.review_reasons.map((reason) => `<li>${escapeHtml(reason)}</li>`).join("")}</ul></div></div>` : ""}
    <details class="explanation-details"><summary>What shaped this prediction?</summary><p>These features push the decision toward <strong>${names[prediction.label]}</strong> (+) or toward the next category, <strong>${names[explanation.comparison_label]}</strong> (−).</p>${explanation.features.length ? explanation.features.map((item) => `<div class="feature-row"><span><code>${escapeHtml(item.feature.trim())}</code><span class="kind">${item.kind === "char" ? "fragment" : "word"}</span></span><span class="feature-track ${item.contribution < 0 ? "negative" : ""}"><i style="width:${Math.abs(item.contribution) / max * 100}%"></i></span><span class="feature-value">${item.contribution >= 0 ? "+" : ""}${item.contribution.toFixed(2)}</span></div>`).join("") : '<p>No familiar features were found. The prediction reflects only the model intercept.</p>'}<p>Top features + remaining features (${explanation.other_features_margin.toFixed(3)}) + intercept (${explanation.base_margin.toFixed(3)}) = decision margin ${explanation.decision_margin.toFixed(3)}. These are logit contributions, not percentage points.</p></details>
    <div class="feedback-actions">${prediction.feedback_status ? `<div class="feedback-received">${icon("check")}Feedback ${prediction.feedback_status === "pending" ? "received · awaiting review" : escapeHtml(prediction.feedback_status)}</div>` : `<p>Does this look right to you?</p><div class="button-row"><button type="button" class="button secondary" data-confirm="${prediction.id}">${icon("check")}Looks right</button><button type="button" class="button secondary" data-correct="${prediction.id}">${icon("edit")}Correct label</button><button type="button" class="button ghost" data-context="${prediction.id}">Needs context</button></div>`}</div>
    ${detail ? `<div class="feedback-actions"><p>Moderation decision ${prediction.moderation !== "unresolved" ? `· ${escapeHtml(prediction.moderation)}` : ""}</p><div class="button-row"><button class="button secondary" data-moderate="approved" data-id="${prediction.id}">${icon("check")}Approve locally</button><button class="button secondary" data-moderate="hidden" data-id="${prediction.id}">${icon("x")}Hide locally</button><button class="button ghost" data-moderate="review" data-id="${prediction.id}">Send to review</button></div><p class="result-hint">Saved in HateLens only. This does not change or remove the comment on YouTube or X.</p><p class="result-hint">${escapeHtml(prediction.model_version)} · ${escapeHtml(date(prediction.created_at))}</p></div>` : ""}</div>`;
}

function resultPanel() {
  return state.latest ? `<section class="panel" aria-label="Analysis result">${resultContent(state.latest)}</section>` : emptyAnalysis();
}

function emptyTable(title, description, symbol = "chat") {
  return `<div class="table-empty">${icon(symbol)}<h3>${escapeHtml(title)}</h3><p>${escapeHtml(description)}</p></div>`;
}

function cachePredictions(items) {
  items.forEach((item) => state.predictions.set(item.id, item));
}

function commentsTable(items, review = false) {
  cachePredictions(items);
  if (!items.length) return emptyTable(review ? "No comments waiting for review." : "A fresh start for better conversations.", review ? "Uncertain predictions and comments you send for review will appear here." : "Analyze your first comment above. Your saved results will appear here.", review ? "queue" : "chat");
  return `<div class="table-wrap"><table class="data-table"><thead><tr><th>Comment</th><th>Prediction</th><th>Model score</th><th>${review ? "Review" : "Status"}</th><th>${review ? "Action" : "Analyzed"}</th></tr></thead><tbody>${items.map((item) => `<tr><td class="comment-cell"><button class="comment-link" data-view="${item.id}" title="Open comment analysis">${escapeHtml(item.text)}</button></td><td>${badge(item.label)}</td><td>${percent(item.score)}</td><td>${item.moderation === "approved" ? badge("approved", "Approved locally") : item.moderation === "hidden" ? badge("rejected", "Hidden locally") : item.needs_review || item.moderation === "review" ? badge("review", "Needs review") : '<span class="empty-label">Unreviewed</span>'}</td><td>${review ? `<div class="button-row"><button class="button secondary small" data-view="${item.id}">Review${icon("arrow")}</button><button class="button ghost small" data-moderate="approved" data-id="${item.id}" aria-label="Approve comment locally">${icon("check")}</button></div>` : `<span class="muted">${escapeHtml(date(item.created_at))}</span>`}</td></tr>`).join("")}</tbody></table></div>`;
}

function toolbar() {
  return `<div class="table-toolbar"><div class="filter-group" role="group" aria-label="Filter predictions">${[["", "All comments"], ["hate", "Hate speech"], ["offensive", "Offensive"], ["neither", "Neither"]].map(([value, label]) => `<button class="filter-button ${state.label === value ? "active" : ""}" data-filter="${value}" aria-pressed="${state.label === value}">${label}</button>`).join("")}</div><div class="history-controls"><select id="source-filter" aria-label="Filter by source"><option value="">All sources</option>${["Manual", "Batch", "YouTube", "X"].map((source) => `<option value="${source}" ${state.source === source ? "selected" : ""}>${source}</option>`).join("")}</select><div class="search-box">${icon("search")}<input type="search" id="comment-search" aria-label="Search saved comments" placeholder="Search comments…" maxlength="300" value="${escapeHtml(state.query)}"></div></div></div>`;
}

function pagination(result, type = "comments") {
  if (!result.total) return "";
  return `<div class="pagination"><span>${number(result.offset + 1)}–${number(Math.min(result.offset + result.limit, result.total))} of ${number(result.total)}</span><div class="pagination-controls"><button class="button secondary small" data-paginate="${type}" data-offset="${Math.max(0, result.offset - result.limit)}" ${result.offset === 0 ? "disabled" : ""}>Previous</button><button class="button secondary small" data-paginate="${type}" data-offset="${result.offset + result.limit}" ${result.offset + result.limit >= result.total ? "disabled" : ""}>Next</button></div></div>`;
}

function batchResults(items = state.batch, imported = false) {
  if (!items.length) return "";
  const filtered = items.filter((item) => !state.batchFilter || (state.batchFilter === "review" ? item.needs_review : item.label === state.batchFilter));
  return `<section class="panel batch-results ${imported ? "import-results" : ""}"><div class="section-heading"><div><h2>${imported ? "Imported comment results" : "Batch results"}</h2><p>${items.length} ${items.length === 1 ? "comment" : "comments"} analyzed. Labels are model predictions; select a comment to review its explanation.</p></div>${imported ? '<a class="button ghost small" href="#analyze">Saved history' + icon("arrow") + '</a>' : '<button class="button ghost small" data-clear-batch>Dismiss' + icon("x") + '</button>'}</div><div class="table-toolbar"><div class="filter-group" role="group" aria-label="Filter batch results">${[["", "All"], ["hate", "Hate speech"], ["offensive", "Offensive"], ["neither", "Neither"], ["review", "Needs review"]].map(([value, label]) => { const count = items.filter((item) => !value || (value === "review" ? item.needs_review : item.label === value)).length; return `<button class="filter-button ${state.batchFilter === value ? "active" : ""}" data-batch-filter="${value}" aria-pressed="${state.batchFilter === value}">${label} · ${count}</button>`; }).join("")}</div></div>${filtered.length ? commentsTable(filtered) : emptyTable("No results in this category.", "Choose another filter to see the remaining predictions.")}</section>`;
}

function commentQuery(review = false, recent = false) {
  const params = new URLSearchParams({ limit: recent ? "5" : "15", offset: recent ? "0" : String(state.offset) });
  if (!recent && state.label) params.set("label", state.label);
  if (!recent && state.query) params.set("q", state.query);
  if (!recent && state.source) params.set("source", state.source);
  if (review) params.set("review_only", "true");
  return `/comments?${params}`;
}

async function overviewPage(full = false) {
  const result = await api(commentQuery(false, !full));
  return `${full ? heading("A LITTLE MORE UNDERSTANDING", "Look beyond the label.", "Analyze a comment, explore its signals, and share what the model missed.", "scan") : heading("YOUR MODERATION WORKSPACE", "Make room for better conversations.", "A clearer view of your community. With people at the heart of every decision.")}
    ${full ? "" : stats()}${!state.status.ready ? modelUnavailable() : ""}<div class="analysis-grid">${composer()}${resultPanel()}</div>${batchResults()}
    <section aria-label="Saved analyses"><div class="section-heading"><div><h2>${full ? "Your analyses" : "Recent analyses"}</h2><p>${full ? "Saved locally, with the original model version and explanation." : "A little context for every decision."}</p></div>${full ? "" : '<a class="button ghost small" href="#analyze">View all' + icon("arrow") + "</a>"}</div><div class="panel">${full ? toolbar() : ""}${commentsTable(result.items)}${full ? pagination(result) : ""}</div></section>
    ${full ? "" : `<div class="overview-bottom"><section class="panel mini-card">${icon("chat")}<div><h3>Your perspective makes a difference.</h3><p>Corrections and context go to a human review queue. Accepted labels can inform the next model.</p><a class="text-link" href="#feedback">Explore human feedback${icon("arrow")}</a></div></section><section class="panel mini-card">${icon("shield")}<div><h3>Fairness deserves a closer look.</h3><p>Explore measured errors across annotated groups, alongside small diagnostic tests.</p><a class="text-link" href="#audit">Open the bias audit${icon("arrow")}</a></div></section></div>`}`;
}

async function reviewPage() {
  const result = await api(commentQuery(true));
  return `${heading("CONTEXT MAKES THE DIFFERENCE", "A second look, a better decision.", "Uncertain comments and those you’ve marked for review, all in one place.", "queue")}
    <div class="info-banner">${icon("info")}<span>Moderation actions are saved in this workspace. Approving or hiding a comment here does not change a social media post or retrain the model.</span></div>
    <section class="panel">${toolbar()}${commentsTable(result.items, true)}${pagination(result)}</section>`;
}

async function feedbackPage() {
  const params = new URLSearchParams({ limit: "15", offset: String(state.feedbackOffset) });
  if (state.feedbackStatus) params.set("status", state.feedbackStatus);
  const result = await api(`/feedback?${params}`);
  result.items.forEach((item) => state.feedback.set(item.id, item));
  return `${heading("LEARNING STARTS WITH LISTENING", "Make your perspective count.", "Review corrections thoughtfully. Build a better training set, one decision at a time.", "chat")}
    <div class="feedback-flow"><span class="flow-step"><b>1</b>Subscriber feedback</span>${icon("arrow")}<span class="flow-step"><b>2</b>Human review</span>${icon("arrow")}<span class="flow-step"><b>3</b>Offline retraining</span>${icon("arrow")}<span class="flow-step"><b>4</b>Evaluate & release</span></div>
    <div class="info-banner plain">${icon("info")}<span>This local workspace includes the reviewer role. Accepted feedback becomes eligible for retraining; the active model remains unchanged.</span></div>
    <section class="panel"><div class="table-toolbar"><div class="filter-group" role="group" aria-label="Filter feedback">${[["pending", "Awaiting review"], ["accepted", "Accepted"], ["rejected", "Rejected"], ["", "All feedback"]].map(([value, label]) => `<button class="filter-button ${state.feedbackStatus === value ? "active" : ""}" data-feedback-filter="${value}" aria-pressed="${state.feedbackStatus === value}">${label}</button>`).join("")}</div><span class="empty-label">${number(result.total)} submissions</span></div>
    ${result.items.length ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Comment</th><th>Original → suggested</th><th>Context</th><th>Status</th><th>Review</th></tr></thead><tbody>${result.items.map((item) => `<tr><td class="comment-cell"><button class="comment-link" data-view="${item.prediction_id}">${escapeHtml(item.text)}</button></td><td><span class="muted">${names[item.original_label]}</span><br><strong>${item.proposed_label ? names[item.proposed_label] : "Needs context"}</strong></td><td class="feedback-note-cell">${escapeHtml(item.note || item.reason.replaceAll("_", " "))}</td><td>${badge(item.status)}</td><td>${item.status === "pending" ? `<button class="button secondary small" data-review-feedback="${item.id}">Review${icon("arrow")}</button>` : `<span class="muted">${item.reviewed_label ? names[item.reviewed_label] : "Not accepted"}</span>`}</td></tr>`).join("")}</tbody></table></div>` : emptyTable("No submissions in this view.", "Use “Looks right”, “Correct label”, or “Needs context” on an analysis to share feedback.", "chat")}${pagination(result, "feedback")}</section>`;
}

function rateCell(value) {
  if (value.rate == null) return '<span class="empty-label">No examples</span>';
  return `<div class="rate" title="95% interval: ${percent(value.interval[0], 1)}–${percent(value.interval[1], 1)}"><strong>${percent(value.rate, 1)}</strong><span class="bar-track"><span style="width:${value.rate * 100}%"></span></span></div><div class="rate-denominator">${value.errors} / ${value.total} · CI ${percent(value.interval[0], 0)}–${percent(value.interval[1], 0)}</div>`;
}

function probesHtml(probes) {
  return probes.templates.map((template) => `<details class="probe-item"><summary><strong>${escapeHtml(template.category)}</strong><span class="${template.passed < template.cases.length ? "fail-count" : ""}">${template.passed} / ${template.cases.length} match expected labels · ${percent(template.score_spread, 1)} score spread</span></summary><p class="probe-intro">Only the group name changes. Score spread is the difference between the largest and smallest hate-speech model scores.</p><div class="table-wrap"><table class="data-table"><thead><tr><th>Test comment</th><th>Expected</th><th>Prediction</th><th>Hate score</th></tr></thead><tbody>${template.cases.map((item) => `<tr><td class="case-text">${escapeHtml(item.text)}</td><td>${names[item.expected]}</td><td>${badge(item.predicted)}</td><td>${percent(item.hate_score, 1)}</td></tr>`).join("")}</tbody></table></div></details>`).join("");
}

async function auditPage() {
  if (!state.status.ready) return modelUnavailable();
  if (!state.audit || state.audit.model_version !== state.status.model.version) state.audit = await api("/audit");
  const audit = state.audit;
  return `${heading("ASK BETTER QUESTIONS OF THE MODEL", "Fairness is something we examine.", "Explore where errors happen, who they affect, and what still needs attention.", "shield")}
    <div class="stat-grid audit-stats">${stat("Held-out test posts", number(audit.test_samples), "Never used to fit the model", "book")}${stat("Annotated target groups", number(audit.groups.length), "Groups may overlap", "shield")}${stat("Diagnostic probes passed", `${audit.probes.passed} / ${audit.probes.total}`, "Handcrafted · limited coverage", "scan")}</div>
    <div class="info-banner plain">${icon("info")}<span>These checks reveal specific model errors. They do not establish that the system is fair across all communities or contexts. Target groups come from dataset annotations, not inferred author identities.</span></div>
    <section class="panel audit-panel"><div class="panel-body"><div class="section-heading"><div><h2>Errors across target groups</h2><p>HateXplain test set · hate speech versus all other categories</p></div></div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>Annotated group</th><th>Posts</th><th>False-positive rate</th><th>False-negative rate</th></tr></thead><tbody>${audit.groups.map((group) => `<tr><td>${escapeHtml(group.group)}${group.small_sample ? '<span class="small-sample">Small sample</span>' : ""}</td><td>${number(group.samples)}</td><td>${rateCell(group.false_positive)}</td><td>${rateCell(group.false_negative)}</td></tr>`).join("")}</tbody></table></div><div class="panel-footnote">False positives: non-hateful posts incorrectly flagged as hate. False negatives: hateful posts the model missed.<br>CI = 95% Wilson interval. “Small sample” means fewer than 20 positive or negative examples; those rates are particularly uncertain.</div></section>
    <section class="panel audit-panel"><div class="panel-body"><div class="section-heading"><div><h2>Same sentence. Different identity.</h2><p>${escapeHtml(audit.probes.description)}</p></div><button class="button secondary small" id="run-probes">${icon("refresh")}Run probes</button></div></div>${probesHtml(audit.probes)}<div class="panel-footnote">These are project-authored diagnostic probes, not the published HateCheck benchmark. Scores are uncalibrated estimates. ${audit.probes.run_at ? `Last run: ${escapeHtml(date(audit.probes.run_at))}.` : ""}</div></section>`;
}

function modelUnavailable() {
  return `<section class="panel error-state"><h2>The model needs to be trained.</h2><p>${escapeHtml(state.status?.error || "The workspace is available. Train the local classifier to enable analysis and auditing.")}</p><code>python -m hatelens.train --download --compare</code><p>After training, restart the server and refresh this page.</p></section>`;
}

function modelPage() {
  if (!state.status.ready) return modelUnavailable();
  const model = state.status.model;
  const test = model.test;
  return `${heading("TRANSPARENCY, BY DESIGN", "Know what’s behind the prediction.", "A traditional NLP baseline, documented data, and results you can inspect.", "book")}
    <div class="model-layout"><section class="panel panel-body"><div class="panel-heading"><div><h2 class="panel-title">A small, understandable model.</h2><p class="panel-subtitle">No generative model or external inference service.</p></div><span class="icon-wrap">${icon("lens")}</span></div><div class="architecture"><span>Comment</span>${icon("arrow")}<span>Word + character TF-IDF</span>${icon("arrow")}<span>Logistic Regression</span></div><dl class="definition-list"><div><dt>TRAINING POSTS</dt><dd>${number(model.training_samples)}</dd></div><div><dt>FEATURES</dt><dd>${number(model.feature_count)}</dd></div><div><dt>TEST MACRO-F1</dt><dd>${model.test.macro_f1.toFixed(3)}</dd></div><div><dt>LANGUAGE</dt><dd>${model.language}</dd></div><div class="full"><dt>MODEL VERSION</dt><dd>${escapeHtml(model.version)}</dd></div><div><dt>TRAINED</dt><dd>${escapeHtml(date(model.trained_at))}</dd></div><div><dt>SCIKIT-LEARN</dt><dd>${escapeHtml(model.sklearn_version)}</dd></div></dl></section>
    <section class="panel panel-body"><h2 class="panel-title">What the labels mean</h2><ul class="method-list"><li>${icon("shield")}<div><strong>Hate speech</strong><br>Attacks or degrades people based on group identity, following the training dataset’s annotation policy.</div></li><li>${icon("chat")}<div><strong>Offensive language</strong><br>Insults, abuse, or profanity without a group-based hate label.</div></li><li>${icon("leaf")}<div><strong>Neither</strong><br>Neither of the above categories under that policy. This is not a universal safety verdict.</div></li></ul><p class="methods-copy">These boundaries can be subjective. The model learns human annotations, including their limitations.</p></section></div>
    <div class="model-layout"><section class="panel"><div class="panel-body"><div class="section-heading"><div><h2>Held-out performance</h2><p>${number(test.samples)} test posts · macro-F1 treats each category equally</p></div></div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>Category</th><th>Precision</th><th>Recall</th><th>F1</th><th>Posts</th></tr></thead><tbody>${Object.keys(names).map((label) => { const row = test.per_class[label]; return `<tr><td>${names[label]}</td><td>${row.precision.toFixed(3)}</td><td>${row.recall.toFixed(3)}</td><td>${row["f1-score"].toFixed(3)}</td><td>${number(row.support)}</td></tr>`; }).join("")}</tbody></table></div><div class="panel-footnote">Accuracy: ${percent(test.accuracy, 1)}. No claim is made that these results transfer to a new platform or language.</div></section>
    <section class="panel panel-body"><h2 class="panel-title">Where labels get confused</h2><p class="panel-subtitle">Rows = annotated labels · columns = predictions</p><div class="confusion"><span></span><span>Hate</span><span>Offensive</span><span>Neither</span>${test.label_order.map((label, row) => `<span>${label === "hate" ? "Hate" : label === "offensive" ? "Offensive" : "Neither"}</span>${test.confusion_matrix[row].map((value, column) => `<span class="matrix-value ${row === column ? "diagonal" : ""}" aria-label="Actual ${names[label]}, predicted ${names[test.label_order[column]]}: ${value}">${number(value)}</span>`).join("")}`).join("")}</div></section></div>
    <div class="model-layout"><section class="panel panel-body"><h2 class="panel-title">Classical model comparison</h2><p class="panel-subtitle">Macro-F1 on ${number(model.validation.samples)} validation posts. These are not test scores.</p><div class="probability-list">${model.comparison.map((row) => `<div class="probability-row" style="grid-template-columns:165px 1fr 40px"><span>${escapeHtml(row.model)}</span><div class="bar-track"><span style="width:${row.macro_f1 * 100}%"></span></div><span>${row.macro_f1.toFixed(3)}</span></div>`).join("")}</div><p class="methods-copy">Logistic Regression is the serving model. Its linear scores allow exact feature contributions relative to the runner-up category.</p></section>
    <section class="panel panel-body"><h2 class="panel-title">Data & known limitations</h2><div class="methods-copy"><p>Trained on <a href="https://github.com/hate-alert/HateXplain" target="_blank" rel="noopener noreferrer">HateXplain</a>, with the authors’ train/validation/test divisions. Repeated normalized text is removed across splits, giving held-out data precedence. Data files are versioned and checksummed.</p><p>Sarcasm, quotations, indirect hate, reclaimed language, and missing conversation context remain difficult. This version has only been evaluated on English posts from this dataset.</p><p>Negation is preserved. Group identities are not inferred from users. Feature explanations describe model behavior; human rationales have not been used to validate explanation quality.</p><p><a href="https://arxiv.org/html/2012.15606v2" target="_blank" rel="noopener noreferrer">HateCheck research</a> informs the types of failure to examine; our small probes are not a substitute for that benchmark.</p></div></section></div>`;
}

async function renderPage() {
  const renderId = ++state.renderId;
  const requested = location.hash.slice(1) || "overview";
  state.page = Object.hasOwn(pageNames, requested) ? requested : "overview";
  document.title = `HateLens · ${pageNames[state.page]}`;
  $("#breadcrumb-current").textContent = pageNames[state.page];
  $$("nav [data-page]").forEach((link) => {
    const active = link.dataset.page === state.page;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  });
  try {
    let html;
    if (state.page === "overview") html = await overviewPage();
    if (state.page === "analyze") html = await overviewPage(true);
    if (state.page === "import") {
      if (!importState.providers) importState.providers = await api("/import/providers");
      html = renderImportPage();
    }
    if (state.page === "review") html = await reviewPage();
    if (state.page === "feedback") html = await feedbackPage();
    if (state.page === "audit") html = await auditPage();
    if (state.page === "model") html = modelPage();
    if (renderId === state.renderId) $("main").innerHTML = html;
  } catch (error) {
    if (renderId === state.renderId) $("main").innerHTML = `<div class="panel error-state"><h2>We couldn’t load this view.</h2><p>${escapeHtml(error.message)}</p><button class="button primary" data-retry>Try again${icon("refresh")}</button></div>`;
  }
}

async function syncPrediction(id) {
  const prediction = await api(`/comments/${id}`);
  state.predictions.set(id, prediction);
  if (state.latest?.id === id) state.latest = prediction;
  state.batch = state.batch.map((item) => item.id === id ? prediction : item);
  importState.results = importState.results.map((item) => item.id === id ? prediction : item);
  if ($("#detail-dialog").open && $("#detail-dialog").dataset.predictionId === id) $("#detail-content").innerHTML = resultContent(prediction, true);
  return prediction;
}

async function openDetail(id) {
  const prediction = await syncPrediction(id);
  $("#detail-content").innerHTML = resultContent(prediction, true);
  $("#detail-dialog").dataset.predictionId = id;
  $("#detail-dialog").showModal();
}

function openFeedback(id, kind) {
  const form = $("#feedback-form");
  form.reset();
  form.elements.prediction_id.value = id;
  form.elements.kind.value = kind;
  form.elements.reason.value = kind === "context" ? "missing_context" : "wrong_category";
  form.elements.proposed_label.required = kind === "correct";
  $(".form-error", form).textContent = "";
  $("#feedback-dialog").showModal();
}

function openReview(id) {
  const item = state.feedback.get(id);
  if (!item) return;
  $("#review-context").innerHTML = `<div class="comment-quote review-quote">${escapeHtml(item.text)}</div><div class="review-metadata">Original: <strong>${names[item.original_label]}</strong> · Suggested: <strong>${item.proposed_label ? names[item.proposed_label] : "Needs context"}</strong><br>Reason: ${escapeHtml(item.reason.replaceAll("_", " "))}${item.note ? `<br>Subscriber’s note: ${escapeHtml(item.note)}` : ""}</div>`;
  const form = $("#review-form");
  form.reset();
  form.elements.feedback_id.value = id;
  form.elements.reviewed_label.value = item.proposed_label || "";
  $(".form-error", form).textContent = "";
  $("#review-dialog").showModal();
}

document.addEventListener("click", async (event) => {
  if ($("#sidebar").classList.contains("open") && !event.target.closest("#sidebar, #menu-button")) {
    $("#sidebar").classList.remove("open");
    $("#menu-button").setAttribute("aria-expanded", "false");
    event.preventDefault();
    return;
  }
  if (event.target.closest(".skip-link")) {
    event.preventDefault();
    $("#main").focus();
    return;
  }
  const button = event.target.closest("button");
  if (!button) return;
  try {
    if (button.dataset.themeChoice) setTheme(button.dataset.themeChoice);
    if (button.dataset.close) document.getElementById(button.dataset.close).close();
    if (button.id === "menu-button") {
      const open = $("#sidebar").classList.toggle("open");
      button.setAttribute("aria-expanded", String(open));
    }
    if (button.dataset.mode && !state.busy) {
      state.mode = button.dataset.mode;
      if (state.mode === "single" && state.draft.length > 3000) state.draft = state.draft.slice(0, 3000);
      await renderPage();
    }
    if (button.dataset.example) {
      const examples = { kind: "Thank you for sharing this. Everyone deserves to feel welcome here.", criticism: "This is a terrible argument. You have absolutely no idea what you are talking about.", context: "I do not agree with people who say that immigrants should leave." };
      const example = examples[button.dataset.example];
      state.draft = state.mode === "batch" && state.draft.trim() ? `${state.draft.trim()}\n${example}` : example;
      $("#comment-input").value = state.draft;
      $("#character-count").textContent = inputCount();
      $("#comment-input").focus();
    }
    if (Object.hasOwn(button.dataset, "filter")) {
      state.label = button.dataset.filter;
      state.offset = 0;
      await renderPage();
    }
    if (Object.hasOwn(button.dataset, "batchFilter")) {
      state.batchFilter = button.dataset.batchFilter;
      await renderPage();
    }
    if (Object.hasOwn(button.dataset, "feedbackFilter")) {
      state.feedbackStatus = button.dataset.feedbackFilter;
      state.feedbackOffset = 0;
      await renderPage();
    }
    if (button.dataset.paginate) {
      if (button.dataset.paginate === "feedback") state.feedbackOffset = Number(button.dataset.offset);
      else state.offset = Number(button.dataset.offset);
      await renderPage();
    }
    if (Object.hasOwn(button.dataset, "clearBatch")) { state.batch = []; await renderPage(); }
    if (button.dataset.view) await openDetail(button.dataset.view);
    if (button.dataset.correct) openFeedback(button.dataset.correct, "correct");
    if (button.dataset.context) openFeedback(button.dataset.context, "context");
    if (button.dataset.confirm) {
      button.disabled = true;
      await api(`/comments/${button.dataset.confirm}/feedback`, { kind: "confirm", reason: "agreement" });
      await syncPrediction(button.dataset.confirm);
      await refreshStatus();
      await renderPage();
      toast("Thanks. Your confirmation is in the human review queue.");
    }
    if (button.dataset.reviewFeedback) openReview(button.dataset.reviewFeedback);
    if (button.dataset.moderate) {
      button.disabled = true;
      await api(`/comments/${button.dataset.id}/moderation`, { action: button.dataset.moderate });
      await syncPrediction(button.dataset.id);
      await refreshStatus();
      await renderPage();
      toast("Moderation decision saved in this workspace.");
    }
    if (button.id === "run-probes") {
      button.disabled = true;
      button.innerHTML = '<span class="spinner"></span>Running…';
      state.audit.probes = await api("/audit/probes", {});
      await renderPage();
      toast(`Diagnostic probes complete: ${state.audit.probes.passed} of ${state.audit.probes.total} match the expected labels.`);
    }
    if (button.id === "export-button") {
      button.disabled = true;
      const report = await api("/export");
      const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: "application/json" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = `hatelens-report-${new Date().toISOString().slice(0, 10)}.json`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      toast("Report exported. Comment text is not included.");
    }
    if (Object.hasOwn(button.dataset, "retry")) { await refreshStatus(); await renderPage(); }
  } catch (error) {
    toast(error.message);
  } finally {
    if (button.isConnected && button.type !== "submit") button.disabled = false;
  }
});

let searchTimeout;
document.addEventListener("change", async (event) => {
  if (event.target.id === "source-filter") {
    state.source = event.target.value;
    state.offset = 0;
    await renderPage();
  }
});
document.addEventListener("input", (event) => {
  if (event.target.id === "comment-input") {
    state.draft = event.target.value;
    $("#character-count").textContent = inputCount();
  }
  if (event.target.id === "comment-search") {
    state.query = event.target.value;
    state.offset = 0;
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(async () => {
      const caret = event.target.selectionStart;
      await renderPage();
      const search = $("#comment-search");
      if (search) { search.focus(); try { search.setSelectionRange(caret, caret); } catch { /* Some engines do not support search input selection. */ } }
    }, 350);
  }
});

document.addEventListener("submit", async (event) => {
  const form = event.target;
  if (!["analysis-form", "feedback-form", "review-form"].includes(form.id)) return;
  event.preventDefault();
  if (form.id === "analysis-form") {
    const source = copiedConversationSource(form.elements.text.value);
    if (source) { await routeCopiedConversation(form.elements.text.value, source); return; }
  }
  if (form.dataset.submitting === "true" || (form.id === "analysis-form" && state.busy)) return;
  form.dataset.submitting = "true";
  const errorElement = $(".form-error", form);
  errorElement.textContent = "";
  const buttons = $$("button[type=submit]", form);
  buttons.forEach((button) => { button.disabled = true; });
  try {
    if (form.id === "analysis-form") {
      state.busy = true;
      const mode = state.mode;
      const text = form.elements.text.value.trim();
      if (!text) throw new Error("Add a comment to analyze.");
      buttons[0].innerHTML = '<span class="spinner"></span>Analyzing…';
      if (mode === "batch") {
        const comments = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
        if (comments.length > 50) throw new Error("Use up to 50 comments in a batch.");
        if (comments.some((comment) => comment.length > 3000)) throw new Error("Each comment must be 3,000 characters or fewer.");
        const result = await api("/analyze/batch", { comments });
        state.batch = result.items;
        cachePredictions(result.items);
        state.latest = result.items[0];
      } else {
        state.latest = await api("/analyze", { text });
        cachePredictions([state.latest]);
      }
      state.busy = false;
      await refreshStatus();
      await renderPage();
      const result = $("#analysis-result");
      if (result) { result.focus({ preventScroll: true }); if (window.innerWidth < 1000) result.scrollIntoView({ behavior: "smooth", block: "start" }); }
      toast(mode === "batch" ? `${state.batch.length} comments analyzed and saved.` : "Analysis saved. Your perspective is welcome.");
    }
    if (form.id === "feedback-form") {
      const id = form.elements.prediction_id.value;
      await api(`/comments/${id}/feedback`, { kind: form.elements.kind.value, proposed_label: form.elements.proposed_label.value || null, reason: form.elements.reason.value, note: form.elements.note.value });
      $("#feedback-dialog").close();
      await syncPrediction(id);
      await refreshStatus();
      await renderPage();
      toast("Feedback submitted. A human review comes next.");
    }
    if (form.id === "review-form") {
      const decision = event.submitter?.value;
      const label = form.elements.reviewed_label.value;
      if (decision === "accepted" && !label) throw new Error("Choose a final category before accepting this submission.");
      await api(`/feedback/${form.elements.feedback_id.value}/review`, { status: decision, reviewed_label: label || null, note: form.elements.note.value });
      const reviewed = state.feedback.get(form.elements.feedback_id.value);
      $("#review-dialog").close();
      if (reviewed) await syncPrediction(reviewed.prediction_id);
      await refreshStatus();
      await renderPage();
      toast(decision === "accepted" ? "Label accepted for future retraining. The active model is unchanged." : "Submission reviewed and rejected.");
    }
  } catch (error) {
    errorElement.textContent = error.message;
    if (!errorElement.isConnected) toast(error.message);
  } finally {
    form.dataset.submitting = "false";
    if (form.id === "analysis-form") {
      state.busy = false;
      if (buttons[0].isConnected) buttons[0].innerHTML = `${state.mode === "batch" ? "Analyze batch" : "Analyze comment"}${icon("arrow")}`;
    }
    buttons.forEach((button) => { button.disabled = false; });
  }
});

window.addEventListener("hashchange", () => {
  state.offset = 0;
  $("#sidebar").classList.remove("open");
  $("#menu-button").setAttribute("aria-expanded", "false");
  renderPage();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") { $("#sidebar").classList.remove("open"); $("#menu-button").setAttribute("aria-expanded", "false"); }
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && event.target.id === "comment-input") $("#analysis-form").requestSubmit();
});

async function start() {
  try { await refreshStatus(); await renderPage(); }
  catch (error) { $("main").innerHTML = `<section class="panel error-state"><h2>The local server is unavailable.</h2><p>${escapeHtml(error.message)}</p><button class="button primary" data-retry>Reconnect${icon("refresh")}</button></section>`; }
}
start();
