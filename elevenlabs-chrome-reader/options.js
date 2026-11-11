const $ = (id) => document.getElementById(id);
const DEFAULTS = { apiKey: "", voiceId: "21m00Tcm4TlvDq8EXCM", modelId: "eleven_multilingual_v2", speed: 1.0, stability: 0.5, similarity: 0.75 };
const msg = (t, ok = true) => { $("msg").textContent = t; $("msg").style.color = ok ? "#070" : "#b00"; };

function bindRange(id) {
  const update = () => ($(id + "Val").textContent = $(id).value);
  $(id).addEventListener("input", update);
  update();
}

async function load() {
  const s = { ...DEFAULTS, ...(await chrome.storage.sync.get(Object.keys(DEFAULTS))) };
  for (const k of Object.keys(DEFAULTS)) if (k !== "voiceId") $(k).value = s[k];
  ["speed", "stability", "similarity"].forEach(bindRange);
  if (s.apiKey) await loadVoices(s.voiceId);
  else $("voiceId").value = s.voiceId;
}

async function loadVoices(selected) {
  const res = await chrome.runtime.sendMessage({ target: "background", type: "list-voices", apiKey: $("apiKey").value.trim() });
  if (!res?.ok) return msg("Could not load voices: " + (res?.error || "unknown error") + ". Check your API key.", false);
  const sel = $("voiceId");
  const current = selected || sel.value;
  sel.innerHTML = "";
  for (const v of res.voices) sel.add(new Option(`${v.name} (${v.category})`, v.id));
  if ([...sel.options].some((o) => o.value === current)) sel.value = current;
  msg(`Loaded ${res.voices.length} voices.`);
}

async function save() {
  const data = {};
  for (const k of Object.keys(DEFAULTS)) data[k] = $(k).value.trim();
  await chrome.storage.sync.set(data);
  msg("Saved ✔");
}

$("save").onclick = save;
$("loadVoices").onclick = () => loadVoices();
$("test").onclick = async () => {
  await save();
  const res = await chrome.runtime.sendMessage({ target: "background", type: "read-text", text: "Hello! This is your ElevenLabs voice reading in Google Chrome." });
  if (!res?.ok) msg(res?.error || "Error", false);
};
load();
