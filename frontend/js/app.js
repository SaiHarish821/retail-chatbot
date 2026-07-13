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
let voiceSocket = null;
let pcmPlayer = null;
let voiceMode = "server_audio"; // "server_audio", "native_ws", "native_http"
let isResponseFinished = false;

// Browser-Native Voice Fallback variables
let phoneRecognition = null;
let phoneSilenceTimer = null;
let currentUtterance = null;
let currentAudioElement = null;
let phoneCurrentTurnTranscript = "";
let phoneAccumulatedTurnTranscript = "";
const PHONE_SILENCE_DURATION = 1000;


// Voice Filler System & Playback Queue Globals
const FILLER_GRACE_MS = 5000;   // wait 5s before first filler (skip if reply is faster)
const FILLER_GAP_MIN_MS = 3500; // min pause between consecutive fillers
const FILLER_GAP_MAX_MS = 6000; // max pause between consecutive fillers
let fillerTrees = [];          // escalation sequences; each is an array of base64 clips
let fillerThinking = [];       // short "hmm"-style interjection clips
let currentTree = null;        // the tree chosen for the current wait
let treeStep = 0;              // position within the current tree
let awaitingResponse = false;  // user finished; we're waiting for agent audio
let fillerActive = false;      // a filler clip is currently playing
let fillerSource = null;       // current AudioBufferSourceNode for the filler
let fillerTimer = null;
let responseDone = false;      // agent signalled its audio response is complete
let playbackQueue = [];        // holds incoming base64 audio chunks while filler is active
let userTranscriptText = "";   // holds partial live user transcript



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
function initApp() {
  fetchCustomerData();
  bindEvents();
  chatInput.focus();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initApp);
} else {
  initApp();
}

