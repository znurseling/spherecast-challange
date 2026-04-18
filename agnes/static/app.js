/*  Agnes Chat — app.js  */
const API_KEY = "devkey";
const HEADERS = { "Content-Type": "application/json", "X-API-Key": API_KEY };

const $messages   = document.getElementById("messagesContainer");
const $input      = document.getElementById("chatInput");
const $btnSend    = document.getElementById("btnSend");
const $btnMic     = document.getElementById("btnMic");
const $btnSpeaker = document.getElementById("btnSpeaker");
const $audioViz   = document.getElementById("audioVisualizer");
const $status     = document.getElementById("statusText");

const $chatPanel        = document.getElementById("chatPanel");
const $inventoryPanel   = document.getElementById("inventoryPanel");
const $btnAskAgnes      = document.getElementById("btnAskAgnes");
const $btnViewInventory = document.getElementById("btnViewInventory");
const $inventoryContainer = document.getElementById("inventoryContainer");

let ttsEnabled = false;
let isRecording = false;
let recognition = null;
let chatHistory = []; // Local memory for the session

/* ── Init ─────────────────────────────────────── */
document.addEventListener("DOMContentLoaded", () => {
  loadDashboard();
  addBotMessage({
    type: "text",
    message: "👋 Hello! I'm **Agnes**, your intelligent Supply Chain companion.\n\nI'm here to help you optimize your sourcing and analyze your data. My core capabilities include:\n\n- **Inventory Tracking**: I can help you review the current raw materials provided by your suppliers.\n- **Consolidation Analysis**: I identify highly fragmented materials that are perfect candidates for supplier consolidation.\n- **Substitution Checking**: I can reason about whether one raw material can safely replace another.\n- **Smart Recommendations**: I provide AI-powered advice on how to streamline your sourcing and reduce supplier redundancy.\n\nJust type or click the microphone to ask me anything about your supply chain!"
  });
  setupSpeechRecognition();
});

/* ── Dashboard sidebar ────────────────────────── */
async function loadDashboard() {
  try {
    const r = await fetch("/api/v1/dashboard", { headers: HEADERS });
    if (!r.ok) throw new Error(r.status);
    const d = await r.json();
    $status.textContent = "Agnes Online";
  } catch {
    $status.textContent = "Offline — start server";
  }
}

/* ── Inventory Panel ──────────────────────────── */
async function loadInventory() {
  $chatPanel.style.display = "none";
  $inventoryPanel.style.display = "flex";
  $inventoryContainer.innerHTML = '<div style="color:var(--text-muted);text-align:center;">Loading inventory...</div>';
  try {
    const r = await fetch("/api/v1/inventory", { headers: HEADERS });
    if (!r.ok) throw new Error(r.status);
    const data = await r.json();
    
    let html = '<div style="display:flex;flex-direction:column;gap:12px;">';
    for (const sup of data) {
      html += `
        <details class="supplier-toggle stat-card" style="margin-bottom:0; padding: 0;">
          <summary style="padding: 16px; cursor: pointer; font-size: 15px; color: var(--text-primary); font-weight: 600; outline: none; list-style: none; display: flex; justify-content: space-between; align-items: center;">
            ${sup.supplier_name}
            <div style="display:flex;align-items:center;gap:12px;">
              <span style="font-size: 11px; font-weight: 500; color: var(--text-muted); background: rgba(255,255,255,0.05); padding: 4px 8px; border-radius: 12px;">${sup.materials.length} Materials</span>
              <svg class="chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
            </div>
          </summary>
          <div style="padding: 0 16px 16px 16px;">
          <table class="rich-table" style="width:100%;text-align:left;margin-top:0;">
            <thead><tr><th>Canonical Name</th><th>Type</th><th>No. of Suppliers</th></tr></thead>
            <tbody>
      `;
      for (const mat of sup.materials) {
        html += `<tr>
          <td style="font-weight: 500;">${mat.canonical_name || "—"}</td>
          <td><span style="background: rgba(0, 184, 255, 0.1); color: var(--accent); padding: 3px 6px; border-radius: 4px; font-size: 11px;">${mat.type}</span></td>
          <td>${mat.supplier_count || 1}</td>
        </tr>`;
      }
      html += `</tbody></table></div></details>`;
    }
    html += '</div>';
    $inventoryContainer.innerHTML = html;
  } catch (e) {
    $inventoryContainer.innerHTML = `<div style="color:var(--red);">Error loading inventory: ${e.message}</div>`;
  }
}

