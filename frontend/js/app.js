/**
 * Retail AI Assistant – Frontend Logic
 * Handles: chat, voice-to-text, quick actions, conversation history
 */

const API_BASE = window.location.origin;

// ── State ────────────────────────────────────────────────────────────────────
let conversationHistory = [];
let isRecording = false;
let isThinking = false;
let isTtsEnabled = localStorage.getItem("isTtsEnabled") === "true";
let audioContext = null;
let scriptProcessor = null;
let micSource = null;
let micStream = null;
let recordBuffer = [];
let silenceTimer = null;
const SILENCE_THRESHOLD = 0.015;
const SILENCE_DURATION = 2500; // 2.5 seconds silence detection

// ── Phone Call Mode State ────────────────────────────────────────────────────
let isInCallMode = false;
let callState = "IDLE"; // "IDLE", "GREETING", "LISTENING", "PROCESSING", "SPEAKING", "MUTED"
let isPhoneMuted = false;
let isPhoneSpeakerActive = true;
let phoneRecognition = null;
let phoneSilenceTimer = null;
let currentUtterance = null;
let phoneCurrentTurnTranscript = "";
let phoneHasDetectedSpeechFallback = false;

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

  // Phone Call Mode controls
  const startCallBtn = document.getElementById("startCallBtn");
  if (startCallBtn) {
    startCallBtn.addEventListener("click", startPhoneCall);
  }

  const phoneMuteBtn = document.getElementById("phoneMuteBtn");
  if (phoneMuteBtn) {
    phoneMuteBtn.addEventListener("click", togglePhoneMute);
  }

  const phoneEndBtn = document.getElementById("phoneEndBtn");
  if (phoneEndBtn) {
    phoneEndBtn.addEventListener("click", endPhoneCall);
  }

  const phoneSpeakerBtn = document.getElementById("phoneSpeakerBtn");
  if (phoneSpeakerBtn) {
    phoneSpeakerBtn.addEventListener("click", togglePhoneSpeaker);
  }

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

  const ttsToggleBtn = document.getElementById("ttsToggleBtn");
  if (ttsToggleBtn) {
    updateTtsButtonUI();
    ttsToggleBtn.addEventListener("click", () => {
      isTtsEnabled = !isTtsEnabled;
      localStorage.setItem("isTtsEnabled", isTtsEnabled);
      updateTtsButtonUI();
      if (isTtsEnabled) {
        showToast("🔊 Text-to-Speech Enabled");
        speakText("Text-to-speech enabled");
      } else {
        showToast("🔇 Text-to-Speech Disabled");
        if ('speechSynthesis' in window) {
          window.speechSynthesis.cancel();
        }
      }
    });
  }
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

  // Remove all previous active suggestion containers
  document.querySelectorAll(".active-suggestions").forEach(el => el.remove());

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
    appendAIMessage(data.reply, data.intent, data.suggestions);
    conversationHistory.push({ role: "assistant", content: data.reply });

    if (isTtsEnabled) {
      speakText(data.reply);
    }
    
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