// ── Sidebar ──────────────────────────────────────────────────────────────────
function renderSidebar() {
  if (!customer) return;

  const initials = customer.name
    ? customer.name.split(" ").map(n => n[0]).join("").toUpperCase()
    : "";

  document.getElementById("customerName").textContent = customer.name;
  document.getElementById("customerId").textContent = customer.id;
  document.getElementById("customerInitials").textContent = initials;
  
  const badgeTextEl = document.getElementById("loyaltyBadgeText");
  if (badgeTextEl) {
    badgeTextEl.textContent = `${customer.loyalty_tier} · ${customer.loyalty_points.toLocaleString()} pts`;
  } else {
    document.getElementById("loyaltyBadge").textContent = `⭐ ${customer.loyalty_tier} · ${customer.loyalty_points.toLocaleString()} pts`;
  }

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

  // Auto-switch to chat tab if the user triggers a query from another tab
  if (typeof switchChatTab === "function") {
    switchChatTab("chat");
  }

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
        stream: true
      }),
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || `Server error ${response.status}`);
    }

    removeTyping(typingId);

    const bubbleEl = createStreamingAIBubble();
    let replyText = "";
    let finalIntent = "general";
    let finalSuggestions = [];
    
    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n\n");
      buffer = lines.pop();

      for (const line of lines) {
        if (line.startsWith("data: ")) {
          try {
            const data = JSON.parse(line.slice(6));
            if (data.type === "token") {
              replyText += data.content;
              updateStreamingAIBubbleText(bubbleEl, replyText);
            } else if (data.type === "done") {
              finalIntent = data.intent;
              finalSuggestions = data.suggestions || [];
              if (data.reply) {
                replyText = data.reply;
              }
            } else if (data.type === "error") {
              throw new Error(data.content);
            }
          } catch (e) {
            console.error("Error parsing stream chunk:", e);
          }
        }
      }
    }

    finalizeStreamingAIBubble(bubbleEl, replyText, finalIntent, finalSuggestions);
    conversationHistory.push({ role: "assistant", content: replyText });

    if (isTtsEnabled) {
      speakText(replyText);
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

function createStreamingAIBubble() {
  document.querySelectorAll(".active-suggestions").forEach(el => el.remove());

  const div = document.createElement("div");
  div.className = "message";
  div.innerHTML = `
    <div class="message-avatar ai-avatar">✦</div>
    <div>
      <div class="intent-tag ai-streaming-intent-tag" style="display: none; margin-bottom: 4px;"></div>
      <div class="message-bubble ai-bubble ai-streaming-text-bubble">...</div>
      <div class="message-meta ai-streaming-meta" style="display: none; margin-top: 4px;"></div>
    </div>
  `;
  messagesEl.appendChild(div);
  scrollToBottom();
  return div;
}

function updateStreamingAIBubbleText(bubbleEl, text) {
  const bubble = bubbleEl.querySelector(".ai-streaming-text-bubble");
  if (bubble) {
    bubble.textContent = text;
  }
  scrollToBottom();
}

function finalizeStreamingAIBubble(bubbleEl, text, intent, suggestions = []) {
  const intentIcon = intentToIcon(intent);
  const intentLabel = intent ? intent.replace(/_/g, " ") : "";
  
  const intentTag = bubbleEl.querySelector(".ai-streaming-intent-tag");
  if (intentTag && intent && intent !== "error") {
    intentTag.innerHTML = `${intentIcon} ${intentLabel}`;
    intentTag.style.display = "inline-flex";
  }

  const bubble = bubbleEl.querySelector(".ai-streaming-text-bubble");
  if (bubble) {
    bubble.innerHTML = formatAIText(text);
  }

  if (suggestions && suggestions.length > 0) {
    const suggestionsDiv = document.createElement("div");
    suggestionsDiv.className = "suggestion-chips active-suggestions";
    suggestionsDiv.style.marginTop = "8px";
    suggestionsDiv.innerHTML = suggestions.map((s, idx) => `
      <button class="chip dynamic-suggestion-chip" style="--chip-idx: ${idx};" data-prompt="${escapeHtml(s)}">${escapeHtml(s)}</button>
    `).join("");
    
    bubble.parentNode.appendChild(suggestionsDiv);
    
    suggestionsDiv.querySelectorAll(".dynamic-suggestion-chip").forEach(chip => {
      chip.addEventListener("click", () => {
        sendMessage(chip.dataset.prompt);
      });
    });
  }

  const meta = bubbleEl.querySelector(".ai-streaming-meta");
  if (meta) {
    meta.innerHTML = `${now()} · <span class="msg-speak-btn" title="Read message" style="cursor:pointer; opacity:0.6; transition:opacity 0.2s;">🔊 Speak</span>`;
    meta.style.display = "block";
    
    const speakBtn = meta.querySelector(".msg-speak-btn");
    if (speakBtn) {
      speakBtn.addEventListener("click", () => {
        speakText(text);
      });
      speakBtn.addEventListener("mouseenter", () => speakBtn.style.opacity = "1");
      speakBtn.addEventListener("mouseleave", () => speakBtn.style.opacity = "0.6");
    }
  }
  
  scrollToBottom();
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
  scrollToNewMessage(div);
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
  // Extract and parse <product-grid> JSON blocks before escaping HTML
  const gridRegex = /<product-grid>([\s\S]*?)<\/product-grid>/g;
  let matches = [];
  let modifiedText = text.replace(gridRegex, (match, jsonStr) => {
    try {
      const products = JSON.parse(jsonStr.trim());
      const gridHtml = renderProductGrid(products);
      const placeholder = `__PRODUCT_GRID_PLACEHOLDER_${matches.length}__`;
      matches.push(gridHtml);
      return placeholder;
    } catch (e) {
      console.error("Failed to parse product-grid JSON:", e);
      return match;
    }
  });

  // 1. Escape HTML first
  let safe = escapeHtml(modifiedText);

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

  let formattedHtml = result.join("");

  // Re-insert rendered product grids
  for (let i = 0; i < matches.length; i++) {
    formattedHtml = formattedHtml.replace(`__PRODUCT_GRID_PLACEHOLDER_${i}__`, matches[i]);
  }

  return formattedHtml;
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

function scrollToNewMessage(messageEl) {
  setTimeout(() => {
    if (!messagesEl || !messageEl) return;

    // Since messagesEl (.messages-container) is position: relative,
    // messageEl.offsetTop is directly the offset relative to the scroll container.
    const messageTop = messageEl.offsetTop;
    const messageHeight = messageEl.scrollHeight;
    const containerHeight = messagesEl.clientHeight;

    if (messageHeight > containerHeight - 40) {
      messagesEl.scrollTo({
        top: messageTop - 10,
        behavior: "smooth"
      });
    } else {
      messagesEl.scrollTo({
        top: messagesEl.scrollHeight,
        behavior: "smooth"
      });
    }
  }, 100);
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
      chatInput.placeholder = "Processing...";
      showToast("⚙️ Processing speech...");
      sendMessage(text);
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
      chatInput.value = text;
      autoResizeTextarea();
      sendBtn.disabled = false;
      if (shouldSubmit) {
        sendMessage(text);
      } else {
        showToast("✓ Transcribed – press Send");
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
  const statusEl  = document.getElementById("phoneStatus");
  const pulse1    = document.getElementById("phonePulse1");
  const pulse2    = document.getElementById("phonePulse2");
  const card      = document.querySelector(".phone-card");
  const badgeText = document.getElementById("stateBadgeText");
  const badgeIcon = document.getElementById("stateBadgeIcon");
  const listeningPop = document.getElementById("phoneListeningPop");

  if (listeningPop) {
    if (state === "LISTENING") {
      listeningPop.classList.add("active");
    } else {
      listeningPop.classList.remove("active");
    }
  }

  if (!statusEl) return;

  // Reset element classes
  statusEl.className = "phone-status";
  if (pulse1) pulse1.className = "phone-avatar-pulse";
  if (pulse2) pulse2.className = "phone-avatar-pulse-2";

  // Clear all call-state classes from card, add the new one
  if (card) {
    card.classList.remove("call-state-speaking", "call-state-listening", "call-state-processing");
    if (state === "GREETING" || state === "SPEAKING") card.classList.add("call-state-speaking");
    else if (state === "LISTENING") card.classList.add("call-state-listening");
    else if (state === "PROCESSING") card.classList.add("call-state-processing");
  }

  const micPaths   = '<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="22"/>';
  const wavePaths  = '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/>';
  const mutedPaths = '<line x1="1" y1="1" x2="23" y2="23"/><path d="M9 9v3a3 3 0 0 0 5.12 2.12M15 9.34V4a3 3 0 0 0-5.94-.6"/><line x1="12" y1="19" x2="12" y2="22"/>';

  if (state === "GREETING") {
    statusEl.textContent = "AI Greeting...";
    statusEl.classList.add("speaking");
    if (pulse1) pulse1.classList.add("pulse-speaking");
    if (pulse2) pulse2.classList.add("pulse-speaking");
    if (badgeText) badgeText.textContent = "Speaking";
    if (badgeIcon) badgeIcon.innerHTML = wavePaths;
  } else if (state === "SPEAKING") {
    statusEl.textContent = "AI Speaking...";
    statusEl.classList.add("speaking");
    if (pulse1) pulse1.classList.add("pulse-speaking");
    if (pulse2) pulse2.classList.add("pulse-speaking");
    if (badgeText) badgeText.textContent = "Speaking";
    if (badgeIcon) badgeIcon.innerHTML = wavePaths;
  } else if (state === "LISTENING") {
    statusEl.textContent = "Listening...";
    statusEl.classList.add("listening");
    if (pulse1) pulse1.classList.add("pulse-listening");
    if (pulse2) pulse2.classList.add("pulse-listening");
    if (badgeText) badgeText.textContent = "Listening";
    if (badgeIcon) badgeIcon.innerHTML = micPaths;
  } else if (state === "PROCESSING") {
    statusEl.textContent = "Processing...";
    statusEl.classList.add("processing");
    if (pulse1) pulse1.classList.add("pulse-processing");
    if (pulse2) pulse2.classList.add("pulse-processing");
    if (badgeText) badgeText.textContent = "Processing";
    if (badgeIcon) badgeIcon.innerHTML = micPaths;
  } else if (state === "MUTED") {
    statusEl.textContent = "Muted";
    statusEl.classList.add("muted");
    if (badgeText) badgeText.textContent = "Muted";
    if (badgeIcon) badgeIcon.innerHTML = mutedPaths;
  } else {
    statusEl.textContent = "Connecting...";
    if (badgeText) badgeText.textContent = "Connecting";
    if (badgeIcon) badgeIcon.innerHTML = micPaths;
  }
}
// ── Voice Filler System & Playback Helpers ─────────────────────────────────────
async function loadFillerClips() {
  if (fillerTrees.length) return;
  try {
    const res = await fetch('/api/fillers');
    const data = await res.json();
    fillerTrees = data.trees || [];
    fillerThinking = data.thinking || [];
    console.log(`[VoiceFillers] Loaded ${fillerTrees.length} trees and ${fillerThinking.length} thinking clips.`);
  } catch (e) {
    console.warn('[VoiceFillers] Could not load filler clips from server:', e);
  }
}

function randomThinking() {
  if (!fillerThinking.length) return null;
  return fillerThinking[Math.floor(Math.random() * fillerThinking.length)];
}

function pickNextFillerClip() {
  if (treeStep > 0 && Math.random() < 0.5) {
    const t = randomThinking();
    if (t) return t;
  }
  if (currentTree && treeStep < currentTree.length) {
    return currentTree[treeStep++];
  }
  return randomThinking();
}

function randomGapMs() {
  return FILLER_GAP_MIN_MS + Math.random() * (FILLER_GAP_MAX_MS - FILLER_GAP_MIN_MS);
}

function playPcmClip(base64, onended) {
  if (!phoneAudioContext) {
    if (onended) onended();
    return null;
  }
  try {
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    
    const int16 = new Int16Array(bytes.buffer);
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 32768;
    
    const audioBuffer = phoneAudioContext.createBuffer(1, float32.length, 24000);
    audioBuffer.copyToChannel(float32, 0);
    
    const source = phoneAudioContext.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(phoneAudioContext.destination);
    source.onended = () => {
      if (onended) onended();
    };
    source.start();
    return source;
  } catch (e) {
    console.error("[VoiceFillers] Error playing filler PCM clip:", e);
    if (onended) onended();
    return null;
  }
}

function speakFiller() {
  if (!awaitingResponse) return; // response already started
  const clip = pickNextFillerClip();
  if (!clip) return;
  fillerActive = true;
  setCallState("SPEAKING");
  
  fillerSource = playPcmClip(clip, () => {
    fillerSource = null;
    fillerActive = false;
    
    if (playbackQueue.length > 0) {
      // response arrived during filler
      awaitingResponse = false;
      while (playbackQueue.length > 0) {
        const item = playbackQueue.shift();
        feedPcmBase64(item);
      }
    } else if (awaitingResponse && !responseDone) {
      setCallState("PROCESSING");
      fillerTimer = setTimeout(() => {
        if (awaitingResponse && playbackQueue.length === 0 && !responseDone) speakFiller();
      }, randomGapMs());
    } else {
      cancelFillers();
      if (responseDone && playbackQueue.length === 0) {
        setCallState("LISTENING");
      }
    }
  });
}

function startFillerCycle() {
  cancelFillers();
  awaitingResponse = true;
  responseDone = false;
  treeStep = 0;
  currentTree = fillerTrees.length
    ? fillerTrees[Math.floor(Math.random() * fillerTrees.length)]
    : null;
  fillerTimer = setTimeout(() => {
    if (awaitingResponse && playbackQueue.length === 0) speakFiller();
  }, FILLER_GRACE_MS);
}

function cancelFillers() {
  awaitingResponse = false;
  fillerActive = false;
  if (fillerTimer) {
    clearTimeout(fillerTimer);
    fillerTimer = null;
  }
  if (fillerSource) {
    try {
      fillerSource.onended = null;
      fillerSource.stop();
    } catch (e) {}
    fillerSource = null;
  }
}

function queueAudio(base64Delta) {
  if (fillerActive) {
    playbackQueue.push(base64Delta);
    return;
  }
  
  if (awaitingResponse) {
    awaitingResponse = false;
    if (fillerTimer) {
      clearTimeout(fillerTimer);
      fillerTimer = null;
    }
  }
  
  // Drain queue if there are any items
  while (playbackQueue.length > 0) {
    const item = playbackQueue.shift();
    feedPcmBase64(item);
  }
  
  feedPcmBase64(base64Delta);
}

function feedPcmBase64(base64) {
  if (pcmPlayer && isPhoneSpeakerActive && voiceMode === "server_audio") {
    setCallState("SPEAKING");
    isResponseFinished = false;
    
    try {
      const binary = atob(base64);
      const buffer = new ArrayBuffer(binary.length);
      const view = new Uint8Array(buffer);
      for (let i = 0; i < binary.length; i++) {
        view[i] = binary.charCodeAt(i);
      }
      pcmPlayer.feed(buffer);
    } catch (e) {
      console.error("[Voice] Error feeding PCM chunk:", e);
    }
  }
}

async function startPhoneCall() {
  if (isInCallMode) return;

  // Clean up any legacy call resources to prevent memory leaks/duplicate event listeners
  if (voiceSocket) {
    console.log("[Voice] Cleaning up legacy WebSocket connection...");
    try {
      voiceSocket.onopen = null;
      voiceSocket.onmessage = null;
      voiceSocket.onclose = null;
      voiceSocket.onerror = null;
      voiceSocket.close();
    } catch (e) {}
    voiceSocket = null;
  }
  if (pcmPlayer) {
    console.log("[Voice] Stopping legacy pcmPlayer...");
    try {
      pcmPlayer.stop();
    } catch (e) {}
    pcmPlayer = null;
  }
  if (phoneRecognition) {
    console.log("[Voice] Aborting legacy SpeechRecognition...");
    try {
      phoneRecognition.abort();
    } catch (e) {}
    phoneRecognition = null;
  }

  isInCallMode = true;
  isPhoneMuted = false;
  voiceMode = "server_audio"; // Reset to default mode on start
  isResponseFinished = false; // Reset response finished state
  userTranscriptText = ""; // Clear transcript text
  awaitingResponse = false;
  fillerActive = false;
  responseDone = false;
  playbackQueue = [];
  playing = false;

  // Pre-load filler audio clips from server
  loadFillerClips();

  // Resume or create AudioContext inside user-gesture event handler with 24kHz sample rate natively
  try {
    if (!phoneAudioContext) {
      phoneAudioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 24000 });
    }
    if (phoneAudioContext.state === "suspended") {
      await phoneAudioContext.resume();
    }
    console.log("[Voice] AudioContext initialized/resumed at 24kHz. State:", phoneAudioContext.state);
  } catch (audioInitErr) {
    console.warn("[Voice] Failed to initialize AudioContext synchronously:", audioInitErr);
  }

  if (isRecording) {
    stopRecording(false);
  }

  chatInput.value = "";
  hideError();

  const muteBtn = document.getElementById("phoneMuteBtn");
  if (muteBtn) {
    muteBtn.classList.remove("muted");
  }

  // Show Overlay
  const chatPanelEl = document.getElementById("chatPanel");
  const accountPanelEl = document.getElementById("accountPanel");
  if (chatPanelEl) chatPanelEl.style.display = 'none';
  if (accountPanelEl) accountPanelEl.style.display = 'none';
  document.getElementById("phoneCallOverlay").classList.add("active");
  document.getElementById("phoneTranscript").textContent = "Connecting to voice service...";
  const phoneAIEl = document.getElementById("phoneAIResponse");
  if (phoneAIEl) phoneAIEl.textContent = "Connecting to real-time voice endpoint...";
  
  setCallState("GREETING");

  // Timeout if WebSocket doesn't connect within 3s
  let connectionTimeout = setTimeout(() => {
    if (voiceSocket && voiceSocket.readyState !== WebSocket.OPEN) {
      console.warn("[Voice] WebSocket connection timed out. Falling back to native HTTP voice mode.");
      showToast("⚠️ Server voice connection timeout. Using local browser fallback.");
      switchToNativeHttpMode();
    }
  }, 3000);

  try {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    voiceSocket = new WebSocket(`${protocol}//${host}/api/voice-realtime`);

    voiceSocket.onopen = async () => {
      clearTimeout(connectionTimeout);
      console.log("[Voice] WebSocket connected. Initializing audio capture...");
      document.getElementById("phoneTranscript").textContent = "Establishing voice channel...";
      await initVoiceAudio();
      document.getElementById("phoneTranscript").textContent = "Say something! I am listening...";
      if (phoneAIEl) phoneAIEl.textContent = "Listening...";
      setCallState("LISTENING");
    };

    voiceSocket.onmessage = async (event) => {
      if (typeof event.data === "string") {
        try {
          const msg = JSON.parse(event.data);
          
          if (msg.type === "audio_delta" && msg.delta) {
            queueAudio(msg.delta);
          }
          else if (msg.type === "speech_started") {
            console.log("[Voice] Upstream speech started (barge-in). Stopping playback.");
            cancelFillers();
            playbackQueue = [];
            if (pcmPlayer) pcmPlayer.stop();
            window.speechSynthesis.cancel();
            document.getElementById("phoneTranscript").textContent = "Listening...";
            setCallState("LISTENING");
          }
          else if (msg.type === "speech_stopped") {
            console.log("[Voice] Upstream speech stopped. Start filler timer.");
            document.getElementById("phoneTranscript").textContent = "Processing...";
            setCallState("PROCESSING");
            startFillerCycle();
          }
          else if (msg.type === "audio_done") {
            console.log("[Voice] Upstream audio response complete.");
            responseDone = true;
            if (!playing && !fillerActive && playbackQueue.length === 0) {
              cancelFillers();
              setCallState("LISTENING");
            }
          }
          else if (msg.type === "user_transcript_delta") {
            const transEl = document.getElementById("phoneTranscript");
            if (transEl) {
              if (userTranscriptText === "") {
                transEl.textContent = "";
              }
              userTranscriptText += msg.delta;
              transEl.textContent = userTranscriptText;
            }
          }
          else if (msg.type === "user_transcript") {
            const transEl = document.getElementById("phoneTranscript");
            if (transEl) {
              transEl.textContent = msg.text;
            }
            userTranscriptText = "";
            appendUserMessage(msg.text);
          }
          else if (msg.type === "agent_transcript") {
            console.log("[Voice] Received agent final transcript:", msg.text);
            appendAIMessage(msg.text, "specialist", ["Track my order", "Find nearest store", "Check product stock"]);
            conversationHistory.push({ role: "assistant", content: msg.text });
            fetchCustomerData();
            
            const phoneAIEl = document.getElementById("phoneAIResponse");
            if (phoneAIEl) phoneAIEl.textContent = msg.text;
          }
          else if (msg.type === "error") {
            console.error("VoiceLive error:", msg.message);
            document.getElementById("phoneTranscript").textContent = "Error: " + msg.message;
          }
        } catch (e) {
          console.error("Error parsing WebSocket message:", e);
        }
      }
    };

    voiceSocket.onclose = () => {
      console.log("[Voice] WebSocket closed.");
      clearTimeout(connectionTimeout);
      cancelFillers();
      if (isInCallMode) {
        if (voiceMode === "server_audio" || voiceMode === "native_ws") {
          switchToNativeHttpMode();
        } else {
          endPhoneCall();
        }
      }
    };

    voiceSocket.onerror = (err) => {
      console.error("[Voice] WebSocket error:", err);
      clearTimeout(connectionTimeout);
      cancelFillers();
      if (isInCallMode) {
        showToast("⚠️ Server voice connection failed. Using local browser fallback.");
        switchToNativeHttpMode();
      }
    };

  } catch (ex) {
    console.error("Failed to start phone call:", ex);
    clearTimeout(connectionTimeout);
    cancelFillers();
    switchToNativeHttpMode();
  }
}

function switchToNativeHttpMode() {
  if (!isInCallMode) return;
  
  cancelFillers();
  console.log("[Voice] Switching to native HTTP fallback mode.");
  voiceMode = "native_http";
  
  if (pcmPlayer) {
    try {
      pcmPlayer.stop();
    } catch (e) {}
    pcmPlayer = null;
  }
  if ('speechSynthesis' in window) {
    try {
      window.speechSynthesis.cancel();
    } catch (e) {}
  }

  if (voiceSocket) {
    try {
      voiceSocket.close();
    } catch(e) {}
    voiceSocket = null;
  }
  
  document.getElementById("phoneTranscript").textContent = "Local voice mode active. I am listening...";
  const phoneAIEl = document.getElementById("phoneAIResponse");
  if (phoneAIEl) phoneAIEl.textContent = "Listening (Local browser mode)...";
  
  setCallState("LISTENING");
  startListeningForCall();
}

function endPhoneCall() {
  if (!isInCallMode) return;
  isInCallMode = false;

  cancelFillers();
  playbackQueue = [];
  playing = false;
  awaitingResponse = false;
  fillerActive = false;
  responseDone = false;

  if (voiceSocket) {
    try {
      voiceSocket.close();
    } catch(e) {}
    voiceSocket = null;
  }

  if (pcmPlayer) {
    pcmPlayer.stop();
    pcmPlayer = null;
  }

  if (phoneScriptProcessor) {
    phoneScriptProcessor.disconnect();
    phoneScriptProcessor = null;
  }
  if (phoneMicSource) {
    phoneMicSource.disconnect();
    phoneMicSource = null;
  }
  if (phoneMicStream) {
    phoneMicStream.getTracks().forEach(track => track.stop());
    phoneMicStream = null;
  }
  if (phoneAudioContext) {
    phoneAudioContext.close();
    phoneAudioContext = null;
  }

  // Cancel any browser-native speech playing
  window.speechSynthesis.cancel();

  document.getElementById("phoneCallOverlay").classList.remove("active");
  const chatPanelEl = document.getElementById("chatPanel");
  if (chatPanelEl) chatPanelEl.style.display = 'flex';
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
    }
    showToast("🎙️ Microphone Muted");
    setCallState("MUTED");
  } else {
    if (muteBtn) {
      muteBtn.classList.remove("muted");
    }
    showToast("🎙️ Microphone Active");
    setCallState("LISTENING");
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
    if (pcmPlayer) {
      pcmPlayer.stop();
    }
  }
}

