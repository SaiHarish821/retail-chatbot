/**
 * Retail AI Assistant – Frontend Logic
 * Handles: chat, voice-to-text, quick actions, conversation history
 */

const API_BASE = window.location.origin;

// ── State ────────────────────────────────────────────────────────────────────
let conversationHistory = [];
let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;
let isThinking = false;

// ── Customer data (mirrored for sidebar UX, not used for logic) ─────────────
const CUSTOMER = {
  name: "Jamie Thornton",
  id: "CUST-00421",
  initials: "JT",
  loyalty: "Gold · 3,240 pts",
};

const ORDERS = [
  { id: "ORD-98741", status: "delivered" },
  { id: "ORD-99102", status: "in_transit" },
  { id: "ORD-97830", status: "refund_processing" },
  { id: "ORD-96210", status: "refund_completed" },
];

const STATUS_LABELS = {
  delivered: "Delivered",
  in_transit: "In Transit",
  refund_processing: "Refund Pending",
  refund_completed: "Refunded",
};

// ── DOM refs ─────────────────────────────────────────────────────────────────
const messagesEl    = document.getElementById("messages");
const chatInput     = document.getElementById("chatInput");
const sendBtn       = document.getElementById("sendBtn");
const voiceBtn      = document.getElementById("voiceBtn");
const errorBanner   = document.getElementById("errorBanner");
const toastEl       = document.getElementById("toast");

// ── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  renderSidebar();
  bindEvents();
  chatInput.focus();
});

// ── Sidebar ──────────────────────────────────────────────────────────────────
function renderSidebar() {
  document.getElementById("customerName").textContent = CUSTOMER.name;
  document.getElementById("customerId").textContent = CUSTOMER.id;
  document.getElementById("customerInitials").textContent = CUSTOMER.initials;
  document.getElementById("loyaltyBadge").textContent = "⭐ " + CUSTOMER.loyalty;

  const pillsEl = document.getElementById("orderPills");
  ORDERS.forEach(order => {
    const pill = document.createElement("div");
    pill.className = "order-pill";
    pill.innerHTML = `
      <span class="order-pill-id">${order.id}</span>
      <span class="order-pill-status status-${order.status}">
        ${STATUS_LABELS[order.status]}
      </span>
    `;
    pill.addEventListener("click", () => {
      sendMessage(`What is the status of order ${order.id}?`);
    });
    pillsEl.appendChild(pill);
  });
}

// ── Events ───────────────────────────────────────────────────────────────────
function bindEvents() {
  sendBtn.addEventListener("click", () => sendFromInput());

  chatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendFromInput();
    }
  });

  chatInput.addEventListener("input", () => {
    autoResizeTextarea();
    sendBtn.disabled = chatInput.value.trim() === "";
  });

  voiceBtn.addEventListener("click", toggleRecording);

  // Quick suggestion chips
  document.querySelectorAll(".chip").forEach(chip => {
    chip.addEventListener("click", () => {
      sendMessage(chip.dataset.prompt);
    });
  });

  // Nav quick actions
  document.querySelectorAll(".nav-btn[data-prompt]").forEach(btn => {
    btn.addEventListener("click", () => {
      sendMessage(btn.dataset.prompt);
    });
  });
}

function autoResizeTextarea() {
  chatInput.style.height = "22px";
  chatInput.style.height = Math.min(chatInput.scrollHeight, 100) + "px";
}

// ── Chat ─────────────────────────────────────────────────────────────────────
function sendFromInput() {
  const text = chatInput.value.trim();
  if (!text || isThinking) return;
  chatInput.value = "";
  chatInput.style.height = "22px";
  sendBtn.disabled = true;
  sendMessage(text);
}