function showChat() {
  $inventoryPanel.style.display = "none";
  $chatPanel.style.display = "flex";
  scrollBottom();
}

/* ── Send message ─────────────────────────────── */
async function sendMessage(text) {
  if (!text.trim()) return;
  
  const currentHistory = [...chatHistory]; // Clone current state
  addUserMessage(text);
  chatHistory.push({ role: "user", content: text });
  
  $input.value = "";
  const typingEl = showTyping();

  try {
    const r = await fetch("/api/v1/chat", {
      method: "POST", headers: HEADERS,
      body: JSON.stringify({ message: text, history: currentHistory }),
    });
    removeTyping(typingEl);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    addBotMessage(data);
    
    // Store Agnes' response in history for next turn
    chatHistory.push({ role: "bot", content: data.message });
    
    if (ttsEnabled) speak(data.message);
    if (data.intent === "dashboard") loadDashboard();
  } catch (e) {
    removeTyping(typingEl);
    addBotMessage({ type: "text", message: `❌ Error: ${e.message}. Is the server running?` });
  }
}

/* ── Message rendering ────────────────────────── */
function addUserMessage(text) {
  const el = msgWrap("user");
  el.querySelector(".msg-bubble").textContent = text;
  $messages.appendChild(el);
  scrollBottom();
}

function addBotMessage(data) {
  const el = msgWrap("bot");
  const bubble = el.querySelector(".msg-bubble");
  bubble.innerHTML = md(data.message || "");

  if (data.data) {
    switch (data.type) {
      case "dashboard":   bubble.appendChild(renderCards(data.data.cards)); break;
      case "table":       bubble.appendChild(renderTable(data.data)); break;
      case "product":     bubble.appendChild(renderProduct(data.data)); break;
      case "substitution":bubble.appendChild(renderSubstitution(data.data)); break;
      case "recommendation":  bubble.appendChild(renderRecommendation(data.data)); break;
      case "recommendations": bubble.appendChild(renderRecommendations(data.data)); break;
    }
  }
  $messages.appendChild(el);
  scrollBottom();
}

function msgWrap(role) {
  const div = document.createElement("div");
  div.className = `message ${role}`;
  div.innerHTML = `
    <div class="msg-avatar">${role === "bot" ? '<img src="/static/logo.png" alt="Agnes">' : "👤"}</div>
    <div>
      <div class="msg-bubble"></div>
      <div class="msg-time">${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</div>
    </div>`;
  return div;
}

function showTyping() {
  const el = msgWrap("bot");
  el.querySelector(".msg-bubble").innerHTML = '<div class="typing-indicator"><span></span><span></span><span></span></div>';
  el.id = "typing-msg";
  $messages.appendChild(el);
  scrollBottom();
  return el;
}
function removeTyping(el) { if (el && el.parentNode) el.parentNode.removeChild(el); }
function scrollBottom() { $messages.scrollTop = $messages.scrollHeight; }

/* ── Rich renderers ───────────────────────────── */
function renderCards(cards) {
  const wrap = document.createElement("div");
  wrap.className = "rich-cards";
  cards.forEach(c => {
    wrap.innerHTML += `<div class="rich-card"><div class="card-icon">${c.icon}</div><div class="card-value">${c.value}</div><div class="card-label">${c.label}</div></div>`;
  });
  return wrap;
}

function renderTable(data) {
  const wrap = document.createElement("div");
  wrap.style.overflowX = "auto";
  let html = '<table class="rich-table"><thead><tr>';
  data.columns.forEach(c => html += `<th>${c.label}</th>`);
  html += "</tr></thead><tbody>";
  data.rows.forEach(r => {
    html += "<tr>";
    data.columns.forEach(c => html += `<td>${r[c.key] ?? "—"}</td>`);
    html += "</tr>";
  });
  html += "</tbody></table>";
  wrap.innerHTML = html;
  return wrap;
}