function getWordDelay(word) {
  let delay = 350; // base delay per word
  
  if (!word) return delay;
  
  // Clean word from punctuation for length check
  const cleanWord = word.replace(/[.,\/#!$%\^&\*;:{}=\-_`~()]/g, "");
  
  // Longer words take longer to speak
  if (cleanWord.length > 8) {
    delay += 120;
  } else if (cleanWord.length > 5) {
    delay += 60;
  } else if (cleanWord.length <= 2) {
    delay -= 60; // shorter words are spoken faster
  }
  
  // Punctuation pauses (to perfectly mirror natural neural voice pauses)
  if (word.endsWith(",") || word.endsWith(";") || word.endsWith(":")) {
    delay += 250; // comma pause
  } else if (word.endsWith(".") || word.endsWith("?") || word.endsWith("!")) {
    delay += 600; // sentence end pause
  }
  
  return delay;
}

function speakPhoneCallText(text) {
  // If speaker is off, don't play audio
  if (!isPhoneSpeakerActive) {
    startListeningForCall();
    return;
  }

  // Clean text for TTS
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

  if (!cleanText) {
    startListeningForCall();
    return;
  }

  // Use browser-native SpeechSynthesis directly for instant playback (0ms server latency)
  speakPhoneCallTextNativeFallback(cleanText);
}

function speakPhoneCallTextNativeFallback(cleanText) {
  if (!('speechSynthesis' in window)) {
    startListeningForCall();
    return;
  }

  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(cleanText);
  utterance.lang = "en-GB";

  // Select voice using standard fallback logic
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

  utterance.onboundary = (event) => {
    if (event.name === 'word') {
      const charIndex = event.charIndex;
      const remainingText = cleanText.substring(charIndex);
      const nextSpace = remainingText.indexOf(' ');
      const wordLength = nextSpace === -1 ? remainingText.length : nextSpace;
      const spokenPart = cleanText.substring(0, charIndex + wordLength);
      
      const phoneAIEl = document.getElementById("phoneAIResponse");
      if (phoneAIEl) {
        phoneAIEl.textContent = spokenPart;
      }
    }
  };

  utterance.onend = () => {
    currentUtterance = null;
    if (isInCallMode) {
      startListeningForCall();
    }
  };

  utterance.onerror = (e) => {
    console.error("SpeechSynthesisUtterance fallback error:", e);
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
  }, PHONE_SILENCE_DURATION);
}

function startListeningForCall() {
  if (!isInCallMode || isPhoneMuted) return;

  // Reset the current turn transcripts, but do NOT clear the visible DOM text
  // so the conversation history remains on the screen until the user starts speaking again.
  phoneCurrentTurnTranscript = "";
  phoneAccumulatedTurnTranscript = "";
  
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
        let sessionFinalTranscript = "";
        let interimTranscript = "";
        for (let i = 0; i < event.results.length; ++i) {
          if (event.results[i].isFinal) {
            sessionFinalTranscript += event.results[i][0].transcript;
          } else {
            interimTranscript += event.results[i][0].transcript;
          }
        }
        
        finalTranscript = sessionFinalTranscript;

        const currentSegmentText = (finalTranscript + interimTranscript).trim();
        const totalText = (phoneAccumulatedTurnTranscript + " " + currentSegmentText).trim();
        
        if (totalText) {
          phoneCurrentTurnTranscript = totalText;
          const transcriptPreview = document.getElementById("phoneTranscript");
          if (transcriptPreview) {
            transcriptPreview.textContent = totalText;
          }

          // Barge-in (Interruption Support)
          if (callState === "SPEAKING" || callState === "GREETING") {
            const wordCount = totalText.split(/\s+/).filter(Boolean).length;
            if (wordCount >= 1) {
              console.log("[CallMode] User interrupted AI speech. Stopping TTS...");
              
              // Cancel native TTS
              window.speechSynthesis.cancel();
              currentUtterance = null;

              // Cancel Azure Audio TTS
              if (currentAudioElement) {
                currentAudioElement.pause();
                currentAudioElement = null;
              }
              
              setCallState("LISTENING");
              
              const phoneAIEl = document.getElementById("phoneAIResponse");
              if (phoneAIEl) phoneAIEl.textContent = "Interrupted...";
              
              // Clear previous turn segment logs to focus on new question
              phoneAccumulatedTurnTranscript = "";
              finalTranscript = "";
              phoneCurrentTurnTranscript = totalText;
              
              if (transcriptPreview) {
                transcriptPreview.textContent = totalText;
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
        // Save the completed speech segment to the accumulated turn transcript
        if (finalTranscript) {
          phoneAccumulatedTurnTranscript = (phoneAccumulatedTurnTranscript + " " + finalTranscript).trim();
          finalTranscript = "";
        }
        
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
function submitPhoneCallTurn() {
  submitPhoneCallTurnNative();
}

async function submitPhoneCallTurnNative() {
  if (!isInCallMode || isPhoneMuted) return;

  if (voiceMode === "server_audio") {
    console.log("[Voice] submitPhoneCallTurn ignored in server_audio mode. Upstream audio handling is active.");
    return;
  }

  const text = phoneCurrentTurnTranscript.trim();

  if (!text) {
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

  appendUserMessage(text);
  conversationHistory.push({ role: "user", content: text });

  if (voiceMode === "native_ws" && voiceSocket && voiceSocket.readyState === WebSocket.OPEN) {
    console.log("[Voice] Sending native transcript via WebSocket text channel:", text);
    voiceSocket.send(JSON.stringify({ type: "voice_query", text: text }));
    return;
  }

  // HTTP POST Fallback (Tier 3)
  try {
    const response = await fetch(`${API_BASE}/chat/voice`, {
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

class PCMPlayer {
  constructor(audioContext, sampleRate = 16000) {
    this.audioContext = audioContext;
    this.sampleRate = sampleRate;
    this.queue = [];
    this.startTime = 0;
    this.onEnded = null;
  }
  
  feed(pcmBuffer) {
    const int16Array = new Int16Array(pcmBuffer);
    const float32Array = new Float32Array(int16Array.length);
    for (let i = 0; i < int16Array.length; i++) {
      float32Array[i] = int16Array[i] / 32768;
    }
    
    const audioBuffer = this.audioContext.createBuffer(1, float32Array.length, this.sampleRate);
    audioBuffer.copyToChannel(float32Array, 0);
    
    const source = this.audioContext.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(this.audioContext.destination);
    
    let playTime = this.startTime;
    const now = this.audioContext.currentTime;
    if (playTime < now) {
      playTime = now + 0.03; // 30ms safety buffer
    }
    
    source.start(playTime);
    this.startTime = playTime + audioBuffer.duration;
    this.queue.push(source);
    
    source.onended = () => {
      const idx = this.queue.indexOf(source);
      if (idx !== -1) {
        this.queue.splice(idx, 1);
      }
      if (this.queue.length === 0 && this.onEnded) {
        this.onEnded();
      }
    };
  }
  
  stop() {
    this.queue.forEach(source => {
      try {
        source.stop();
      } catch (e) {}
    });
    this.queue = [];
    this.startTime = 0;
  }
}

async function initVoiceAudio() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    phoneMicStream = stream;

    if (!phoneAudioContext) {
      phoneAudioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 24000 });
    }
    if (phoneAudioContext.state === "suspended") {
      await phoneAudioContext.resume();
    }
    phoneMicSource = phoneAudioContext.createMediaStreamSource(stream);

    pcmPlayer = new PCMPlayer(phoneAudioContext, 24000);
    pcmPlayer.onEnded = () => {
      if (responseDone && isInCallMode && !awaitingResponse && !fillerActive) {
        console.log("[Voice] Playback queue empty and response done. Transitioning back to LISTENING.");
        setCallState("LISTENING");
      }
    };

    phoneScriptProcessor = phoneAudioContext.createScriptProcessor(4096, 1, 1);
    
    phoneScriptProcessor.onaudioprocess = (e) => {
      if (!isInCallMode || isPhoneMuted) return;
      const channelData = e.inputBuffer.getChannelData(0);
      const pcm16 = floatTo16BitPCM(channelData);
      
      if (voiceSocket && voiceSocket.readyState === WebSocket.OPEN) {
        voiceSocket.send(pcm16.buffer);
      }
    };

    const dummyGain = phoneAudioContext.createGain();
    dummyGain.gain.value = 0.0;
    phoneMicSource.connect(phoneScriptProcessor);
    phoneScriptProcessor.connect(dummyGain);
    dummyGain.connect(phoneAudioContext.destination);
    
    console.log("[Voice] Audio capture and player initialized at 24kHz natively.");
  } catch (err) {
    console.error("Failed to initialize audio:", err);
    showError("Microphone access is required for call mode.");
  }
}

function floatTo16BitPCM(float32Array) {
  const out = new Int16Array(float32Array.length);
  for (let i = 0; i < float32Array.length; i++) {
    let s = Math.max(-1, Math.min(1, float32Array[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
  }
  return out;
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

// ── Product Grid Renderer Helpers ───────────────────────────────────────────
function getProductIcon(category) {
  const cat = (category || "").toLowerCase();
  if (cat.includes("dairy")) return "🥛";
  if (cat.includes("bakery") || cat.includes("bread")) return "🍞";
  if (cat.includes("pantry") || cat.includes("oil") || cat.includes("condiment")) return "🫙";
  if (cat.includes("fruit") || cat.includes("vegetable") || cat.includes("produce")) return "🍎";
  if (cat.includes("meat") || cat.includes("poultry") || cat.includes("chicken")) return "🍗";
  if (cat.includes("fish") || cat.includes("seafood")) return "🐟";
  if (cat.includes("beverage") || cat.includes("drink")) return "🥤";
  if (cat.includes("snack") || cat.includes("sweet") || cat.includes("chocolate")) return "🍫";
  if (cat.includes("frozen")) return "❄️";
  return "🛒";
}

function renderStars(rating) {
  const r = parseFloat(rating) || 0;
  let stars = "";
  for (let i = 1; i <= 5; i++) {
    if (i <= r) {
      stars += "★";
    } else {
      stars += "☆";
    }
  }
  return stars;
}

function renderBadges(product) {
  let badges = "";
  if (product.best_seller) {
    badges += `<div class="product-card-badge badge-bestseller">Best Seller</div>`;
  }
  if (product.is_on_promotion) {
    badges += `<div class="product-card-badge badge-promo">${product.promotion_detail || "Promo"}</div>`;
  }
  if (product.store_recommended) {
    badges += `<div class="product-card-badge badge-recommended">Staff Pick</div>`;
  }
  return badges;
}

function getAvailabilityClass(status) {
  const s = (status || "").toLowerCase();
  if (s.includes("in stock")) return "status-instock";
  if (s.includes("limited")) return "status-limited";
  if (s.includes("out of stock")) return "status-outofstock";
  return "status-instock";
}

function renderProductGrid(products) {
  if (!Array.isArray(products) || products.length === 0) return "";
  
  let cardsHtml = products.map(p => {
    const icon = getProductIcon(p.category);
    const badges = renderBadges(p);
    const stars = renderStars(p.customer_rating);
    const availClass = getAvailabilityClass(p.availability);
    const priceStr = typeof p.price === "number" ? p.price.toFixed(2) : parseFloat(p.price || 0).toFixed(2);
    
    const isOutOfStock = (p.availability || "").toLowerCase().includes("out of stock");
    const actionBtn = isOutOfStock 
      ? `<button class="product-card-action-btn" disabled style="background:#e5e7eb;color:#9ca3af;cursor:not-allowed;">Out of Stock</button>`
      : `<button class="product-card-action-btn" onclick="sendMessage('Add ${p.id} to cart')">🛒 Add to Basket</button>`;
      
    const explanationHtml = p.explanation 
      ? `<div class="product-card-explanation">${escapeHtml(p.explanation)}</div>` 
      : "";

    return `
      <div class="product-card">
        ${badges}
        <div class="product-card-img-wrapper">
          <div class="product-card-fallback-img">${icon}</div>
        </div>
        <div class="product-card-body">
          <div class="product-card-brand">${escapeHtml(p.brand || "Sainsbury's")}</div>
          <div class="product-card-title" title="${escapeHtml(p.name)}">${escapeHtml(p.name)}</div>
          <div class="product-card-rating">
            <span class="product-card-rating-stars">${stars}</span>
            <span>(${p.review_count || 0})</span>
          </div>
          <div class="product-card-footer">
            <div class="product-card-price">£${priceStr}</div>
            <div class="product-card-status ${availClass}">${escapeHtml(p.availability || "In Stock")}</div>
          </div>
          ${explanationHtml}
          ${actionBtn}
        </div>
      </div>
    `;
  }).join("");

  return `<div class="product-grid-container">${cardsHtml}</div>`;
}
