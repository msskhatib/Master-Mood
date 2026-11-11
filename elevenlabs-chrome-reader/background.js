// ElevenLabs Page Reader - background service worker
// Fetches speech from the ElevenLabs API and sends the audio to an
// offscreen document for playback (service workers cannot play audio).

const API = "https://api.elevenlabs.io/v1";
const DEFAULTS = {
  apiKey: "",
  voiceId: "21m00Tcm4TlvDq8EXCM", // "Rachel" - default ElevenLabs voice
  modelId: "eleven_multilingual_v2", // supports English, Arabic and 27+ other languages
  stability: 0.5,
  similarity: 0.75,
  speed: 1.0
};
const MAX_CHUNK = 2500; // characters per request

let session = 0; // increments on every new read / stop to cancel older jobs

async function getSettings() {
  return { ...DEFAULTS, ...(await chrome.storage.sync.get(Object.keys(DEFAULTS))) };
}

// ---------- context menu + shortcuts ----------
chrome.runtime.onInstalled.addListener((details) => {
  chrome.contextMenus.create({ id: "el-read-selection", title: "Read with ElevenLabs", contexts: ["selection"] });
  chrome.contextMenus.create({ id: "el-read-page", title: "Read whole page with ElevenLabs", contexts: ["page"] });
  chrome.contextMenus.create({ id: "el-stop", title: "Stop ElevenLabs reading", contexts: ["all"] });
  if (details.reason === "install") chrome.runtime.openOptionsPage();
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === "el-read-selection") readText(info.selectionText);
  if (info.menuItemId === "el-read-page") readText(await getPageText(tab.id, false));
  if (info.menuItemId === "el-stop") stop();
});

chrome.commands.onCommand.addListener(async (command, tab) => {
  if (command === "stop-reading") return stop();
  if (command === "read-selection") {
    const [t] = tab ? [tab] : await chrome.tabs.query({ active: true, currentWindow: true });
    readText(await getPageText(t.id, true));
  }
});

// ---------- messages from popup / offscreen ----------
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.target !== "background") return;
  (async () => {
    switch (msg.type) {
      case "read-selection": {
        const text = await getPageText(msg.tabId, true);
        sendResponse(await readText(text));
        break;
      }
      case "read-page": {
        const text = await getPageText(msg.tabId, false);
        sendResponse(await readText(text));
        break;
      }
      case "read-text":
        sendResponse(await readText(msg.text));
        break;
      case "stop":
        await stop();
        sendResponse({ ok: true });
        break;
      case "pause":
      case "resume":
        await sendToOffscreen({ type: msg.type });
        sendResponse({ ok: true });
        break;
      case "list-voices":
        sendResponse(await listVoices(msg.apiKey));
        break;
      default:
        sendResponse({ ok: false, error: "Unknown message" });
    }
  })();
  return true; // async response
});

// ---------- text extraction from the page ----------
async function getPageText(tabId, selectionOnly) {
  try {
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId },
      args: [selectionOnly],
      func: (selectionOnly) => {
        const sel = window.getSelection().toString().trim();
        if (selectionOnly || sel) return sel;
        const root = document.querySelector("article, main, [role=main]") || document.body;
        return root.innerText.replace(/\n{2,}/g, "\n").trim();
      }
    });
    return result || "";
  } catch (e) {
    console.warn("Cannot read this page:", e);
    return "";
  }
}

// ---------- split long text into sentence-based chunks ----------
function chunkText(text) {
  const sentences = text.replace(/\s+/g, " ").match(/[^.!?؟。]+[.!?؟。]*\s*/g) || [text];
  const chunks = [];
  let cur = "";
  for (const s of sentences) {
    if ((cur + s).length > MAX_CHUNK && cur) {
      chunks.push(cur.trim());
      cur = "";
    }
    if (s.length > MAX_CHUNK) {
      for (let i = 0; i < s.length; i += MAX_CHUNK) chunks.push(s.slice(i, i + MAX_CHUNK));
    } else cur += s;
  }
  if (cur.trim()) chunks.push(cur.trim());
  return chunks;
}

// ---------- ElevenLabs API ----------
async function tts(text, s) {
  const res = await fetch(`${API}/text-to-speech/${s.voiceId}?output_format=mp3_44100_128`, {
    method: "POST",
    headers: { "xi-api-key": s.apiKey, "Content-Type": "application/json", Accept: "audio/mpeg" },
    body: JSON.stringify({
      text,
      model_id: s.modelId,
      voice_settings: {
        stability: Number(s.stability),
        similarity_boost: Number(s.similarity),
        speed: Number(s.speed)
      }
    })
  });
  if (!res.ok) {
    let detail = await res.text();
    try { detail = JSON.parse(detail).detail?.message || detail; } catch {}
    throw new Error(`ElevenLabs error ${res.status}: ${detail}`);
  }
  const buf = await res.arrayBuffer();
  // base64 encode so it can be passed through runtime messaging
  let bin = "";
  const bytes = new Uint8Array(buf);
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

async function listVoices(apiKeyOverride) {
  const s = await getSettings();
  const key = apiKeyOverride || s.apiKey;
  if (!key) return { ok: false, error: "No API key" };
  const res = await fetch(`${API}/voices`, { headers: { "xi-api-key": key } });
  if (!res.ok) return { ok: false, error: `HTTP ${res.status}` };
  const data = await res.json();
  return { ok: true, voices: data.voices.map((v) => ({ id: v.voice_id, name: v.name, category: v.category })) };
}

// ---------- reading pipeline ----------
async function readText(text) {
  text = (text || "").trim();
  if (!text) return notify("No text found. Select some text on the page first.");
  const s = await getSettings();
  if (!s.apiKey) {
    chrome.runtime.openOptionsPage();
    return notify("Please add your ElevenLabs API key in the settings.");
  }

  const my = ++session;
  await ensureOffscreen();
  await sendToOffscreen({ type: "reset" });
  setBadge("...");

  const chunks = chunkText(text);
  // Fetch chunk N+1 while chunk N plays (simple prefetch of 1 ahead)
  let next = tts(chunks[0], s);
  try {
    for (let i = 0; i < chunks.length; i++) {
      const audio = await next;
      if (my !== session) return { ok: false, error: "cancelled" };
      if (i + 1 < chunks.length) next = tts(chunks[i + 1], s);
      setBadge(`${i + 1}/${chunks.length}`);
      await sendToOffscreen({ type: "enqueue", audio, last: i === chunks.length - 1 });
    }
    return { ok: true, chunks: chunks.length };
  } catch (e) {
    if (my === session) setBadge("");
    return notify(e.message);
  }
}

async function stop() {
  session++;
  setBadge("");
  if (await chrome.offscreen.hasDocument()) await sendToOffscreen({ type: "reset" });
}

// ---------- offscreen document for audio ----------
async function ensureOffscreen() {
  if (await chrome.offscreen.hasDocument()) return;
  await chrome.offscreen.createDocument({
    url: "offscreen.html",
    reasons: ["AUDIO_PLAYBACK"],
    justification: "Play ElevenLabs text-to-speech audio"
  });
}

function sendToOffscreen(msg) {
  return chrome.runtime.sendMessage({ target: "offscreen", ...msg }).catch(() => {});
}

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.target === "background-event" && msg.type === "finished") setBadge("");
});

// ---------- UI helpers ----------
function setBadge(text) {
  chrome.action.setBadgeBackgroundColor({ color: "#111" });
  chrome.action.setBadgeText({ text });
}

function notify(error) {
  console.warn(error);
  setBadge("!");
  chrome.storage.local.set({ lastError: error });
  return { ok: false, error };
}