async function sendMessage(text) {
  if (!text || isThinking) return;
  hideError();

  // Remove welcome card after first message
  const welcome = document.getElementById("welcomeCard");
  if (welcome) welcome.remove();

  appendUserMessage(text);
  conversationHistory.push({ role: "user", content: text });

  const typingId = showTyping();
  isThinking = true;

  try {
    const response = await fetch(`${API_BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
        conversation_history: conversationHistory.slice(-20),
      }),
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || `Server error ${response.status}`);
    }

    const data = await response.json();
    removeTyping(typingId);
    appendAIMessage(data.reply, data.intent);
    conversationHistory.push({ role: "assistant", content: data.reply });

  } catch (err) {
    removeTyping(typingId);
    showError(err.message);
    appendAIMessage(
      "I'm having trouble connecting right now. Please check the backend is running and your Azure credentials are configured.",
      "error"
    );
  } finally {
    isThinking = false;
    chatInput.focus();
  }
}

// ── Render messages ──────────────────────────────────────────────────────────
function appendUserMessage(text) {
  const div = document.createElement("div");
  div.className = "message user-message";
  div.innerHTML = `
    <div class="message-avatar user-avatar">JT</div>
    <div>
      <div class="message-bubble user-bubble">${escapeHtml(text)}</div>
      <div class="message-meta">${now()}</div>
    </div>
  `;
  messagesEl.appendChild(div);
  scrollToBottom();
}

function appendAIMessage(text, intent) {
  const intentIcon = intentToIcon(intent);
  const intentLabel = intent ? intent.replace(/_/g, " ") : "";

  const div = document.createElement("div");
  div.className = "message";
  div.innerHTML = `
    <div class="message-avatar ai-avatar">✦</div>
    <div>
      ${intent && intent !== "error" ? `<div class="intent-tag">${intentIcon} ${intentLabel}</div>` : ""}
      <div class="message-bubble ai-bubble">${formatAIText(text)}</div>
      <div class="message-meta">${now()}</div>
    </div>
  `;
  messagesEl.appendChild(div);
  scrollToBottom();
}

function showTyping() {
  const id = "typing-" + Date.now();
  const div = document.createElement("div");
  div.className = "message typing-indicator";
  div.id = id;
  div.innerHTML = `
    <div class="message-avatar ai-avatar">✦</div>
    <div class="typing-dots">
      <span></span><span></span><span></span>
    </div>
  `;
  messagesEl.appendChild(div);
  scrollToBottom();
  return id;
}

function removeTyping(id) {
  const el = document.getElementById(id);
  if (el) el.remove();
}

function formatAIText(text) {
  return escapeHtml(text)
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.*?)\*/g, "<em>$1</em>")
    .replace(/`(.*?)`/g, "<code style='background:var(--orange-50);color:var(--orange-700);padding:1px 5px;border-radius:4px;font-size:0.9em'>$1</code>")
    .replace(/\n/g, "<br>");
}

function escapeHtml(text) {
  const map = { "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" };
  return String(text).replace(/[&<>"']/g, m => map[m]);
}

function intentToIcon(intent) {
  const icons = {
    order: "📦",
    refund: "↩️",
    delivery: "🚚",
    store: "🏪",
    error: "⚠️",
  };
  return icons[intent] || "💬";
}

function now() {
  return new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

function scrollToBottom() {
  requestAnimationFrame(() => {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  });
}

// ── Voice ─────────────────────────────────────────────────────────────────────
async function toggleRecording() {
  if (isRecording) {
    stopRecording();
  } else {
    await startRecording();
  }
}

async function startRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    audioChunks = [];

    mediaRecorder = new MediaRecorder(stream, { mimeType: "audio/webm" });
    mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) audioChunks.push(e.data);
    };
    mediaRecorder.onstop = handleRecordingStop;
    mediaRecorder.start(100);

    isRecording = true;
    voiceBtn.classList.add("recording");
    voiceBtn.title = "Stop recording";
    showToast("🎙 Recording… tap again to stop");

  } catch (err) {
    showError("Microphone access denied. Enable it in browser settings.");
  }
}

function stopRecording() {
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    mediaRecorder.stop();
    mediaRecorder.stream.getTracks().forEach(t => t.stop());
  }
  isRecording = false;
  voiceBtn.classList.remove("recording");
  voiceBtn.title = "Voice input";
}

async function handleRecordingStop() {
  if (audioChunks.length === 0) return;

  const blob = new Blob(audioChunks, { type: "audio/wav" });
  const formData = new FormData();
  formData.append("audio", blob, "voice.wav");

  showToast("⚙️ Transcribing…");

  try {
    const res = await fetch(`${API_BASE}/voice/transcribe`, {
      method: "POST",
      body: formData,
    });

    if (!res.ok) throw new Error(`Transcription failed (${res.status})`);

    const { transcript } = await res.json();
    if (transcript) {
      chatInput.value = transcript;
      autoResizeTextarea();
      sendBtn.disabled = false;
      chatInput.focus();
      showToast("✓ Transcribed – press Send");
    } else {
      showToast("No speech detected. Try again.");
    }
  } catch (err) {
    showError("Voice transcription failed: " + err.message);
  }
}

// ── UI helpers ────────────────────────────────────────────────────────────────
function showToast(msg) {
  toastEl.textContent = msg;
  toastEl.classList.add("show");
  setTimeout(() => toastEl.classList.remove("show"), 3000);
}

function showError(msg) {
  errorBanner.textContent = "⚠️ " + msg;
  errorBanner.classList.add("visible");
  setTimeout(() => errorBanner.classList.remove("visible"), 8000);
}

function hideError() {
  errorBanner.classList.remove("visible");
}
