"use strict";

// Shared rendering helpers are declared by app.js, which loads after this file.
const importState = { source: "YouTube", link: "", limit: 50, sort: "top", includeReplies: false, providers: null, fetching: false, raw: "", filename: "", format: "auto", column: null, preview: null, results: [], busy: false, reading: false, stale: false, skipDuplicates: false, error: "", progress: null };
const formatNames = { auto: "Auto-detect", youtube: "Copied YouTube section", x: "Copied X section", lines: "Plain text · one comment per line", csv: "CSV export", json: "JSON export", link: "Fetched from link" };

function importRows() { return importState.preview?.comments || []; }
function pendingImportRows() { return importRows().filter((row) => row.selected && row.valid && !row.prediction_id); }

function copiedConversationSource(text) {
  const youtubeHeaders = text.match(/@[\w.\-·]+\s*\\?\s*\d+\s+(?:second|minute|hour|day|week|month|year)s?\s+ago/gi) || [];
  const xHeaders = text.match(/@[A-Za-z0-9_]{1,15}\s*[·•]\s*(?:\d+\s*[smhd]|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2})/gi) || [];
  return youtubeHeaders.length >= 2 ? "YouTube" : xHeaders.length >= 2 ? "X" : null;
}

async function routeCopiedConversation(text, source) {
  if (importState.busy || importState.fetching || importState.reading) {
    toast("Finish the current import, then paste these comments on the Import comments page.");
    return;
  }
  importState.source = source;
  importState.raw = text;
  importState.filename = "";
  importState.format = "auto";
  importState.column = null;
  location.hash = "import";
  await renderPage();
  await previewImport();
  toast("Copied conversation detected. Review each extracted comment before analysis.");
}

function renderImportProvenance(prediction) {
  const meta = prediction.import_metadata;
  if (!meta) return "";
  const details = [prediction.source, meta.author || "Author not supplied", meta.posted_at].filter(Boolean);
  const counts = [meta.likes ? `${meta.likes} likes` : "", meta.replies ? `${meta.replies}${/repl/i.test(meta.replies) ? "" : " replies"}` : ""].filter(Boolean);
  return `<p class="result-hint provenance-detail">${details.map(escapeHtml).join(" · ")}${counts.length ? `<br>${counts.map(escapeHtml).join(" · ")}` : ""}<br>Source details are not analyzed.${meta.source_url ? ` <a class="import-origin" href="${escapeHtml(meta.source_url)}" target="_blank" rel="noopener noreferrer">Original conversation ↗</a>` : ""}</p>`;
}