function appendAIMessage(text, intent, suggestions = []) {
  const intentIcon = intentToIcon(intent);
  const intentLabel = intent ? intent.replace(/_/g, " ") : "";

  // Remove any previous active suggestion containers
  document.querySelectorAll(".active-suggestions").forEach(el => el.remove());

  const div = document.createElement("div");
  div.className = "message";

  let suggestionsHtml = "";
  if (suggestions && suggestions.length > 0) {
    suggestionsHtml = `
      <div class="suggestion-chips active-suggestions" style="margin-top: 8px;">
        ${suggestions.map((s, idx) => `<button class="chip dynamic-suggestion-chip" style="--chip-idx: ${idx};" data-prompt="${escapeHtml(s)}">${escapeHtml(s)}</button>`).join("")}
      </div>
    `;
  }

  div.innerHTML = `
    <div class="message-avatar ai-avatar">✦</div>
    <div>
      ${intent && intent !== "error" ? `<div class="intent-tag">${intentIcon} ${intentLabel}</div>` : ""}
      <div class="message-bubble ai-bubble">${formatAIText(text)}</div>
      ${suggestionsHtml}
      <div class="message-meta">${now()} · <span class="msg-speak-btn" title="Read message" style="cursor:pointer; opacity:0.6; transition:opacity 0.2s;">🔊 Speak</span></div>
    </div>
  `;

  // Bind click event to dynamic suggestion chips
  div.querySelectorAll(".dynamic-suggestion-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      sendMessage(chip.dataset.prompt);
    });
  });

  const speakBtn = div.querySelector(".msg-speak-btn");
  if (speakBtn) {
    speakBtn.addEventListener("click", () => {
      speakText(text);
    });
    speakBtn.addEventListener("mouseenter", () => speakBtn.style.opacity = "1");
    speakBtn.addEventListener("mouseleave", () => speakBtn.style.opacity = "0.6");
  }

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
  // 1. Escape HTML first
  let safe = escapeHtml(text);

  // 2. Strip stray markdown headers and horizontal rules
  safe = safe.replace(/^#{1,3}\s+.*/gm, "");
  safe = safe.replace(/^[-=]{3,}\s*$/gm, "");

  // 3. Bold: **text** → <strong>
  safe = safe.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");

  // 4. Italic: *text* → <em>
  safe = safe.replace(/(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)/g, "<em>$1</em>");

  // 5. Inline code: `text`
  safe = safe.replace(/`(.*?)`/g, "<code style='background:rgba(249,115,22,0.12);color:#f97316;padding:1px 6px;border-radius:4px;font-size:0.88em;font-weight:600'>$1</code>");

  // 6. Sainsbury's URL → branded clickable link
  safe = safe.replace(
    /https?:\/\/www\.sainsburys\.co\.uk\/[^\s<]*/g,
    `<a href="https://www.sainsburys.co.uk/" target="_blank" rel="noopener" style="display:inline-flex;align-items:center;gap:5px;margin-top:6px;padding:5px 12px;background:linear-gradient(135deg,#f97316,#ea580c);color:#fff;border-radius:20px;font-size:0.8rem;font-weight:600;text-decoration:none;letter-spacing:0.3px">🛒 Shop at Sainsbury's</a>`
  );

  // 7. Bullet lines: lines starting with • → styled list items
  // Group consecutive bullet lines into a <ul>
  const lines = safe.split(/\n/);
  const result = [];
  let inList = false;

  for (let line of lines) {
    const trimmed = line.trim();
    if (trimmed.startsWith("•") || trimmed.startsWith("&bull;")) {
      const content = trimmed.replace(/^[•&bull;]+\s*/, "");
      if (!inList) {
        result.push('<ul style="margin:6px 0 6px 0;padding:0;list-style:none;display:flex;flex-direction:column;gap:4px;">');
        inList = true;
      }
      result.push(`<li style="display:flex;align-items:flex-start;gap:7px;"><span style="color:#f97316;font-size:0.7rem;margin-top:4px;flex-shrink:0">●</span><span>${content}</span></li>`);
    } else {
      if (inList) {
        result.push("</ul>");
        inList = false;
      }
      if (trimmed === "") {
        result.push('<div style="height:6px"></div>');
      } else {
        result.push(`<p style="margin:0 0 6px 0;line-height:1.55">${trimmed}</p>`);
      }
    }
  }
  if (inList) result.push("</ul>");

  return result.join("");
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
let recognition = null;

function resetSilenceTimer() {
  if (silenceTimer) {
    clearTimeout(silenceTimer);
  }
  silenceTimer = setTimeout(() => {
    console.log("Auto-submitting due to 2.5 seconds of silence");
    if (isRecording) {
      stopRecording(true);
    }
  }, SILENCE_DURATION);
}

async function toggleRecording() {
  if (isRecording) {
    stopRecording(false); // Manual stop preserves text without auto-submit
  } else {
    await startRecording();
  }
}

async function startRecording() {
  hideError();
  chatInput.value = "";
  chatInput.placeholder = "Listening...";
  
  // Try native Web Speech API first
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (SpeechRecognition) {
    try {
      if (recognition) {
        recognition.abort();
      }
      
      recognition = new SpeechRecognition();
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = 'en-GB';
      
      let finalTranscript = "";
      
      recognition.onstart = () => {
        isRecording = true;
        voiceBtn.classList.add("recording");
        voiceBtn.title = "Stop recording";
        showToast("🎙 Listening... Speak now");
        resetSilenceTimer();
      };
      
      recognition.onresult = (event) => {
        resetSilenceTimer();
        let interimTranscript = "";
        
        for (let i = event.resultIndex; i < event.results.length; ++i) {
          if (event.results[i].isFinal) {
            finalTranscript += event.results[i][0].transcript;
          } else {
            interimTranscript += event.results[i][0].transcript;
          }
        }
        
        const currentText = (finalTranscript + interimTranscript).trim();
        if (currentText) {
          chatInput.value = currentText;
          autoResizeTextarea();
          sendBtn.disabled = false;
        }
      };
      
      recognition.onerror = (event) => {
        console.error("Speech recognition error:", event.error);
        if (event.error === 'not-allowed') {
          showError("Microphone access blocked. Please enable it in browser settings.");
          stopRecording(false);
        }
      };
      
      recognition.onend = () => {
        if (isRecording) {
          stopRecording(false);
        }
      };
      
      recognition.start();
      return;
    } catch (e) {
      console.warn("Web Speech API failed to start, falling back to server-side WAV recording:", e);
    }
  }
  
  // Fallback to Server-Side WAV Recording using AudioContext and Azure Speech SDK
  await startRecordingFallback();
}

async function startRecordingFallback() {
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
    resetSilenceTimer();
    
    const bufferLength = analyser.fftSize;
    const dataArray = new Uint8Array(bufferLength);
    
    function checkSilence() {
      if (!isRecording || recognition) return;
      
      analyser.getByteTimeDomainData(dataArray);
      
      let sum = 0;
      for (let i = 0; i < bufferLength; i++) {
        const floatVal = (dataArray[i] - 128) / 128;
        sum += floatVal * floatVal;
      }
      const rms = Math.sqrt(sum / bufferLength);
      
      if (rms < SILENCE_THRESHOLD) {
        // Silence detected
      } else {
        // Sound detected, reset silence timer
        resetSilenceTimer();
      }
      
      requestAnimationFrame(checkSilence);
    }
    
    requestAnimationFrame(checkSilence);
    
  } catch (err) {
    console.error(err);
    showError("Microphone access denied or error starting recording.");
  }
}

