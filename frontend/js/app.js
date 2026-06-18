/**
 * Retail AI Assistant – Frontend Logic
 * Handles: chat, voice-to-text, quick actions, conversation history
 */

const API_BASE = window.location.origin;

// ── State ────────────────────────────────────────────────────────────────────
let conversationHistory = [];
let isRecording = false;
let isThinking = false;
let audioContext = null;
let scriptProcessor = null;
let micSource = null;
let micStream = null;
let recordBuffer = [];
let silenceTimer = null;
const SILENCE_THRESHOLD = 0.015;
const SILENCE_DURATION = 5000;

// ── Customer data (mirrored for sidebar UX, loaded dynamically) ─────────────
let customer = null;
let orders = [];

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
  fetchCustomerData();
  bindEvents();
  chatInput.focus();
});

// ── Sidebar ──────────────────────────────────────────────────────────────────
function renderSidebar() {
  if (!customer) return;

  const initials = customer.name
    ? customer.name.split(" ").map(n => n[0]).join("").toUpperCase()
    : "";

  document.getElementById("customerName").textContent = customer.name;
  document.getElementById("customerId").textContent = customer.id;
  document.getElementById("customerInitials").textContent = initials;
  
  const loyaltyBadgeText = `⭐ ${customer.loyalty_tier} · ${customer.loyalty_points.toLocaleString()} pts`;
  document.getElementById("loyaltyBadge").textContent = loyaltyBadgeText;

  if (customer.default_address) {
    const addrText = `${customer.default_address.line1}, ${customer.default_address.city}`;
    document.getElementById("customerAddressText").textContent = addrText;
  }

  const pillsEl = document.getElementById("orderPills");
  pillsEl.innerHTML = "";
  orders.forEach(order => {
    const pill = document.createElement("div");
    pill.className = "order-pill";
    pill.innerHTML = `
      <span class="order-pill-id">${order.order_id}</span>
      <span class="order-pill-status status-${order.status}">
        ${STATUS_LABELS[order.status] || order.status}
      </span>
    `;
    pill.addEventListener("click", () => {
      sendMessage(`What is the status of order ${order.order_id}?`);
    });
    pillsEl.appendChild(pill);
  });
}