function renderProduct(d) {
  const wrap = document.createElement("div");
  wrap.innerHTML = `
    <div class="product-field"><span class="field-label">SKU</span><div class="field-value"><code>${d.sku || "—"}</code></div></div>
    <div class="product-field"><span class="field-label">Canonical Name</span><div class="field-value">${d.canonical_name} <small>(${(d.confidence * 100).toFixed(0)}%)</small></div></div>
    <div class="product-field"><span class="field-label">Type</span><div class="field-value">${d.type}</div></div>
    <div class="product-field"><span class="field-label">Suppliers (${d.suppliers.length})</span><div class="field-value">${d.suppliers.map(s => s.name).join(", ") || "—"}</div></div>
    <div class="product-field"><span class="field-label">Consumed by (${d.companies.length} companies)</span><div class="field-value">${d.companies.map(c => c.name).join(", ") || "—"}</div></div>
    <div class="product-field"><span class="field-label">BOMs</span><div class="field-value">${d.bom_count}</div></div>
    ${renderEvidence(d.evidence)}`;
  return wrap;
}

function renderSubstitution(d) {
  const wrap = document.createElement("div");
  const vClass = d.verdict.includes("ACCEPT") ? "verdict-accept" : d.verdict.includes("REVIEW") ? "verdict-review" : "verdict-reject";
  wrap.innerHTML = `
    <div style="display:flex;gap:12px;margin:10px 0;flex-wrap:wrap;">
      <div class="rich-card" style="flex:1;min-width:120px"><div class="card-label">Material A</div><div class="card-value" style="font-size:14px">${d.product_a.canonical}</div><div class="card-label">ID: ${d.product_a.id}</div></div>
      <div style="display:flex;align-items:center;font-size:22px">⇄</div>
      <div class="rich-card" style="flex:1;min-width:120px"><div class="card-label">Material B</div><div class="card-value" style="font-size:14px">${d.product_b.canonical}</div><div class="card-label">ID: ${d.product_b.id}</div></div>
    </div>
    <div class="verdict-badge ${vClass}">${d.verdict}</div>
    <div style="margin:6px 0;color:var(--text-secondary);font-size:13px">Confidence: <strong>${(d.confidence * 100).toFixed(0)}%</strong> · Mode: <strong>${d.mode}</strong></div>
    <div style="margin:8px 0;font-size:13px">${d.reasoning}</div>
    ${renderEvidence(d.evidence)}`;
  return wrap;
}

function renderRecommendation(d) {
  const wrap = document.createElement("div");
  if (!d.recommendation) {
    wrap.innerHTML = `<p style="color:var(--text-muted)">No recommendation available.</p>`;
    return wrap;
  }
  const rec = d.recommendation;
  wrap.innerHTML = `
    <div class="rec-supplier">
      <div class="card-label">Consolidate under</div>
      <div class="supplier-name">${rec.consolidate_under_supplier_name}</div>
      <div style="margin-top:8px;font-size:12px;color:var(--text-secondary)">
        Cluster: ${rec.cluster_size} products · Current suppliers: ${rec.current_supplier_count}
      </div>
    </div>
    ${d.tradeoffs && d.tradeoffs.length ? d.tradeoffs.map(t => `<div class="tradeoff-item">⚠️ ${t}</div>`).join("") : ""}
    ${renderEvidence(d.evidence)}`;
  return wrap;
}

function renderRecommendations(d) {
  const wrap = document.createElement("div");
  (d.recommendations || []).forEach((r, i) => {
    const card = document.createElement("div");
    card.style.cssText = "margin-top:12px;padding-top:12px;border-top:1px solid var(--border)";
    card.innerHTML = `<strong>${i + 1}. ${r.canonical_name || "Product " + r.product_id}</strong>`;
    card.appendChild(renderRecommendation(r));
    wrap.appendChild(card);
  });
  return wrap;
}