function renderImportPage() {
  const locked = importState.busy || importState.reading || importState.fetching;
  const isX = importState.source === "X";
  return `${heading("BRING THE CONVERSATION WITH YOU", "Comments in. Clutter out.", "Import from YouTube or X. Check the text, then explore predictions and add your feedback.", "download")}
    <div class="import-source-switch" role="group" aria-label="Comment source">${["YouTube", "X"].map((source) => `<button type="button" class="source-choice ${importState.source === source ? "active" : ""}" data-import-source="${source}" aria-pressed="${importState.source === source}" ${locked ? "disabled" : ""}><span class="source-symbol" aria-hidden="true">${source === "YouTube" ? "▶" : "𝕏"}</span>${source === "X" ? "X / Twitter" : source}</button>`).join("")}<span>Preview first. Analyze what matters.</span></div>
    <div class="import-intake"><section class="panel panel-body import-link-panel"><div class="panel-heading"><div><p class="eyebrow">FROM A LINK</p><h2 class="panel-title">${isX ? "Bring in the replies." : "Start with a video."}</h2><p class="panel-subtitle">${isX ? "Recent conversation replies through the X API." : "Public YouTube comments. No API key needed."}</p></div><span class="icon-wrap">${icon("chat")}</span></div>
    <form id="import-link-form"><label for="import-link" class="input-label">${isX ? "X post link" : "YouTube video link"}</label><input id="import-link" type="text" inputmode="url" autocomplete="off" maxlength="2048" placeholder="${isX ? "https://x.com/username/status/…" : "https://www.youtube.com/watch?v=…"}" value="${escapeHtml(importState.link)}" required ${locked ? "disabled" : ""}>
    <div class="link-options"><label for="import-limit">Comment limit<input id="import-limit" type="number" min="1" max="500" value="${importState.limit}" required ${locked ? "disabled" : ""}></label>${!isX ? `<label for="import-sort">Sort by<select id="import-sort" ${locked ? "disabled" : ""}><option value="top" ${importState.sort === "top" ? "selected" : ""}>Top comments</option><option value="new" ${importState.sort === "new" ? "selected" : ""}>Newest first</option></select></label>` : '<p>Last 7 days<br>Newest replies first</p>'}</div>
    ${isX ? `<details class="x-credentials" ${importState.providers?.x?.token_configured ? "" : "open"}><summary>${importState.providers?.x?.token_configured ? "Server token configured · use a different token" : "Connect your X API access"}</summary><label for="x-token" class="input-label">Bearer token</label><input id="x-token" type="password" autocomplete="off" spellcheck="false" placeholder="${importState.providers?.x?.token_configured ? "Optional override for this fetch" : "Paste your X API bearer token"}" ${locked ? "disabled" : ""}><p class="form-hint">Used for this fetch, then cleared. Not saved in HateLens. API access and usage charges depend on your X account. <a href="https://docs.x.com/x-api/posts/search/introduction" target="_blank" rel="noopener noreferrer">X API setup ↗</a></p></details>` : `<label class="duplicate-control include-replies"><input id="import-replies" type="checkbox" ${importState.includeReplies ? "checked" : ""} ${locked ? "disabled" : ""}>Include available replies within this limit</label>`}
    <p class="form-hint link-scope">${isX ? "Includes replies across the linked conversation. The original post and replies older than 7 days are excluded." : "The preview is a sample. Private videos, disabled comments, or access restrictions may prevent retrieval."}</p>
    <button class="button primary fetch-button" type="submit" ${locked ? "disabled" : ""}>${importState.fetching ? '<span class="spinner"></span>Fetching comments…' : `Fetch comments${icon("arrow")}`}</button><p class="form-hint">${importState.fetching ? "This can take up to 55 seconds. Keep this page open." : "Fetching creates a preview. Analysis starts when you choose."}</p></form></section>
    <section class="panel panel-body"><div class="panel-heading"><div><p class="eyebrow">FROM TEXT OR A FILE</p><h2 class="panel-title">Have the comments already?</h2><p class="panel-subtitle">TXT, CSV, JSON · up to 2 MB and 500 comments</p></div></div>
    <div class="import-upload" id="import-upload"><div>${icon("download")}<span><strong>${escapeHtml(importState.filename || "Choose a file, or drop it here")}</strong><small>Processed by your local HateLens server.</small></span></div><button type="button" class="button secondary small" data-import-action="choose" ${locked ? "disabled" : ""}>Choose file</button><input class="sr-only" type="file" id="import-file" aria-label="Upload comments" accept=".txt,.csv,.json" ${locked ? "disabled" : ""}></div>
    <form id="import-form"><label for="import-content" class="input-label">Or paste the copied section</label><textarea id="import-content" rows="5" maxlength="2097152" placeholder="${isX ? '@community_member · 2h&#10;I appreciated this explanation.' : '@community_member&#10;2 hours ago&#10;I appreciated this explanation.&#10;12&#10;Reply'}" ${locked ? "disabled" : ""}>${escapeHtml(importState.raw)}</textarea>
    <div class="import-format"><label for="import-format">Input format</label><select id="import-format" ${locked ? "disabled" : ""}>${Object.entries(formatNames).filter(([value]) => value !== "link").map(([value, name]) => `<option value="${value}" ${importState.format === value ? "selected" : ""}>${name}</option>`).join("")}</select></div>
    ${importState.preview?.columns ? `<div class="import-format"><label for="import-column">Comment column</label><select id="import-column" ${locked ? "disabled" : ""}><option value="">Choose a column</option>${importState.preview.columns.map((column) => `<option value="${escapeHtml(column)}" ${importState.column === column ? "selected" : ""}>${escapeHtml(column)}</option>`).join("")}</select></div>` : ""}
    <div class="composer-bottom"><span class="character-count">Only comment text is analyzed.</span><button class="button primary" type="submit" ${locked ? "disabled" : ""}>${importState.reading ? '<span class="spinner"></span>Reading…' : `Preview comments${icon("arrow")}`}</button></div></form>
    </section></div><p class="form-error import-main-error" id="import-error" role="alert">${escapeHtml(importState.error)}</p>
    <div id="import-preview-region">${renderImportPreview()}</div>${batchResults(importState.results, true)}`;
}

