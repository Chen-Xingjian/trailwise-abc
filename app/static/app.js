import { conversationStore, modelOnlyHistory } from "./chat-store.mjs?v=baseline-history";
import { factName, licenceName, monitoredName, readerAnswer, readerText, routes } from "./reader-names.mjs";

(() => {
  const $ = (id) => document.getElementById(id);
  const ui = {
    form: $("question-form"), question: $("question-input"), reference: $("reference-select"),
    ask: $("ask-button"), askText: $("ask-button-text"), clear: $("clear-question"),
    panel: $("answer-panel"), empty: $("empty-state"), loading: $("loading-state"),
    notice: $("service-notice"),
    modeButtons: [...document.querySelectorAll(".mode-button")],
    demoQuestion: $("demo-question"), demoFollowup: $("demo-followup"),
  };
  let local;
  try { local = window.localStorage; } catch { /* Private browser with no storage. */ }
  const chats = conversationStore(local);
  const actionText = {compare: "Compare answers", rag: "Ask with RAG", baseline: "Ask without RAG"};
  const state = {mode: "compare", busy: false, status: null, chat: null, freshQuestion: false};
  function title(chat) { return chat.turns[0]?.question || "New chat"; }

  function refreshReferenceOptions(scope) {
    if (!Array.isArray(scope?.allowed_reference_ids)) return;
    const allowed = [...new Set(scope.allowed_reference_ids
      .filter((id) => typeof id === "string" && id.trim())
      .map((id) => id.trim()))];
    const previous = ui.reference.value;
    const options = [element("option", "", "All routes in this guide")];
    options[0].value = "";
    for (const id of allowed) {
      const option = element("option", "", routes[id] || `Reviewed route ${options.length}`);
      option.value = id;
      options.push(option);
    }
    ui.reference.replaceChildren(...options);
    ui.reference.value = allowed.includes(previous) ? previous : "";
  }

  function showNotice(message, isError = false) {
    ui.notice.textContent = message;
    ui.notice.hidden = !message;
    ui.notice.classList.toggle("is-error", isError);
  }

  function setMode(mode) {
    if (state.mode !== mode) state.freshQuestion = true;
    state.mode = mode;
    for (const button of ui.modeButtons) {
      const active = button.dataset.mode === mode;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    }
    $("answer-mode-label").textContent = ({compare: "SIDE BY SIDE", rag: "WITH RAG", baseline: "WITHOUT RAG"})[mode];
    ui.askText.textContent = actionText[mode];
    updateConnectionNotice();
  }

  function updateConnectionNotice() {
    if (!state.status) return;
    if (!state.status.model?.connected) {
      showNotice(state.mode === "compare" ? "The local model is offline. The evidence side can still show available records; the model-only answer requires a connection." : state.mode === "rag"
        ? "The local model is not connected. You can explore retrieved evidence, clearly labelled as a preview."
        : "The local model is not connected. A model-only answer is unavailable until the model is running.");
    } else if (String(state.status.embedding?.mode || "").toLowerCase() === "hash") {
      showNotice("The local model is connected. Retrieval is in keyword preview mode; semantic retrieval has not been enabled.");
    } else {
      showNotice("");
    }
  }

  function demoParent() {
    const question = ui.demoQuestion.textContent.trim().toLowerCase();
    return state.chat?.turns.findLast(turn => turn.mode === "compare"
      && turn.question.trim().toLowerCase() === question
      && turn.data.rag?.answer_kind !== "error" && turn.data.baseline?.answer_kind !== "error");
  }

  function updateDemoButtons() {
    ui.demoQuestion.disabled = state.busy;
    ui.demoFollowup.disabled = state.busy || !demoParent();
  }

  function setBusy(busy) {
    state.busy = busy;
    ui.panel.setAttribute("aria-busy", String(busy));
    ui.ask.disabled = busy;
    ui.ask.classList.toggle("is-loading", busy);
    ui.reference.disabled = busy;
    ui.clear.disabled = busy;
    for (const button of ui.modeButtons) button.disabled = busy;
    updateDemoButtons();
    for (const button of document.querySelectorAll(".followup-form button, .reply-here, #conversation-list button")) button.disabled = busy;
    document.body.classList.toggle("is-busy", busy);
    if (busy) {
      ui.empty.hidden = true;
      ui.loading.hidden = false;
      $("loading-label").textContent = state.mode === "rag" ? "Finding relevant records…" : "Asking the local model…";
      ui.askText.textContent = "Working…";
    } else {
      ui.loading.hidden = true;
      ui.askText.textContent = actionText[state.mode];
    }
  }

  function updateCount() {
    $("character-count").textContent = `${ui.question.value.length} / 1200`;
  }

  async function requestJson(url, options = {}, timeout = 120000) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeout);
    try {
      const response = await fetch(url, { ...options, signal: controller.signal });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        let detail = data?.detail;
        if (Array.isArray(detail)) detail = detail.map((part) => part.msg || "Invalid request").join("; ");
        if (typeof detail !== "string") detail = `The request could not be completed (HTTP ${response.status}).`;
        throw new Error(detail);
      }
      if (!data || typeof data !== "object") throw new Error("The local service returned an unreadable response.");
      return data;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("The request took too long. Check the local model, then try again.");
      if (error instanceof TypeError) throw new Error("The local service could not be reached. Check that the application is running, then refresh its status.");
      throw error;
    } finally {
      window.clearTimeout(timer);
    }
  }

  async function refreshStatus() {
    $("refresh-status").disabled = true;
    try {
      const status = await requestJson("/api/status", {}, 10000);
      state.status = status;
      refreshReferenceOptions(status.scope);
      const connected = Boolean(status.model?.connected);
      $("connection-dot").className = `status-dot ${connected ? "is-connected" : "is-offline"}`;
      $("connection-label").textContent = connected ? "Local model connected" : "Evidence preview";
      $("model-status-title").textContent = connected ? "Local model connected" : "Local model not connected";
      $("model-status-detail").textContent = status.model?.message || (connected
        ? "Generated answers are available through the configured local model."
        : "Reviewed records may still be explored. Generated model answers require a local model connection.");
      const factCount = Number.isFinite(status.accepted_fact_count) ? status.accepted_fact_count : null;
      $("reviewed-fact-count").textContent = factCount === null ? "—" : String(factCount);
      $("setup-facts-count").textContent = factCount === null ? "Unavailable" : String(factCount);
      const embeddingMode = String(status.embedding?.mode || "").toLowerCase();
      const retrievalMode = String(status.index?.mode || embeddingMode).toLowerCase();
      let retrievalLabel = "Not ready";
      if (status.index?.ready) {
        retrievalLabel = embeddingMode === "hash" || retrievalMode.includes("lexical") || retrievalMode.includes("keyword")
          ? "Keyword evidence preview" : embeddingMode === "sentence-transformers" || retrievalMode.includes("semantic") || status.embedding?.ready
            ? "Semantic evidence retrieval" : "Evidence index ready";
      }
      $("setup-retrieval").textContent = retrievalLabel;
      $("release-label").textContent = status.release_id ? "Reviewed trail guide" : "Guide version unavailable";
      updateConnectionNotice();
    } catch (error) {
      state.status = null;
      $("connection-dot").className = "status-dot is-error";
      $("connection-label").textContent = "Service unavailable";
      $("model-status-title").textContent = "Local service unavailable";
      $("model-status-detail").textContent = error.message;
      $("setup-retrieval").textContent = "Unavailable";
      $("release-label").textContent = "Review release unavailable";
      showNotice(error.message, true);
    } finally {
      $("refresh-status").disabled = false;
    }
  }

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function safeSourceUrl(value) {
    try {
      const parsed = new URL(value);
      return ["https:", "http:"].includes(parsed.protocol) ? parsed.href : null;
    } catch {
      return null;
    }
  }

  function makeEvidenceCard(record, index) {
    const card = element("article", "evidence-card");
    const top = element("div", "evidence-card-top");
    top.append(element("span", "fact-id", `[${index + 1}] ${factName(record.fact_id)}`));
    top.append(element("span", "reference-id", routes[record.reference_id] || ""));
    card.append(top, element("p", "evidence-text", readerText((record.text || "").replace(/^Reference: [^\n]+\n/, "")) || "No record text was supplied."));
    const provenances = Array.isArray(record.source_records)
      ? record.source_records.filter((source) => source && typeof source === "object") : [];
    const sources = provenances.length ? provenances : [record];
    for (const [index, provenance] of sources.entries()) {
      const item = element("div", "provenance-item");
      if (sources.length > 1) item.append(element("span", "provenance-number", `Source ${index + 1} of ${sources.length}`));
      item.append(makeProvenance(provenance));
      card.append(item);
    }
    return card;
  }

  function externalLink(text, value, className) {
    const href = safeSourceUrl(value);
    const source = element(href ? "a" : "span", className, `${text}${href ? " ↗" : ""}`);
    if (href) {
      source.href = href;
      source.target = "_blank";
      source.rel = "noopener noreferrer";
    }
    return source;
  }

  function makeProvenance(provenance) {
    const container = element("div", "provenance-content");
    const sourceRow = element("div", "evidence-source-row");
    sourceRow.append(
      externalLink(provenance.source_title || "Source", provenance.source_url, "evidence-source"),
      externalLink(licenceName(provenance.licence_id), provenance.licence_url, "licence-label"),
    );
    container.append(sourceRow);
    if (provenance.source_locator) container.append(element("p", "source-locator", readerText(provenance.source_locator)));
    const historyUrl = provenance.history_url || provenance.history_link;
    if (provenance.attribution || provenance.additional_notice || historyUrl) {
      const details = element("details", "attribution-details");
      details.append(element("summary", "", "Attribution & reuse"));
      if (provenance.attribution) details.append(element("p", "attribution-text", readerText(provenance.attribution)));
      if (provenance.additional_notice) details.append(element("p", "attribution-notice", readerText(provenance.additional_notice)));
      if (historyUrl) details.append(externalLink("Contributor history", historyUrl, "history-link"));
      container.append(details);
    }
    return container;
  }

  function appendInlineText(parent, text) {
    const bold = /\*\*([^*\n]+)\*\*/g;
    let cursor = 0;
    for (const match of text.matchAll(bold)) {
      if (match.index > cursor) parent.append(document.createTextNode(text.slice(cursor, match.index)));
      parent.append(element("strong", "", match[1]));
      cursor = match.index + match[0].length;
    }
    if (cursor < text.length) parent.append(document.createTextNode(text.slice(cursor)));
  }

  function renderAnswerText(text, container) {
    container.replaceChildren();
    let paragraph = [];
    let list = null;
    let listKind = "";
    let insideUnsupportedFence = false;
    function flushParagraph() {
      if (!paragraph.length) return;
      const p = element("p", "");
      appendInlineText(p, paragraph.join("\n"));
      container.append(p);
      paragraph = [];
    }
    for (const line of text.replace(/\r\n?/g, "\n").split("\n")) {
      if (/^\s*```/.test(line) || insideUnsupportedFence) {
        flushParagraph();
        list = null;
        listKind = "";
        container.append(element("p", "", line));
        if (/^\s*```/.test(line)) insideUnsupportedFence = !insideUnsupportedFence;
        continue;
      }
      if (!line.trim()) {
        flushParagraph();
        list = null;
        listKind = "";
        continue;
      }
      const bullet = line.match(/^[-*+]\s+(.+)$/);
      const numbered = line.match(/^(\d{1,3})[.)]\s+(.+)$/);
      if (bullet || numbered) {
        flushParagraph();
        const kind = bullet ? "ul" : "ol";
        if (!list || listKind !== kind) {
          list = element(kind, "");
          if (numbered) list.start = Number(numbered[1]);
          container.append(list);
          listKind = kind;
        }
        const item = element("li", "");
        if (numbered) item.value = Number(numbered[1]);
        appendInlineText(item, bullet ? bullet[1] : numbered[2]);
        list.append(item);
      } else {
        list = null;
        listKind = "";
        paragraph.push(line);
      }
    }
    flushParagraph();
  }

  function friendlyModelName(value) {
    if (/models--[^/\\]+[/\\]snapshots[/\\]/i.test(value) && /qwen3\.5[-_]4b/i.test(value)) {
      return "Qwen3.5-4B-4bit";
    }
    return value;
  }

  const replyForm = $("reply-template").content.firstElementChild.cloneNode(true);
  const replyInput = replyForm.querySelector("textarea");
  const replyError = replyForm.querySelector(".reply-error");
  const replyDrafts = new Map();
  let replyTurn = null;

  function attachReply(turn, article) {
    if (replyTurn && replyForm.parentElement) {
      replyForm.parentElement.querySelector(".reply-here").hidden = false;
      if (replyInput.value) replyDrafts.set(replyTurn.id, replyInput.value);
      else replyDrafts.delete(replyTurn.id);
    }
    replyTurn = turn;
    replyInput.value = replyDrafts.get(turn.id) || "";
    replyError.hidden = true;
    const paired = turn.mode === "compare";
    replyForm.querySelector("label span").textContent = paired ? "Follow up on both answers" : "Follow up on this answer";
    const focus = paired ? turn.data.rag?.trail_focus : turn.data.trail_focus;
    replyForm.querySelector('[data-part="followup-focus"]').textContent =
      focus?.places?.join(" → ") || routes[focus?.reference] || focus?.route || "";
    article.querySelector(".reply-here").hidden = true;
    article.append(replyForm);
  }
  replyForm.addEventListener("submit", event => {
    event.preventDefault();
    if (replyTurn) submit(replyInput, replyTurn, replyError);
  });
  replyInput.addEventListener("keydown", event => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      if (!state.busy) replyForm.requestSubmit();
    }
  });

  function renderResponse(data) {
    const section = $("response-template").content.firstElementChild.cloneNode(true);
    const part = name => section.querySelector(`[data-part="${name}"]`);
    const records = Array.isArray(data.evidence) ? data.evidence.filter((record) => record && typeof record === "object") : [];
    const raw = typeof data.answer === "string" ? data.answer : "No answer was returned.";
    const readable = readerAnswer(raw, records);
    renderAnswerText(readable, part("answer-text"));
    const sources = part("evidence-section");
    sources.open = false;
    sources.hidden = !(records.length || Object.keys(data.verification_rules || {}).length || data.itinerary_sources?.length || data.distance_guide || data.live || data.notice_result);
    const clarification = data.answer_kind === "clarification";
    const preview = data.answer_kind === "evidence_preview";
    const error = data.answer_kind === "error";
    const limit = data.answer_kind === "scope_limit";
    const kind = part("answer-kind");
    kind.className = `answer-kind${preview ? " is-preview" : error ? " is-error" : limit ? " is-limit" : ""}`;
    kind.textContent = data.answer_kind === "activity_calculation" ? "Your activity readings" : data.answer_kind === "stage_measurement" ? "Reviewed stage measurement" : data.answer_kind === "reviewed_guidance" ? "Reviewed guidance" : data.answer_kind === "packing_list" ? "Packing checklist" : data.answer_kind === "variant_plan" ? "Published itinerary comparison" : data.answer_kind === "itinerary_budget" ? "Itinerary planning" : data.answer_kind === "route_distance" ? (data.distance_guide.used ? "Guide estimate" : "Distance check") : data.answer_kind === "live_result" ? "External source check" : data.answer_kind === "live_clarification" ? "Follow-up question" : clarification ? "Walking window needed" : preview ? "Evidence preview — model not connected"
      : data.answer_kind === "window_summary" ? "Walking window and planning evidence"
        : error ? "Answer unavailable"
        : limit ? "Evidence or scope limit"
          : data.mode === "baseline" ? "Model-only answer" : "Answer with retrieved evidence";
    part("preview-explanation").hidden = !preview;
    const latency = typeof data.latency_ms === "number" ? data.latency_ms : Number.NaN;
    part("response-time").textContent = Number.isFinite(latency) ? `${(latency / 1000).toFixed(1)} s` : "";
    const warningList = Array.isArray(data.warnings) ? data.warnings.filter((item) => typeof item === "string") : [];
    const warnings = part("answer-warnings");
    warnings.replaceChildren(...warningList.map((text) => element("p", "", readerText(text))));
    warnings.hidden = warningList.length === 0;
    const evidenceList = part("evidence-list");
    evidenceList.replaceChildren();
    part("evidence-count").textContent = records.length ? `${records.length} retrieved` : "";
    for (const rule of Object.values(data.verification_rules || {})) {
      evidenceList.append(element("p", "source-locator", "Reviewed verification rule · " + rule));
    }
    for (const source of data.itinerary_sources || []) {
      evidenceList.append(externalLink(source.label + " · " + source.publisher, source.url, "evidence-source"),
        element("p", "source-locator", source.locator));
    }
    if (data.distance_guide) {
      evidenceList.append(externalLink(data.distance_guide.title, data.distance_guide.url, "evidence-source"));
      if (data.distance_guide.checked_at_utc) evidenceList.append(element("p", "source-locator",
        "Guide checked " + nepalTime(data.distance_guide.checked_at_utc)));
    }
    for (const live of [data.live, data.notice_result].filter(Boolean)) {
      renderLiveSource(live, evidenceList);
    }
    evidenceList.append(...records.map(makeEvidenceCard));
    if (records.length && readerAnswer(raw, records, true) !== readable) {
      const trace = element("details", "attribution-details");
      trace.append(element("summary", "", "Answer with source numbers"), element("p", "evidence-text", readerAnswer(raw, records, true)));
      evidenceList.append(trace);
    }
    const footerParts = [];
    if (typeof data.model_id === "string" && data.model_id) footerParts.push(`Model: ${friendlyModelName(data.model_id)}`);
    if (data.retrieval?.mode) {
      const mode = String(data.retrieval.mode).toLowerCase();
      footerParts.push(mode === "hash" || mode.includes("lexical") || mode.includes("keyword")
        ? "Keyword retrieval (diagnostic)"
        : mode === "sentence-transformers" || mode.includes("semantic") ? "Semantic evidence retrieval" : `Retrieval: ${data.retrieval.mode}`);
    }
    if (preview) footerParts.push("Preview only; no model answer generated");
    part("answer-footer").textContent = footerParts.join(" · ");
    part("answer-footer").hidden = !footerParts.length;
    return section;
  }

  function comparisonCard(mode, data) {
    const card = element("section", "comparison-card " + mode);
    card.append(element("h4", "comparison-title", mode === "rag" ? "With RAG" : "Without RAG"),
      element("p", "comparison-description", mode === "rag" ? "Uses the reviewed trail guide" : "Same model · public live checks available · no guide documents"));
    if (data) card.append(renderResponse(data));
    else card.append(element("p", "comparison-pending", "Waiting for an answer…"));
    return card;
  }

  function renderTurn(turn) {
    const {data, question} = turn;
    const article = $("answer-template").content.firstElementChild.cloneNode(true);
    article.dataset.turnId = turn.id;
    const part = name => article.querySelector(`[data-part="${name}"]`);
    part("asked-question").textContent = question;
    const parent = state.chat.turns.find(item => item.id === turn.parent);
    if (parent && state.chat.turns.indexOf(parent) + 1 !== state.chat.turns.indexOf(turn)) {
      article.prepend(element("p", "branch-label", "Reply to: " + parent.question));
    }
    const responses = article.querySelector(".turn-responses");
    if (turn.mode === "compare") {
      responses.classList.add("compared");
      responses.append(comparisonCard("rag", data.rag), comparisonCard("baseline", data.baseline));
    } else {
      responses.append(renderResponse(data));
    }
    const replyButton = article.querySelector(".reply-here");
    replyButton.addEventListener("click", () => {
      if (state.busy) return;
      attachReply(turn, article);
      replyInput.focus();
    });
    $("chat-history").append(article);
    if (turn.id === state.chat.turns.at(-1)?.id) attachReply(turn, article);
    return article;
  }

  function editChat(id, edit) {
    return navigator.locks ? navigator.locks.request(chats.prefix + id, edit) : edit();
  }

  function renderList() {
    const list = $("conversation-list");
    list.replaceChildren();
    for (const chat of chats.list()) {
      const row = element("li", "chat-list-row");
      const open = element("button", "chat-list-title", title(chat));
      open.title = title(chat);
      open.setAttribute("aria-current", String(chat.id === state.chat?.id));
      open.addEventListener("click", () => { if (!state.busy) openChat(chat.id); });
      const remove = element("button", "chat-delete", "Delete");
      remove.setAttribute("aria-label", "Delete chat: " + title(chat));
      remove.addEventListener("click", () => {
        if (state.busy) return;
        const confirm = element("button", "chat-delete", "Confirm delete");
        confirm.setAttribute("aria-label", "Confirm delete: " + title(chat));
        const cancel = element("button", "chat-delete", "Keep");
        cancel.addEventListener("click", () => { renderList(); });
        confirm.addEventListener("click", async () => {
          if (state.busy) return;
          confirm.disabled = true;
          try { await editChat(chat.id, () => chats.remove(chat.id)); }
          catch { confirm.disabled = false; showNotice("This browser could not delete the conversation.", true); return; }
          if (chat.id === state.chat?.id) openChat(chats.list()[0]?.id);
          else renderList();
        });
        row.replaceChildren(open, confirm, cancel);
        cancel.focus();
      });
      row.append(open, remove);
      list.append(row);
    }
    $("storage-note").textContent = chats.persistent() ? "Saved in this browser." : "Browser storage unavailable. This session is held in memory.";
  }

  function openChat(id) {
    state.chat = (id && chats.read(id)) || chats.create();
    try { sessionStorage.setItem("trailwise.activeChat", state.chat.id); } catch { /* optional */ }
    replyForm.remove();
    replyDrafts.clear();
    replyTurn = null;
    $("chat-history").replaceChildren();
    ui.empty.hidden = state.chat.turns.length > 0;
    state.freshQuestion = false;
    ui.question.value = "";
    ui.question.setCustomValidity("");
    ui.reference.value = "";
    setMode(state.chat.turns.at(-1)?.mode || "compare");
    state.freshQuestion = false;
    updateCount();
    state.chat.turns.forEach(renderTurn);
    updateDemoButtons();
    renderList();
  }

  async function fetchAnswer(question, mode, reference, previous, parent) {
    if (mode === "baseline") {
      const payload = {question, mode, reference_id: reference, offer_live_checks: true, chat_context: previous?.chat_context, baseline_history: modelOnlyHistory(state.chat.turns, parent)};
      while (payload.baseline_history.length && new TextEncoder().encode(JSON.stringify(payload)).length > 16384) {
        payload.baseline_history.shift();
      }
      return requestJson("/api/ask", {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload)});
    }
    return requestJson("/api/ask", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({question, mode, reference_id: reference, top_k: 3, offer_live_checks: mode === "rag",
        chat_context: previous?.chat_context, trail_focus: previous?.trail_focus,
        prior_plan: previous?.planning_budget ?? (previous?.answer_kind === "variant_plan" ? {} : undefined),
        prior_planning_question: previous?.planning_question, variant_context: previous?.variant_context,
        distance_followup: previous?.answer_kind === "route_distance",
        planning_followup: ["clarification", "itinerary_budget"].includes(previous?.answer_kind)}),
    });
  }

  async function compareAnswers(question, reference, previous, pending, parent) {
    pending.append(element("p", "asked-question", question));
    const cards = element("div", "turn-responses compared");
    pending.append(cards);
    const modes = ["rag", "baseline"];
    cards.append(...modes.map(mode => comparisonCard(mode, null)));
    $("chat-history").append(pending);
    pending.scrollIntoView({block: "start", behavior: "smooth"});
    const results = {};
    // The local generator serves one completion at a time. Each arm carries only its own state.
    for (const mode of modes) {
      $("loading-label").textContent = mode === "rag" ? "Checking the trail guide…" : "Getting the answer without RAG…";
      try {
        results[mode] = await fetchAnswer(question, mode, reference, previous?.[mode], parent);
      } catch (error) {
        results[mode] = {mode, answer_kind: "error", answer: error.message, evidence: []};
      }
      cards.querySelector("." + mode).replaceWith(comparisonCard(mode, results[mode]));
    }
    return results;
  }

  async function submit(input, parent, errorBox) {
    if (state.busy || !input.reportValidity()) return;
    const question = input.value.trim();
    if (!question) { input.focus(); return; }
    const chatId = state.chat.id;
    const mode = parent?.mode || state.mode;
    const reference = parent ? parent.reference : (ui.reference.value || null);
    const previous = parent?.data;
    const pending = element("article", "conversation-turn");
    setBusy(true);
    if (errorBox) errorBox.hidden = true;
    try {
      const data = mode === "compare"
        ? await compareAnswers(question, reference, previous, pending, parent)
        : await fetchAnswer(question, mode, reference, previous, parent);
      pending.remove();
      const turn = {id: crypto.randomUUID(), parent: parent?.id || null, mode, reference, question, data};
      const saved = await editChat(chatId, () => chats.append(chatId, turn));
      if (!saved) { openChat(chats.list()[0]?.id); return; }
      if (input.value.trim() === question) input.value = "";
      const priorCount = state.chat.turns.length;
      state.chat = saved;
      if (saved.turns.length !== priorCount + 1) openChat(saved.id);
      else {
        renderTurn(turn);
        renderList();
      }
      ui.empty.hidden = true;
      state.freshQuestion = false;
      updateCount();
      const answer = $("chat-history").lastElementChild;
      answer.scrollIntoView({block: "start", behavior: "smooth"});
    } catch (error) {
      if (errorBox) { errorBox.textContent = error.message; errorBox.hidden = false; }
      else showNotice(error.message, true);
    } finally {
      pending.remove();
      setBusy(false);
      ui.empty.hidden = Boolean(state.chat.turns.length);
    }
  }

  ui.form.addEventListener("submit", event => {
    event.preventDefault();
    submit(ui.question, state.freshQuestion ? null : state.chat.turns.at(-1), null);
  });

  ui.question.addEventListener("input", () => {
    ui.question.setCustomValidity("");
    updateCount();
  });
  ui.question.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      if (!state.busy) ui.form.requestSubmit();
    }
  });
  ui.clear.addEventListener("click", () => {
    if (state.chat.turns.length) openChat();
    else openChat(state.chat.id);
    ui.question.focus();
  });
  ui.reference.addEventListener("change", () => { state.freshQuestion = true; });
  for (const button of ui.modeButtons) button.addEventListener("click", () => setMode(button.dataset.mode));
  ui.demoQuestion.addEventListener("click", () => {
    setMode("compare");
    state.freshQuestion = true;
    ui.reference.value = "";
    ui.question.value = ui.demoQuestion.textContent.trim();
    ui.question.setCustomValidity("");
    updateCount();
    ui.question.focus();
  });
  ui.demoFollowup.addEventListener("click", () => {
    const parent = demoParent();
    if (!parent) return;
    const article = $("chat-history").querySelector(`[data-turn-id="${CSS.escape(parent.id)}"]`);
    attachReply(parent, article);
    replyInput.value = ui.demoFollowup.textContent.trim();
    replyInput.focus();
  });
  $("refresh-status").addEventListener("click", refreshStatus);
  document.addEventListener("click", (event) => {
    if (!$("system-details").contains(event.target)) $("system-details").open = false;
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") $("system-details").open = false;
  });
  function nepalTime(timestamp) {
    return new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Kathmandu", day: "2-digit", month: "short",
      year: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(new Date(timestamp)) + " NPT";
  }

  function renderLiveSource(data, target) {
    const meta = element("p", "source-locator", "Checked " + nepalTime(data.checked_at_utc) + " · ");
    meta.append(externalLink(data.model || data.publisher, data.source, "evidence-source"));
    if (data.model) {
      meta.append(document.createTextNode(" · "), externalLink("CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/", "evidence-source"),
        document.createTextNode(" · Route points adapted from "), externalLink("KeiTreks GPX", "https://keitreks.com/gpx", "evidence-source"));
    }
    if (data.status === "forecast") {
      if (data.run_initialised_utc) meta.append(document.createTextNode(" · Model run " + nepalTime(data.run_initialised_utc)));
      if (data.period === "day") meta.append(document.createTextNode(" · Daily forecast in Nepal time"));
      meta.append(document.createTextNode(" · Grid centre " + data.grid_distance_km + " km from the route point"));
    }
    if (data.feed_updated_utc) meta.append(document.createTextNode(" · Feed updated " + nepalTime(data.feed_updated_utc)));
    target.append(meta);
    if (data.hours?.length) {
      const detail = element("details", "hourly-details");
      detail.append(element("summary", "", "Hourly forecast · Nepal time"));
      const table = element("table", "forecast-table");
      const header = table.createTHead().insertRow();
      for (const label of ["Time", "°C", "Precip. mm", "Snow cm", "Gust km/h"]) header.append(element("th", "", label));
      const tbody = table.createTBody();
      for (const hour of data.hours) {
        const row = tbody.insertRow();
        for (const value of [hour.local_time.slice(11), hour.temperature_2m, hour.precipitation, hour.snowfall, hour.wind_gusts_10m])
          row.insertCell().textContent = value ?? "—";
      }
      detail.append(table, element("p", "source-locator", "Samples bracket the walking window. Precipitation, snow and maximum gust refer to the preceding hour."));
      target.append(detail);
    }
    if (data.municipal) renderLocalSources(data, target);
    for (const item of data.items || []) {
      const row = element("p", "");
      row.append(externalLink(item.title, item.url, "evidence-source"), document.createTextNode(" · " + (item.published_utc || "Date unverified")));
      target.append(row);
    }
  }

  function renderLocalSources(data, target) {
    const local = data.municipal;
    target.append(externalLink(local.publisher, local.source, "evidence-source"));
    for (const item of local.items) {
      const row = element("p", "");
      row.append(externalLink(item.title, item.url, "evidence-source"), document.createTextNode(" · Observation time unverified"));
      target.append(row);
    }
    for (const item of data.contacts) {
      const row = element("p", "");
      row.append(externalLink(item.name, item.source, "evidence-source"), document.createTextNode(" · " + item.use));
      target.append(row);
    }
    for (const item of data.field_reports) {
      const row = element("p", "");
      row.append(externalLink(item.publisher, item.source_url, "evidence-source"),
        document.createTextNode(" · " + item.section + " · " + item.subject + " · " + item.observation
        + " · Observed " + nepalTime(item.observed_at) + " · Published " + nepalTime(item.published_at)
        + " · " + item.validity + (item.valid_until ? " (" + nepalTime(item.valid_until) + ")" : "")));
      target.append(row);
    }
    if (data.invalid_field_reports) target.append(element("p", "", "Some field reports could not be verified and have been withheld."));
  }

  $("source-watch").addEventListener("toggle", async (event) => {
    if (!event.currentTarget.open) return;
    const target = $("source-watch-result");
    try {
      const report = await requestJson("/api/source-audit");
      target.replaceChildren(element("p", "", report.checked_at ? "Last scan " + nepalTime(report.checked_at) : (report.error || "No scan recorded for this release.")));
      for (const item of report.targets) {
        const row = element("p", "");
        row.append(externalLink(monitoredName(item.id), item.url, "evidence-source"), document.createTextNode(" · " + item.comparison
          + " · " + item.availability + " · checked " + nepalTime(item.last_attempt)));
        if (item.comparison === "changed" || item.availability === "unavailable")
          row.append(document.createTextNode(" · Review " + item.facts.map(factName).join(", ")));
        target.append(row);
      }
      if (report.manual_fact_ids?.length) target.append(element("p", "", "Manual review only: " + report.manual_fact_ids.map(factName).join(", ")));
    } catch (error) { target.textContent = error.message; }
  });
  let active;
  try { active = sessionStorage.getItem("trailwise.activeChat"); } catch { /* optional */ }
  const existing = chats.list();
  openChat(existing.some(chat => chat.id === active) ? active : existing[0]?.id);
  window.addEventListener("storage", event => {
    if (state.busy || (event.key !== null && !event.key.startsWith(chats.prefix))) return;
    if (!chats.read(state.chat.id)) openChat(chats.list()[0]?.id);
    else if (event.key === chats.prefix + state.chat.id) openChat(state.chat.id);
    else renderList();
  });
  refreshStatus();
})();
