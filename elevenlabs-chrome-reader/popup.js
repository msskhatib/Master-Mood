const $ = (id) => document.getElementById(id);
const status = (t) => ($("status").textContent = t || "");

async function send(type, extra = {}) {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  status("Working...");
  const res = await chrome.runtime.sendMessage({ target: "background", type, tabId: tab?.id, ...extra });
  status(res && !res.ok && res.error !== "cancelled" ? res.error : "");
}

$("sel").onclick = () => send("read-selection");
$("page").onclick = () => send("read-page");
$("stop").onclick = () => send("stop");
$("pause").onclick = () => send("pause");
$("resume").onclick = () => send("resume");
$("readCustom").onclick = () => send("read-text", { text: $("custom").value });
$("opts").onclick = (e) => { e.preventDefault(); chrome.runtime.openOptionsPage(); };

chrome.storage.sync.get("apiKey").then(({ apiKey }) => {
  if (!apiKey) status("Add your ElevenLabs API key in Settings first.");
});
