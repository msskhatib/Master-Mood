// Plays queued MP3 chunks one after another.
const queue = [];
let audio = null;
let lastQueued = false;

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.target !== "offscreen") return;
  if (msg.type === "reset") {
    queue.length = 0;
    lastQueued = false;
    if (audio) { audio.pause(); URL.revokeObjectURL(audio.src); audio = null; }
  } else if (msg.type === "enqueue") {
    queue.push(msg.audio);
    lastQueued = msg.last;
    if (!audio) playNext();
  } else if (msg.type === "pause") {
    audio?.pause();
  } else if (msg.type === "resume") {
    audio?.play();
  }
});

function playNext() {
  const b64 = queue.shift();
  if (!b64) {
    audio = null;
    if (lastQueued) chrome.runtime.sendMessage({ target: "background-event", type: "finished" });
    return;
  }
  const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], { type: "audio/mpeg" }));
  audio = new Audio(url);
  audio.onended = () => { URL.revokeObjectURL(url); playNext(); };
  audio.onerror = () => { URL.revokeObjectURL(url); playNext(); };
  audio.play();
}