// ── Fetch dynamic customer data ──────────────────────────────────────────────
async function fetchCustomerData() {
  try {
    const res = await fetch(`${API_BASE}/customer`);
    if (!res.ok) throw new Error(`Failed to fetch customer data: ${res.status}`);
    const data = await res.json();
    customer = data.customer;
    orders = data.orders || [];
    
    // Update Welcome Card text with customer's first name
    const welcomeHeader = document.querySelector("#welcomeCard h2");
    if (welcomeHeader && customer.name) {
      const firstName = customer.name.split(" ")[0];
      welcomeHeader.textContent = `Hello, ${firstName} 👋`;
    }
    
    renderSidebar();
  } catch (err) {
    console.error("Error fetching customer data:", err);
  }
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
    
    // Refresh customer and orders in UI in case the agent executed tool updates
    await fetchCustomerData();

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
  const initials = customer && customer.name
    ? customer.name.split(" ").map(n => n[0]).join("").toUpperCase()
    : "JT";
  const div = document.createElement("div");
  div.className = "message user-message";
  div.innerHTML = `
    <div class="message-avatar user-avatar">${initials}</div>
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
    micStream = stream;
    
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
    
    micSource = audioContext.createMediaStreamSource(stream);
    
    // Silence detection analyser
    const analyser = audioContext.createAnalyser();
    analyser.fftSize = 512;
    micSource.connect(analyser);
    
    // ScriptProcessor to capture raw PCM
    scriptProcessor = audioContext.createScriptProcessor(4096, 1, 1);
    recordBuffer = [];
    
    scriptProcessor.onaudioprocess = (e) => {
      if (!isRecording) return;
      const channelData = e.inputBuffer.getChannelData(0);
      recordBuffer.push(new Float32Array(channelData));
    };
    
    micSource.connect(scriptProcessor);
    scriptProcessor.connect(audioContext.destination);
    
    isRecording = true;
    voiceBtn.classList.add("recording");
    voiceBtn.title = "Stop recording";
    showToast("🎙 Recording… speak now");
    
    const bufferLength = analyser.fftSize;
    const dataArray = new Uint8Array(bufferLength);
    
    function checkSilence() {
      if (!isRecording) return;
      
      analyser.getByteTimeDomainData(dataArray);
      
      let sum = 0;
      for (let i = 0; i < bufferLength; i++) {
        const floatVal = (dataArray[i] - 128) / 128;
        sum += floatVal * floatVal;
      }
      const rms = Math.sqrt(sum / bufferLength);
      
      if (rms < SILENCE_THRESHOLD) {
        if (!silenceTimer) {
          silenceTimer = setTimeout(() => {
            console.log("Auto-stopping recording due to 5 seconds of silence");
            stopRecording();
            showToast("✓ Auto-stopped (silence detected)");
          }, SILENCE_DURATION);
        }
      } else {
        if (silenceTimer) {
          clearTimeout(silenceTimer);
          silenceTimer = null;
        }
      }
      
      requestAnimationFrame(checkSilence);
    }
    
    requestAnimationFrame(checkSilence);
    
  } catch (err) {
    console.error(err);
    showError("Microphone access denied or error starting recording.");
  }
}

function stopRecording() {
  if (!isRecording) return;
  isRecording = false;
  
  if (silenceTimer) {
    clearTimeout(silenceTimer);
    silenceTimer = null;
  }
  
  if (scriptProcessor) {
    scriptProcessor.disconnect();
    scriptProcessor = null;
  }
  
  if (micSource) {
    micSource.disconnect();
    micSource = null;
  }
  
  if (audioContext) {
    audioContext.close();
  }
  
  if (micStream) {
    micStream.getTracks().forEach(t => t.stop());
    micStream = null;
  }
  
  voiceBtn.classList.remove("recording");
  voiceBtn.title = "Voice input";
  
  handleRecordingStop();
}

async function handleRecordingStop() {
  if (recordBuffer.length === 0) return;

  // Merge float buffers
  let totalLength = 0;
  for (let i = 0; i < recordBuffer.length; i++) {
    totalLength += recordBuffer[i].length;
  }
  const mergedSamples = mergeBuffers(recordBuffer, totalLength);

  // Downsample to 16kHz
  const sampleRate = audioContext.sampleRate;
  const targetSampleRate = 16000;
  const downsampledSamples = downsampleBuffer(mergedSamples, sampleRate, targetSampleRate);

  // Encode to mono 16-bit PCM WAV
  const blob = encodeWAV(downsampledSamples, targetSampleRate);
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

// ── WAV helper functions ──────────────────────────────────────────────────────
function mergeBuffers(channelBuffer, recordingLength) {
  const result = new Float32Array(recordingLength);
  let offset = 0;
  for (let i = 0; i < channelBuffer.length; i++) {
    result.set(channelBuffer[i], offset);
    offset += channelBuffer[i].length;
  }
  return result;
}

function downsampleBuffer(buffer, sampleRate, outSampleRate) {
  if (outSampleRate === sampleRate) {
    return buffer;
  }
  const sampleRateRatio = sampleRate / outSampleRate;
  const newLength = Math.round(buffer.length / sampleRateRatio);
  const result = new Float32Array(newLength);
  let offsetResult = 0;
  let offsetBuffer = 0;
  while (offsetResult < result.length) {
    const nextOffsetBuffer = Math.round((offsetResult + 1) * sampleRateRatio);
    let accum = 0, count = 0;
    for (let i = offsetBuffer; i < nextOffsetBuffer && i < buffer.length; i++) {
      accum += buffer[i];
      count++;
    }
    result[offsetResult] = accum / count;
    offsetResult++;
    offsetBuffer = nextOffsetBuffer;
  }
  return result;
}

function encodeWAV(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);

  writeString(view, 0, 'RIFF');
  view.setUint32(4, 36 + samples.length * 2, true);
  writeString(view, 8, 'WAVE');
  writeString(view, 12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(view, 36, 'data');
  view.setUint32(40, samples.length * 2, true);

  floatTo16BitPCM(view, 44, samples);

  return new Blob([view.buffer], { type: 'audio/wav' });
}

function floatTo16BitPCM(output, offset, input) {
  for (let i = 0; i < input.length; i++, offset += 2) {
    let s = Math.max(-1, Math.min(1, input[i]));
    output.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
  }
}

function writeString(view, offset, string) {
  for (let i = 0; i < string.length; i++) {
    view.setUint8(offset + i, string.charCodeAt(i));
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