function renderImportPreview() {
  const preview = importState.preview;
  if (!preview) return "";
  const rows = preview.comments;
  const locked = importState.busy || importState.reading || importState.fetching;
  const selected = pendingImportRows().length;
  const done = rows.filter((row) => row.prediction_id).length;
  return `<section class="panel import-preview" aria-label="Extracted comments"><div class="panel-body"><div class="section-heading"><div><p class="eyebrow">CHECK BEFORE YOU ANALYZE</p><h2>${rows.length} extracted comments</h2><p>${escapeHtml(preview.source)} · ${escapeHtml(formatNames[preview.format])}${preview.format !== "link" ? ` · ${preview.removed_lines} metadata/control lines separated` : ""}${preview.duplicates ? ` · ${preview.duplicates} repeated comments` : ""}</p>${preview.source_url ? `<a class="import-origin" href="${escapeHtml(preview.source_url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(preview.title || "View original conversation")} ↗</a>` : ""}</div>${rows.length ? '<button class="button secondary small" data-import-action="download">Download cleaned JSON' + icon("download") + '</button>' : ""}</div>
    ${preview.warnings.map((warning) => `<p class="import-warning">${icon("info")}<span>${escapeHtml(warning)}</span></p>`).join("")}
    <p class="import-stale" id="import-stale" ${importState.stale ? "" : "hidden"}>The source changed. Preview again before analyzing.</p></div>
    ${rows.length ? `<div class="table-toolbar"><div class="button-row"><button class="button ghost small" data-import-action="select-all" ${locked ? "disabled" : ""}>Select all eligible</button><button class="button ghost small" data-import-action="select-none" ${locked ? "disabled" : ""}>Clear selection</button></div><label class="duplicate-control"><input type="checkbox" id="skip-duplicates" ${importState.skipDuplicates ? "checked" : ""} ${locked ? "disabled" : ""}>Skip repeated text</label></div>
    <div class="table-wrap import-preview-scroll"><table class="data-table import-preview-table"><thead><tr><th scope="col">Use</th><th scope="col">Comment text · editable</th><th scope="col">Source details</th></tr></thead><tbody>${rows.map((row, index) => `<tr data-import-row="${row.id}"><td><input type="checkbox" data-select-import="${row.id}" aria-label="Select comment ${index + 1}" ${row.selected ? "checked" : ""} ${locked || !row.valid || row.prediction_id || (importState.skipDuplicates && row.duplicate_of) ? "disabled" : ""}><span class="import-row-number">${index + 1}</span></td><td><textarea data-edit-import="${row.id}" aria-label="Comment ${index + 1} text" rows="2" ${locked || row.prediction_id ? "disabled" : ""}>${escapeHtml(row.text)}</textarea><span class="import-row-status ${row.valid ? "" : "invalid"}" data-row-status="${row.id}">${row.prediction_id ? "Analyzed and saved" : !row.valid ? `${row.characters} characters · edit to 3,000 or fewer` : row.duplicate_of ? `Repeated text · same as ${row.duplicate_of}` : `${row.characters} characters`}</span></td><td class="import-source"><strong>${escapeHtml(row.author || "Author not supplied")}</strong><span>${escapeHtml(row.posted_at || "Time not supplied")}</span>${row.likes ? `<span>${escapeHtml(row.likes)} likes</span>` : ""}${row.replies ? `<span>${escapeHtml(row.replies)}${/repl/i.test(row.replies) ? "" : " replies"}</span>` : ""}</td></tr>`).join("")}</tbody></table></div>
    <div class="import-preview-footer"><div><strong id="import-selection-count">${selected} selected${done ? ` · ${done} already analyzed` : ""}</strong><p>Overlong comments are kept for editing, never silently cut.</p></div><button class="button primary" id="analyze-import" data-import-action="analyze" ${locked || importState.stale || !selected || !state.status.ready ? "disabled" : ""}>${importState.busy ? '<span class="spinner"></span>Analyzing…' : `Analyze selected${icon("arrow")}`}</button></div>
    ${importState.progress ? `<div class="import-progress" role="status"><progress max="${importState.progress.total}" value="${importState.progress.done}"></progress><span>${importState.progress.done} / ${importState.progress.total} comments processed</span></div>` : ""}` : ""}</section>`;
}

function setImportError(message) {
  importState.error = message;
  const error = document.getElementById("import-error");
  if (error) error.textContent = message;
  else if (message) toast(message);
}

function markImportStale() {
  importState.stale = Boolean(importState.preview);
  const notice = document.getElementById("import-stale");
  if (notice) notice.hidden = !importState.stale;
  updateImportSelection();
}

function updateImportSelection() {
  const selected = pendingImportRows().length;
  const done = importRows().filter((row) => row.prediction_id).length;
  const count = document.getElementById("import-selection-count");
  if (count) count.textContent = `${selected} selected${done ? ` · ${done} already analyzed` : ""}`;
  const button = document.getElementById("analyze-import");
  if (button) button.disabled = importState.busy || importState.reading || importState.fetching || importState.stale || !selected || !state.status.ready;
}

function updateImportRows() {
  const seen = new Map();
  for (const row of importRows()) {
    const key = row.text.normalize("NFKC").toLowerCase().trim().replace(/\s+/g, " ");
    row.duplicate_of = seen.get(key) || null;
    seen.set(key, seen.get(key) || row.id);
    row.characters = Array.from(row.text).length;
    row.valid = row.text.trim().length > 0 && row.characters <= 3000;
    if (!row.valid || (importState.skipDuplicates && row.duplicate_of) || row.prediction_id) row.selected = false;
    const check = document.querySelector(`[data-select-import="${row.id}"]`);
    if (check) {
      check.checked = row.selected;
      check.disabled = !row.valid || Boolean(row.prediction_id) || (importState.skipDuplicates && Boolean(row.duplicate_of));
    }
    const status = document.querySelector(`[data-row-status="${row.id}"]`);
    if (status) {
      status.textContent = row.prediction_id ? "Analyzed and saved" : !row.valid ? `${row.characters} characters · use 1–3,000 characters` : row.duplicate_of ? `Repeated text · same as ${row.duplicate_of}` : `${row.characters} characters`;
      status.classList.toggle("invalid", !row.valid);
    }
  }
  updateImportSelection();
}

async function previewImport() {
  if (importState.busy || importState.reading || importState.fetching) return;
  if (!importState.raw.trim()) { setImportError("Paste comments or choose a file first."); return; }
  importState.reading = true;
  importState.error = "";
  if (state.page === "import") await renderPage();
  try {
    const result = await api("/import/preview", { source: importState.source, content: importState.raw, format: importState.format, filename: importState.filename, column: importState.column });
    acceptImportPreview(result);
  } catch (error) {
    importState.stale = Boolean(importState.preview);
    importState.error = error.message;
  } finally {
    importState.reading = false;
    if (state.page === "import") await renderPage();
  }
}

function acceptImportPreview(result) {
  result.comments.forEach((row) => { row.selected = row.valid && !(importState.skipDuplicates && row.duplicate_of); });
  importState.preview = result;
  importState.column = result.selected_column || null;
  importState.results = [];
  importState.progress = null;
  importState.stale = false;
  state.batchFilter = "";
}

async function fetchImportLink() {
  if (importState.busy || importState.reading || importState.fetching) return;
  if (!importState.link.trim()) { setImportError("Paste a video or post link first."); return; }
  const tokenField = document.getElementById("x-token");
  const request = { url: importState.link.trim(), source: importState.source, limit: importState.limit, sort: importState.sort, include_replies: importState.includeReplies, token: tokenField?.value.trim() || "" };
  if (tokenField) tokenField.value = "";
  importState.fetching = true;
  importState.error = "";
  markImportStale();
  if (state.page === "import") await renderPage();
  try {
    acceptImportPreview(await api("/import/link", request));
  } catch (error) {
    importState.error = error.message;
  } finally {
    request.token = "";
    importState.fetching = false;
    if (state.page === "import") await renderPage();
  }
}

async function readImportFile(file) {
  if (!file || importState.busy || importState.reading || importState.fetching) return;
  if (!/\.(txt|csv|json)$/i.test(file.name)) { setImportError("Choose a .txt, .csv, or .json file."); return; }
  if (file.size > 2 * 1024 * 1024) { setImportError("The file exceeds 2 MB. Split it into smaller files."); return; }
  try {
    importState.reading = true;
    setImportError("");
    const content = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer());
    importState.raw = content;
    importState.filename = file.name;
    importState.format = "auto";
    importState.column = null;
    markImportStale();
  } catch {
    setImportError("The file could not be read as UTF-8. Export it as UTF-8 text, CSV, or JSON.");
    return;
  } finally {
    importState.reading = false;
  }
  await previewImport();
}

async function analyzeImport() {
  if (importState.busy || importState.reading || importState.fetching || importState.stale) return;
  const selected = pendingImportRows();
  if (!selected.length) { setImportError("Select at least one valid comment."); return; }
  importState.busy = true;
  importState.error = "";
  importState.progress = { done: 0, total: selected.length };
  state.batchFilter = "";
  if (state.page === "import") await renderPage();
  try {
    for (let offset = 0; offset < selected.length; offset += 50) {
      const chunk = selected.slice(offset, offset + 50);
      const comments = chunk.map((row) => Object.fromEntries(["id", "text", "author", "posted_at", "likes", "replies", "original_id", "parent_id", "conversation_id"].map((key) => [key, row[key] || ""])));
      const response = await api("/import/analyze", { session_id: importState.preview.session_id, source: importState.preview.source, source_url: importState.preview.source_url || "", comments });
      response.items.forEach((prediction, index) => {
        chunk[index].prediction_id = prediction.id;
        chunk[index].selected = false;
        if (!importState.results.some((result) => result.id === prediction.id)) importState.results.push(prediction);
      });
      cachePredictions(response.items);
      importState.progress.done += response.items.length;
      if (state.page === "import") await renderPage();
    }
    toast(`${selected.length} imported comments analyzed. Use the result filters to review them.`);
  } catch (error) {
    importState.error = `${error.message} Completed results stay saved. Retry the remaining selection; this import session prevents duplicate saves.`;
  } finally {
    importState.busy = false;
    try { await refreshStatus(); } catch { /* Keep the import state available for retry. */ }
    if (state.page === "import") await renderPage();
  }
}

document.addEventListener("submit", (event) => {
  if (event.target.id === "import-form") { event.preventDefault(); previewImport(); }
  if (event.target.id === "import-link-form") { event.preventDefault(); fetchImportLink(); }
});

document.addEventListener("paste", (event) => {
  if (event.target.id !== "comment-input") return;
  const text = event.clipboardData?.getData("text/plain") || "";
  const source = copiedConversationSource(text);
  if (!source) return;
  event.preventDefault(); // Route before the single-comment length limit can cut off the paste.
  routeCopiedConversation(text, source);
});

document.addEventListener("input", (event) => {
  if (event.target.id === "import-link") { importState.link = event.target.value; markImportStale(); }
  if (event.target.id === "import-limit") { importState.limit = Number(event.target.value); markImportStale(); }
  if (event.target.id === "import-content") {
    importState.raw = event.target.value;
    importState.filename = "";
    markImportStale();
  }
  if (event.target.dataset.editImport) {
    const row = importRows().find((item) => item.id === event.target.dataset.editImport);
    if (row) { row.text = event.target.value; updateImportRows(); }
  }
});

document.addEventListener("change", (event) => {
  if (event.target.id === "import-sort") { importState.sort = event.target.value; markImportStale(); }
  if (event.target.id === "import-replies") { importState.includeReplies = event.target.checked; markImportStale(); }
  if (event.target.id === "import-file") readImportFile(event.target.files[0]);
  if (event.target.id === "import-format") { importState.format = event.target.value; importState.column = null; markImportStale(); }
  if (event.target.id === "import-column") { importState.column = event.target.value || null; markImportStale(); }
  if (event.target.id === "skip-duplicates") {
    importState.skipDuplicates = event.target.checked;
    updateImportRows();
  }
  if (event.target.dataset.selectImport) {
    const row = importRows().find((item) => item.id === event.target.dataset.selectImport);
    if (row) row.selected = event.target.checked;
    updateImportSelection();
  }
});

document.addEventListener("click", async (event) => {
  if (importState.busy || importState.reading || importState.fetching) return;
  const source = event.target.closest("[data-import-source]")?.dataset.importSource;
  if (source && source !== importState.source) {
    importState.source = source;
    importState.link = "";
    importState.error = "";
    importState.format = "auto";
    importState.column = null;
    markImportStale();
    await renderPage();
    return;
  }
  const action = event.target.closest("[data-import-action]")?.dataset.importAction;
  if (!action) return;
  if (action === "choose") document.getElementById("import-file").click();
  if (action === "select-all" || action === "select-none") {
    importRows().forEach((row) => { row.selected = action === "select-all" && row.valid && !row.prediction_id && !(importState.skipDuplicates && row.duplicate_of); });
    updateImportRows();
  }
  if (action === "analyze") await analyzeImport();
  if (action === "download") {
    const rows = importRows().map(({ text, author, posted_at, likes, replies, original_id, parent_id, conversation_id }) => ({ text, author, posted_at, likes, replies, original_id, parent_id, conversation_id }));
    const url = URL.createObjectURL(new Blob([JSON.stringify({ source: importState.preview.source, source_url: importState.preview.source_url || "", comments: rows }, null, 2)], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "hatelens-cleaned-comments.json";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
});

document.addEventListener("dragover", (event) => {
  const zone = event.target.closest("#import-upload");
  if (zone) { event.preventDefault(); zone.classList.add("drag-over"); }
});
document.addEventListener("dragleave", (event) => event.target.closest("#import-upload")?.classList.remove("drag-over"));
document.addEventListener("drop", (event) => {
  const zone = event.target.closest("#import-upload");
  if (!zone) return;
  event.preventDefault();
  zone.classList.remove("drag-over");
  if (event.dataTransfer.files.length !== 1) { setImportError("Choose one comment file at a time."); return; }
  readImportFile(event.dataTransfer.files[0]);
});
