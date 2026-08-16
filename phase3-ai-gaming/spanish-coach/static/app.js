const $ = (id) => document.getElementById(id);
const audio = $("audio");
let currentStory = null;
let recorder = null;
let chunks = [];

function authHeaders(extra = {}) {
  const token = localStorage.getItem("spanishCoachToken") || "";
  return token ? {...extra, Authorization: `Bearer ${token}`} : extra;
}

async function api(path, options = {}) {
  options.headers = authHeaders(options.headers || {});
  const res = await fetch(path, options);
  if (!res.ok) throw new Error(await res.text());
  return res;
}

function card(html) {
  const el = document.createElement("div");
  el.className = "card";
  el.innerHTML = html;
  return el;
}

document.querySelectorAll("nav button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll("nav button, .tab").forEach((el) => el.classList.remove("active"));
    button.classList.add("active");
    $(button.dataset.tab).classList.add("active");
  });
});

$("tokenInput").value = localStorage.getItem("spanishCoachToken") || "";
$("tokenInput").addEventListener("change", () => {
  localStorage.setItem("spanishCoachToken", $("tokenInput").value.trim());
  refreshHealth();
});

async function refreshHealth() {
  try {
    const data = await (await api("/health")).json();
    $("health").textContent = data.ok ? "Ready" : "Degraded";
  } catch {
    $("health").textContent = "Offline";
  }
}

$("sendChat").addEventListener("click", async () => {
  const message = $("chatInput").value.trim();
  if (!message) return;
  $("chatOutput").prepend(card(`<strong>You</strong><p>${message}</p>`));
  const data = await (await api("/api/chat", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({message})
  })).json();
  $("chatOutput").prepend(card(`<strong>Coach</strong><p class="spanish">${data.reply}</p><p class="muted">Next: ${data.next_phrase || ""}</p>`));
});

$("recordBtn").addEventListener("click", async () => {
  if (recorder && recorder.state === "recording") {
    recorder.stop();
    $("recordBtn").textContent = "Record";
    return;
  }
  const stream = await navigator.mediaDevices.getUserMedia({audio: true});
  chunks = [];
  recorder = new MediaRecorder(stream);
  recorder.ondataavailable = (event) => chunks.push(event.data);
  recorder.onstop = async () => {
    const blob = new Blob(chunks, {type: "audio/webm"});
    const form = new FormData();
    form.append("file", blob, "speech.webm");
    const data = await (await api("/api/audio/transcribe", {method: "POST", body: form})).json();
    $("chatInput").value = data.text || "";
    stream.getTracks().forEach((track) => track.stop());
  };
  recorder.start();
  $("recordBtn").textContent = "Stop";
});

$("makeStory").addEventListener("click", async () => {
  const payload = {
    level: $("storyLevel").value,
    topic: $("storyTopic").value,
    length: $("storyLength").value,
    tense: $("storyTense").value,
    vocab_focus: $("storyVocab").value
  };
  currentStory = await (await api("/api/stories", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload)
  })).json();
  $("storyOutput").innerHTML = `<h2>${currentStory.title}</h2><p class="spanish">${currentStory.spanish_text}</p><p class="english">${currentStory.english_text}</p><p class="muted">${currentStory.questions.join(" | ")}</p>`;
});

async function playSegments(segments) {
  const res = await api("/api/tts", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({segments})
  });
  const blob = await res.blob();
  audio.src = URL.createObjectURL(blob);
  await audio.play();
}

$("playStory").addEventListener("click", async () => {
  if (!currentStory) return;
  const plan = currentStory.listening_plan || {};
  const segments = (plan.sentence_loop || []).flatMap((item) => item.sequence || []);
  await playSegments(segments);
});

$("playLoop").addEventListener("click", async () => {
  const segments = $("loopText").value.split(/\n+/).map((line) => line.trim()).filter(Boolean);
  await playSegments(segments);
});

$("addVocab").addEventListener("click", async () => {
  const data = await (await api("/api/vocab", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({spanish: $("vocabSpanish").value, english: $("vocabEnglish").value, example_sentence: $("vocabExample").value})
  })).json();
  $("vocabOutput").prepend(renderCard(data));
});

$("loadDue").addEventListener("click", async () => {
  const data = await (await api("/api/vocab/due")).json();
  $("vocabOutput").replaceChildren(...data.map(renderCard));
});

function renderCard(item) {
  const el = card(`<strong class="spanish">${item.spanish}</strong><p>${item.english}</p><p class="muted">${item.example_sentence || ""}</p>`);
  ["again", "hard", "good", "easy"].forEach((rating) => {
    const b = document.createElement("button");
    b.textContent = rating;
    b.addEventListener("click", async () => {
      await api(`/api/vocab/${item.id}/review`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({rating})});
      el.remove();
    });
    el.appendChild(b);
  });
  return el;
}

refreshHealth();