function renderEvidence(evidence) {
  if (!evidence || !evidence.length) return "";
  return `<div class="evidence-list">${evidence.map(e =>
    `<div class="evidence-item"><span class="evidence-source">${e.source}</span><span class="evidence-detail">${e.detail}</span></div>`
  ).join("")}</div>`;
}

/* ── Markdown (minimal) ──────────────────────── */
function md(text) {
  return text
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/`(.+?)`/g, "<code>$1</code>")
    .replace(/\n/g, "<br>");
}

/* ── Speech Recognition ───────────────────────── */
function setupSpeechRecognition() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { $btnMic.style.display = "none"; return; }
  recognition = new SR();
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.lang = "en-US";

  recognition.onresult = (e) => {
    const text = e.results[0][0].transcript;
    $input.value = text;
    sendMessage(text);
  };
  recognition.onend = () => stopRecording();
  recognition.onerror = () => stopRecording();
}

function toggleRecording() {
  if (isRecording) { recognition.stop(); stopRecording(); }
  else { recognition.start(); startRecording(); }
}
function startRecording() {
  isRecording = true;
  $btnMic.classList.add("recording");
  $audioViz.classList.add("active");
}
function stopRecording() {
  isRecording = false;
  $btnMic.classList.remove("recording");
  $audioViz.classList.remove("active");
}

/* ── Text-to-Speech ───────────────────────────── */
function toggleTTS() {
  ttsEnabled = !ttsEnabled;
  const svgOff = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon><line x1="23" y1="9" x2="17" y2="15"></line><line x1="17" y1="9" x2="23" y2="15"></line></svg>';
  const svgOn = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon><path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"></path></svg>';
  $btnSpeaker.innerHTML = ttsEnabled ? svgOn : svgOff;
  $btnSpeaker.classList.toggle("active", ttsEnabled);
}

function speak(text) {
  if (!window.speechSynthesis) return;
  window.speechSynthesis.cancel();

  // Clean markdown and HTML for speech
  const clean = text.replace(/\*\*?/g, "").replace(/[#|`\-]/g, "").replace(/<[^>]+>/g, "").trim();
  if (!clean) return;

  const utt = new SpeechSynthesisUtterance(clean);
  
  // Find a more "humanly" voice
  const voices = window.speechSynthesis.getVoices();
  const enVoices = voices.filter(v => v.lang.startsWith("en"));
  
  // Prioritization: Google Neural > Google > Samantha (Mac) > Enhanced > First English
  const preferred = enVoices.find(v => v.name.toLowerCase().includes("neural"))
                 || enVoices.find(v => v.name.toLowerCase().includes("google"))
                 || enVoices.find(v => v.name.toLowerCase().includes("samantha"))
                 || enVoices.find(v => v.name.toLowerCase().includes("enhanced"))
                 || enVoices[0];

  if (preferred) {
    utt.voice = preferred;
    console.log("Agnes voice selected:", preferred.name);
  }

  utt.rate = 1.0;  // Natural speed
  utt.pitch = 1.0; // Natural pitch
  window.speechSynthesis.speak(utt);
}

// Ensure voices are loaded (some browsers populate this async)
if (window.speechSynthesis) {
  window.speechSynthesis.onvoiceschanged = () => window.speechSynthesis.getVoices();
}

/* ── Event listeners ──────────────────────────── */
$btnSend.addEventListener("click", () => sendMessage($input.value));
$input.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage($input.value); } });
$btnMic.addEventListener("click", toggleRecording);
$btnSpeaker.addEventListener("click", toggleTTS);

document.querySelectorAll(".quick-btn").forEach(btn => {
  btn.addEventListener("click", () => sendMessage(btn.dataset.msg));
});

if ($btnAskAgnes) $btnAskAgnes.addEventListener("click", (e) => { e.preventDefault(); showChat(); });
if ($btnViewInventory) $btnViewInventory.addEventListener("click", (e) => { e.preventDefault(); loadInventory(); });