function stopRecording(shouldSubmit = false) {
  if (!isRecording) return;
  isRecording = false;
  
  if (silenceTimer) {
    clearTimeout(silenceTimer);
    silenceTimer = null;
  }
  
  // Stop Web Speech API
  if (recognition) {
    recognition.onend = null;
    recognition.stop();
    recognition = null;
    
    const text = chatInput.value.trim();
    chatInput.placeholder = "Ask about orders, refunds, deliveries, stores…";
    voiceBtn.classList.remove("recording");
    voiceBtn.title = "Voice input";
    
    if (shouldSubmit && text) {
      const wordCount = text.split(/\s+/).filter(Boolean).length;
      if (wordCount < 2) {
        showToast("Accidental input ignored (less than 2 words)");
        chatInput.value = "";
        sendBtn.disabled = true;
      } else {
        chatInput.placeholder = "Processing...";
        showToast("⚙️ Processing speech...");
        sendMessage(text);
      }
    }
    return;
  }
  
  // Stop Fallback WAV recording
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
  
  handleRecordingStopFallback(shouldSubmit);
}

async function handleRecordingStopFallback(shouldSubmit) {
  if (recordBuffer.length === 0) {
    chatInput.placeholder = "Ask about orders, refunds, deliveries, stores…";
    return;
  }

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

  chatInput.placeholder = "Processing...";
  showToast("⚙️ Transcribing…");

  try {
    const res = await fetch(`${API_BASE}/voice/transcribe`, {
      method: "POST",
      body: formData,
    });

    if (!res.ok) throw new Error(`Transcription failed (${res.status})`);

    const { transcript } = await res.json();
    const text = (transcript || "").trim();
    
    chatInput.placeholder = "Ask about orders, refunds, deliveries, stores…";
    
    if (text) {
      const wordCount = text.split(/\s+/).filter(Boolean).length;
      if (wordCount < 2) {
        showToast("Accidental input ignored (less than 2 words)");
        chatInput.value = "";
        sendBtn.disabled = true;
      } else {
        chatInput.value = text;
        autoResizeTextarea();
        sendBtn.disabled = false;
        if (shouldSubmit) {
          sendMessage(text);
        } else {
          showToast("✓ Transcribed – press Send");
        }
      }
    } else {
      showToast("No speech detected. Try again.");
    }
  } catch (err) {
    showError("Voice transcription failed: " + err.message);
    chatInput.placeholder = "Ask about orders, refunds, deliveries, stores…";
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

// ── Text-to-Speech helpers ───────────────────────────────────────────────────
function updateTtsButtonUI() {
  const ttsToggleBtn = document.getElementById("ttsToggleBtn");
  if (!ttsToggleBtn) return;
  if (isTtsEnabled) {
    ttsToggleBtn.classList.add("active");
    ttsToggleBtn.textContent = "🔊";
    ttsToggleBtn.title = "Disable Text-to-Speech";
  } else {
    ttsToggleBtn.classList.remove("active");
    ttsToggleBtn.textContent = "🔇";
    ttsToggleBtn.title = "Enable Text-to-Speech";
  }
}

function speakText(text) {
  if (!('speechSynthesis' in window)) {
    console.warn("Text-to-Speech is not supported in this browser.");
    return;
  }

  // Stop any active speech synthesis
  window.speechSynthesis.cancel();

  // Clean HTML tags
  let cleanText = text.replace(/<[^>]*>/g, "");

  // Remove internal IDs first before dashes are altered
  cleanText = cleanText
    .replace(/\bCUST-\d+\b/g, "")
    .replace(/\bSTR-\d+\b/g, "");

  // Convert star ratings (⭐⭐⭐⭐⭐ or ★★★★★) to spoken words ("5 stars")
  cleanText = cleanText.replace(/[⭐★☆]+/g, (match) => {
    const count = [...match].length;
    return ` ${count} star${count !== 1 ? "s" : ""} `;
  });

  // Remove other decorative emojis and icons (like 👋, 🛒, 📦, 🚚, 🏪, etc.)
  try {
    cleanText = cleanText.replace(/\p{Emoji_Presentation}/gu, "");
  } catch (e) {
    // Fallback regex for environments that don't support Unicode property escapes
    cleanText = cleanText.replace(/[\u{1F300}-\u{1F9FF}\u{1F600}-\u{1F64F}\u{1F680}-\u{1F6FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/gu, "");
  }

  // Replace links with friendly spoken equivalents
  cleanText = cleanText.replace(/https?:\/\/[^\s]+/g, "the Sainsbury's website");

  // Clean HTML tags, special characters, markdown symbols, and collapse spaces
  cleanText = cleanText
    .replace(/[*#`_\-–—•●✦]/g, " ")
    .replace(/&bull;/g, " ")
    .replace(/\s+/g, " ")
    .trim();

  if (!cleanText) return;

  const utterance = new SpeechSynthesisUtterance(cleanText);
  utterance.lang = "en-GB";

  // Select the highest quality human voice available
  const voices = window.speechSynthesis.getVoices();
  const enVoices = voices.filter(v => v.lang.toLowerCase().startsWith("en"));
  
  // Prioritize Edge's Online Natural voices, Google premium voices, Apple Siri/Premium, and standard defaults
  const findVoice = () => {
    // 1. Natural en-GB (e.g. Microsoft Sonia Online (Natural))
    const naturalGB = enVoices.find(v => v.lang.toLowerCase().replace('_', '-').startsWith("en-gb") && v.name.toLowerCase().includes("natural"));
    if (naturalGB) return naturalGB;
    
    // 2. Any English Natural voice (e.g. Microsoft Aria Online (Natural))
    const naturalEn = enVoices.find(v => v.name.toLowerCase().includes("natural"));
    if (naturalEn) return naturalEn;
    
    // 3. Google en-GB
    const googleGB = enVoices.find(v => v.lang.toLowerCase().replace('_', '-').startsWith("en-gb") && v.name.toLowerCase().includes("google"));
    if (googleGB) return googleGB;

    // 4. Any Google English voice
    const googleEn = enVoices.find(v => v.name.toLowerCase().includes("google"));
    if (googleEn) return googleEn;

    // 5. Apple Premium / Enhanced / Siri en-GB
    const premiumGB = enVoices.find(v => v.lang.toLowerCase().replace('_', '-').startsWith("en-gb") && 
      (v.name.toLowerCase().includes("premium") || v.name.toLowerCase().includes("enhanced") || v.name.toLowerCase().includes("siri")));
    if (premiumGB) return premiumGB;

    // 6. Any Premium / Enhanced / Siri English voice
    const premiumEn = enVoices.find(v => v.name.toLowerCase().includes("premium") || v.name.toLowerCase().includes("enhanced") || v.name.toLowerCase().includes("siri"));
    if (premiumEn) return premiumEn;

    // 7. Standard en-GB
    const standardGB = enVoices.find(v => v.lang.toLowerCase().replace('_', '-').startsWith("en-gb"));
    if (standardGB) return standardGB;

    // 8. Standard English fallback
    if (enVoices.length > 0) return enVoices[0];

    // 9. Absolute fallback
    return voices[0];
  };

  const selectedVoice = findVoice();
  if (selectedVoice) {
    utterance.voice = selectedVoice;
  }

  window.speechSynthesis.speak(utterance);
}

// ── Phone Call Mode Logic ────────────────────────────────────────────────────

function setCallState(state) {
  callState = state;
  const statusEl = document.getElementById("phoneStatus");
  const pulse1 = document.getElementById("phonePulse1");
  const pulse2 = document.getElementById("phonePulse2");
  if (!statusEl || !pulse1 || !pulse2) return;

  statusEl.className = "phone-status";
  pulse1.className = "phone-avatar-pulse";
  pulse2.className = "phone-avatar-pulse-2";

  if (state === "GREETING") {
    statusEl.textContent = "AI Greeting...";
    statusEl.classList.add("speaking");
    pulse1.classList.add("pulse-speaking");
    pulse2.classList.add("pulse-speaking");
  } else if (state === "SPEAKING") {
    statusEl.textContent = "AI Speaking...";
    statusEl.classList.add("speaking");
    pulse1.classList.add("pulse-speaking");
    pulse2.classList.add("pulse-speaking");
  } else if (state === "LISTENING") {
    statusEl.textContent = "Listening...";
    statusEl.classList.add("listening");
    pulse1.classList.add("pulse-listening");
    pulse2.classList.add("pulse-listening");
  } else if (state === "PROCESSING") {
    statusEl.textContent = "Processing...";
    statusEl.classList.add("processing");
    pulse1.classList.add("pulse-processing");
    pulse2.classList.add("pulse-processing");
  } else if (state === "MUTED") {
    statusEl.textContent = "Muted";
    statusEl.classList.add("muted");
  } else {
    statusEl.textContent = "Connecting...";
  }
}

async function startPhoneCall() {
  if (isInCallMode) return;
  isInCallMode = true;
  isPhoneMuted = false;

  // Clean up any standard voice recording
  if (isRecording) {
    stopRecording(false);
  }

  // Clear chat input, hide any banner/toast
  chatInput.value = "";
  hideError();

  // Reset mute button UI
  const muteBtn = document.getElementById("phoneMuteBtn");
  if (muteBtn) {
    muteBtn.classList.remove("muted");
    muteBtn.textContent = "🎙️";
  }

  // Show Overlay
  document.getElementById("phoneCallOverlay").classList.add("active");
  document.getElementById("phoneTranscript").textContent = "Connecting...";
  const phoneAIEl = document.getElementById("phoneAIResponse");
  if (phoneAIEl) phoneAIEl.textContent = "Connecting...";
  setCallState("GREETING");

  // Load name if customer is loaded
  const firstName = customer && customer.name ? customer.name.split(" ")[0] : "Jamie";
  const greetingText = `Hello ${firstName}, how can I help you today?`;
  if (phoneAIEl) phoneAIEl.textContent = greetingText;

  // Visual addition to chat panel
  appendAIMessage(greetingText, "general");
  conversationHistory.push({ role: "assistant", content: greetingText });

  // Speak greeting
  speakPhoneCallText(greetingText);
}

function endPhoneCall() {
  if (!isInCallMode) return;
  isInCallMode = false;

  // Cancel Speech
  window.speechSynthesis.cancel();
  currentUtterance = null;

  // Stop Listening / Recording
  if (phoneRecognition) {
    phoneRecognition.onend = null;
    phoneRecognition.onerror = null;
    phoneRecognition.stop();
    phoneRecognition = null;
  }
  stopPhoneCallRecordingFallback();

  if (phoneSilenceTimer) {
    clearTimeout(phoneSilenceTimer);
    phoneSilenceTimer = null;
  }

  // Hide Overlay
  document.getElementById("phoneCallOverlay").classList.remove("active");
  const phoneAIEl = document.getElementById("phoneAIResponse");
  if (phoneAIEl) phoneAIEl.textContent = "AI response will appear here...";
  const phoneTransEl = document.getElementById("phoneTranscript");
  if (phoneTransEl) phoneTransEl.textContent = "Waiting for speech...";
  setCallState("IDLE");
  showToast("📞 Call Ended");
}

function togglePhoneMute() {
  if (!isInCallMode) return;
  isPhoneMuted = !isPhoneMuted;
  const muteBtn = document.getElementById("phoneMuteBtn");

  if (isPhoneMuted) {
    if (muteBtn) {
      muteBtn.classList.add("muted");
      muteBtn.textContent = "🔇";
    }
    showToast("🎙️ Microphone Muted");
    setCallState("MUTED");
    
    // Stop recognition/recording
    if (phoneRecognition) {
      phoneRecognition.onend = null;
      phoneRecognition.stop();
    }
    stopPhoneCallRecordingFallback();
  } else {
    if (muteBtn) {
      muteBtn.classList.remove("muted");
      muteBtn.textContent = "🎙️";
    }
    showToast("🎙️ Microphone Active");
    
    // Restart listening
    startListeningForCall();
  }
}

function togglePhoneSpeaker() {
  if (!isInCallMode) return;
  isPhoneSpeakerActive = !isPhoneSpeakerActive;
  const speakerBtn = document.getElementById("phoneSpeakerBtn");

  if (isPhoneSpeakerActive) {
    if (speakerBtn) {
      speakerBtn.classList.add("active");
      speakerBtn.classList.remove("off");
    }
    showToast("🔊 Speaker On");
  } else {
    if (speakerBtn) {
      speakerBtn.classList.remove("active");
      speakerBtn.classList.add("off");
    }
    showToast("🔇 Speaker Off");
    window.speechSynthesis.cancel();
    
    // If AI was speaking, transition directly to listening now
    if (callState === "SPEAKING" || callState === "GREETING") {
      startListeningForCall();
    }
  }
}

function speakPhoneCallText(text) {
  if (!('speechSynthesis' in window)) {
    startListeningForCall();
    return;
  }

  window.speechSynthesis.cancel();

  // Clean HTML/emojis/ids as in standard speakText
  let cleanText = text.replace(/<[^>]*>/g, "")
    .replace(/\bCUST-\d+\b/g, "")
    .replace(/\bSTR-\d+\b/g, "")
    .replace(/[⭐★☆]+/g, (match) => {
      const count = [...match].length;
      return ` ${count} star${count !== 1 ? "s" : ""} `;
    });
  
  try {
    cleanText = cleanText.replace(/\p{Emoji_Presentation}/gu, "");
  } catch (e) {
    cleanText = cleanText.replace(/[\u{1F300}-\u{1F9FF}\u{1F600}-\u{1F64F}\u{1F680}-\u{1F6FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/gu, "");
  }
  
  cleanText = cleanText.replace(/https?:\/\/[^\s]+/g, "the Sainsbury's website")
    .replace(/[*#`_\-–—•●✦]/g, " ")
    .replace(/&bull;/g, " ")
    .replace(/\s+/g, " ")
    .trim();

  if (!cleanText || !isPhoneSpeakerActive) {
    startListeningForCall();
    return;
  }

  const utterance = new SpeechSynthesisUtterance(cleanText);
  utterance.lang = "en-GB";

  // Select voice using the same standard fallback logic
  const voices = window.speechSynthesis.getVoices();
  const enVoices = voices.filter(v => v.lang.toLowerCase().startsWith("en"));
  const findVoice = () => {
    const naturalGB = enVoices.find(v => v.lang.toLowerCase().replace('_', '-').startsWith("en-gb") && v.name.toLowerCase().includes("natural"));
    if (naturalGB) return naturalGB;
    const naturalEn = enVoices.find(v => v.name.toLowerCase().includes("natural"));
    if (naturalEn) return naturalEn;
    const googleGB = enVoices.find(v => v.lang.toLowerCase().replace('_', '-').startsWith("en-gb") && v.name.toLowerCase().includes("google"));
    if (googleGB) return googleGB;
    const standardGB = enVoices.find(v => v.lang.toLowerCase().replace('_', '-').startsWith("en-gb"));
    if (standardGB) return standardGB;
    return enVoices[0] || voices[0];
  };

  const selectedVoice = findVoice();
  if (selectedVoice) {
    utterance.voice = selectedVoice;
  }

  utterance.onstart = () => {
    if (isInCallMode && isPhoneSpeakerActive) {
      setCallState("SPEAKING");
    }
  };

  utterance.onend = () => {
    currentUtterance = null;
    if (isInCallMode) {
      startListeningForCall();
    }
  };

  utterance.onerror = (e) => {
    console.error("SpeechSynthesisUtterance error:", e);
    currentUtterance = null;
    if (isInCallMode) {
      startListeningForCall();
    }
  };

  currentUtterance = utterance;
  window.speechSynthesis.speak(utterance);
}

function resetPhoneSilenceTimer() {
  if (phoneSilenceTimer) {
    clearTimeout(phoneSilenceTimer);
  }
  phoneSilenceTimer = setTimeout(() => {
    if (isInCallMode && callState === "LISTENING" && !isPhoneMuted) {
      submitPhoneCallTurn();
    }
  }, SILENCE_DURATION);
}

function startListeningForCall() {
  if (!isInCallMode || isPhoneMuted) return;

  // Reset the current turn transcript, but do NOT clear the visible DOM text
  // so the conversation history remains on the screen until the user starts speaking again.
  phoneCurrentTurnTranscript = "";
  
  setCallState("LISTENING");

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (SpeechRecognition) {
    try {
      if (phoneRecognition) {
        phoneRecognition.abort();
      }

      phoneRecognition = new SpeechRecognition();
      phoneRecognition.continuous = true;
      phoneRecognition.interimResults = true;
      phoneRecognition.lang = 'en-GB';

      let finalTranscript = "";

      phoneRecognition.onstart = () => {
        resetPhoneSilenceTimer();
      };

      phoneRecognition.onresult = (event) => {
        let interimTranscript = "";
        for (let i = event.resultIndex; i < event.results.length; ++i) {
          if (event.results[i].isFinal) {
            finalTranscript += event.results[i][0].transcript;
          } else {
            interimTranscript += event.results[i][0].transcript;
          }
        }

        const currentText = (finalTranscript + interimTranscript).trim();
        if (currentText) {
          phoneCurrentTurnTranscript = currentText;
          if (transcriptPreview) {
            transcriptPreview.textContent = currentText;
          }

          // Barge-in (Interruption Support)
          if (callState === "SPEAKING" || callState === "GREETING") {
            const wordCount = currentText.split(/\s+/).filter(Boolean).length;
            if (wordCount >= 1) {
              console.log("[CallMode] User interrupted AI speech. Stopping TTS...");
              window.speechSynthesis.cancel();
              currentUtterance = null;
              setCallState("LISTENING");
              
              const phoneAIEl = document.getElementById("phoneAIResponse");
              if (phoneAIEl) phoneAIEl.textContent = "Interrupted...";
              
              finalTranscript = "";
              if (transcriptPreview) {
                transcriptPreview.textContent = currentText;
              }
            }
          }
          
          resetPhoneSilenceTimer();
        }
      };

      phoneRecognition.onerror = (event) => {
        console.error("Call SpeechRecognition error:", event.error);
        if (event.error === 'not-allowed') {
          showError("Microphone access blocked. Please enable it.");
          togglePhoneMute(); // Mute automatically if blocked
        }
      };

      phoneRecognition.onend = () => {
        // Continuous listening: restart if still active and not muted
        if (isInCallMode && callState === "LISTENING" && !isPhoneMuted) {
          try {
            phoneRecognition.start();
          } catch (e) {
            // Already started or busy
          }
        }
      };

      phoneRecognition.start();
      return;
    } catch (e) {
      console.warn("Call native speech recognition failed to start, falling back to WAV:", e);
    }
  }

  // Fallback to Server-Side continuous WAV recording
  startPhoneCallRecordingFallback();
}

// Override turn submit for fallback method when silence fires
// If we are in fallback mode and not native recognition
function submitPhoneCallTurn() {
  if (phoneRecognition) {
    submitPhoneCallTurnNative();
  } else {
    submitPhoneCallTurnFallback();
  }
}

async function submitPhoneCallTurnNative() {
  if (!isInCallMode || isPhoneMuted) return;

  const text = phoneCurrentTurnTranscript.trim();

  if (!text) {
    resetPhoneSilenceTimer();
    return;
  }

  const wordCount = text.split(/\s+/).filter(Boolean).length;
  if (wordCount < 2) {
    // Noise or short greeting, ignore and do not submit. Clear text.
    phoneCurrentTurnTranscript = "";
    resetPhoneSilenceTimer();
    return;
  }

  const transcriptPreview = document.getElementById("phoneTranscript");

  if (phoneRecognition) {
    phoneRecognition.onend = null;
    phoneRecognition.stop();
  }

  if (phoneSilenceTimer) {
    clearTimeout(phoneSilenceTimer);
    phoneSilenceTimer = null;
  }

  setCallState("PROCESSING");
  transcriptPreview.textContent = "Processing...";

  appendUserMessage(text);
  conversationHistory.push({ role: "user", content: text });

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
      throw new Error(`Server error ${response.status}`);
    }

    const data = await response.json();
    appendAIMessage(data.reply, data.intent, data.suggestions);
    conversationHistory.push({ role: "assistant", content: data.reply });

    fetchCustomerData();

    const phoneAIEl = document.getElementById("phoneAIResponse");
    if (phoneAIEl) phoneAIEl.textContent = data.reply;

    if (isPhoneSpeakerActive) {
      speakPhoneCallText(data.reply);
    } else {
      startListeningForCall();
    }
  } catch (err) {
    console.error("Phone call API request failed:", err);
    const errorReply = "I'm having trouble connecting to my service. Could you repeat that?";
    appendAIMessage(errorReply, "error");
    
    const phoneAIEl = document.getElementById("phoneAIResponse");
    if (phoneAIEl) phoneAIEl.textContent = errorReply;

    if (isPhoneSpeakerActive) {
      speakPhoneCallText(errorReply);
    } else {
      startListeningForCall();
    }
  }
}

// ── Fallback continuous recording for Phone Call Mode ────────────────────────
let phoneAudioContext = null;
let phoneMicSource = null;
let phoneScriptProcessor = null;
let phoneMicStream = null;
let phoneRecordBuffer = [];
let silenceCheckInterval = null;

async function startPhoneCallRecordingFallback() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    phoneMicStream = stream;

    phoneAudioContext = new (window.AudioContext || window.webkitAudioContext)();
    phoneMicSource = phoneAudioContext.createMediaStreamSource(stream);

    const analyser = phoneAudioContext.createAnalyser();
    analyser.fftSize = 512;
    phoneMicSource.connect(analyser);

    phoneScriptProcessor = phoneAudioContext.createScriptProcessor(4096, 1, 1);
    phoneRecordBuffer = [];
    phoneHasDetectedSpeechFallback = false;

    phoneScriptProcessor.onaudioprocess = (e) => {
      if (!isInCallMode || isPhoneMuted) return;
      const channelData = e.inputBuffer.getChannelData(0);
      phoneRecordBuffer.push(new Float32Array(channelData));
    };

    phoneMicSource.connect(phoneScriptProcessor);
    phoneScriptProcessor.connect(phoneAudioContext.destination);

    resetPhoneSilenceTimer();

    const bufferLength = analyser.fftSize;
    const dataArray = new Uint8Array(bufferLength);
    let consecutiveSpeechFrames = 0;

    silenceCheckInterval = requestAnimationFrame(function checkSilence() {
      if (!isInCallMode || isPhoneMuted || phoneRecognition) return;

      analyser.getByteTimeDomainData(dataArray);
      let sum = 0;
      for (let i = 0; i < bufferLength; i++) {
        const floatVal = (dataArray[i] - 128) / 128;
        sum += floatVal * floatVal;
      }
      const rms = Math.sqrt(sum / bufferLength);

      if (rms >= SILENCE_THRESHOLD) {
        // Sound detected
        if (callState === "LISTENING") {
          phoneHasDetectedSpeechFallback = true;
          resetPhoneSilenceTimer();
        } else if (callState === "SPEAKING" || callState === "GREETING") {
          // Barge-in check: user speaks over speaker
          consecutiveSpeechFrames++;
          if (consecutiveSpeechFrames >= 3) {
            console.log("[CallMode Fallback] User speaking detected. stopping speech...");
            window.speechSynthesis.cancel();
            currentUtterance = null;
            phoneRecordBuffer = []; // Clear buffer to start fresh recording
            setCallState("LISTENING");
            consecutiveSpeechFrames = 0;
            resetPhoneSilenceTimer();
          }
        }
      } else {
        consecutiveSpeechFrames = 0;
      }

      silenceCheckInterval = requestAnimationFrame(checkSilence);
    });

  } catch (err) {
    console.error("Fallback recording failed:", err);
    showError("Could not start microphone recording fallback.");
  }
}

function stopPhoneCallRecordingFallback() {
  if (silenceCheckInterval) {
    cancelAnimationFrame(silenceCheckInterval);
    silenceCheckInterval = null;
  }
  if (phoneScriptProcessor) {
    phoneScriptProcessor.disconnect();
    phoneScriptProcessor = null;
  }
  if (phoneMicSource) {
    phoneMicSource.disconnect();
    phoneMicSource = null;
  }
  if (phoneAudioContext) {
    phoneAudioContext.close();
    phoneAudioContext = null;
  }
  if (phoneMicStream) {
    phoneMicStream.getTracks().forEach(t => t.stop());
    phoneMicStream = null;
  }
}

async function submitPhoneCallTurnFallback() {
  if (!phoneHasDetectedSpeechFallback || phoneRecordBuffer.length === 0) {
    // No speech detected during fallback, reset buffers/timer and keep recording
    phoneRecordBuffer = [];
    phoneHasDetectedSpeechFallback = false;
    resetPhoneSilenceTimer();
    return;
  }

  // Merge float buffers
  let totalLength = 0;
  for (let i = 0; i < phoneRecordBuffer.length; i++) {
    totalLength += phoneRecordBuffer[i].length;
  }
  const mergedSamples = mergeBuffers(phoneRecordBuffer, totalLength);

  const sampleRate = phoneAudioContext ? phoneAudioContext.sampleRate : 44100;
  const targetSampleRate = 16000;
  const downsampledSamples = downsampleBuffer(mergedSamples, sampleRate, targetSampleRate);

  const blob = encodeWAV(downsampledSamples, targetSampleRate);
  const formData = new FormData();
  formData.append("audio", blob, "voice.wav");

  const transcriptPreview = document.getElementById("phoneTranscript");
  // Don't overwrite the previous text yet, wait until we verify if transcript is non-empty
  setCallState("PROCESSING");

  try {
    const res = await fetch(`${API_BASE}/voice/transcribe`, {
      method: "POST",
      body: formData,
    });

    if (!res.ok) throw new Error(`Transcription failed (${res.status})`);

    const { transcript } = await res.json();
    const text = (transcript || "").trim();

    if (text) {
      const wordCount = text.split(/\s+/).filter(Boolean).length;
      if (wordCount < 2) {
        // Ignore noise, continue listening
        startListeningForCall();
      } else {
        if (transcriptPreview) {
          transcriptPreview.textContent = text;
        }
        appendUserMessage(text);
        conversationHistory.push({ role: "user", content: text });

        const response = await fetch(`${API_BASE}/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message: text,
            conversation_history: conversationHistory.slice(-20),
          }),
        });

        if (!response.ok) throw new Error("Chat call failed");
        const data = await response.json();
        appendAIMessage(data.reply, data.intent, data.suggestions);
        conversationHistory.push({ role: "assistant", content: data.reply });
        fetchCustomerData();

        const phoneAIEl = document.getElementById("phoneAIResponse");
        if (phoneAIEl) phoneAIEl.textContent = data.reply;

        if (isPhoneSpeakerActive) {
          speakPhoneCallText(data.reply);
        } else {
          startListeningForCall();
        }
      }
    } else {
      startListeningForCall();
    }
  } catch (err) {
    console.error("Fallback turn submission failed:", err);
    const phoneAIEl = document.getElementById("phoneAIResponse");
    if (phoneAIEl) phoneAIEl.textContent = "I encountered an error. Please try again.";
    startListeningForCall();
  }
}

// Preload voices as early as possible so they are immediately available on speech request
if ('speechSynthesis' in window) {
  window.speechSynthesis.getVoices();
  if (window.speechSynthesis.onvoiceschanged !== undefined) {
    window.speechSynthesis.onvoiceschanged = () => {
      // Fetch voices again to trigger loading in the browser
      window.speechSynthesis.getVoices();
    };
  }
}
