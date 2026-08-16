const $ = (id) => document.getElementById(id);
const audio = $("audio");
let currentStory = null;
let currentQueue = [];
let currentSegmentIndex = 0;
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

function setActiveTab(tabId) {
  document.querySelectorAll("nav button, .tab").forEach((el) => el.classList.remove("active"));
  document.querySelector(`[data-tab="${tabId}"]`)?.classList.add("active");
  $(tabId)?.classList.add("active");
  window.scrollTo({top: 0, behavior: "smooth"});
}

document.querySelectorAll("nav button").forEach((button) => {
  button.addEventListener("click", () => setActiveTab(button.dataset.tab));
});

$("tokenInput").value = localStorage.getItem("spanishCoachToken") || "";
$("tokenInput").addEventListener("change", () => {
  localStorage.setItem("spanishCoachToken", $("tokenInput").value.trim());
  refreshHealth();
  refreshProgress();
});

async function refreshHealth() {
  try {
    const data = await (await api("/health")).json();
    $("health").textContent = data.ok ? "● Ready" : "● Degraded";
    $("health").className = data.ok ? "ready" : "warn";
  } catch {
    $("health").textContent = "● Offline";
    $("health").className = "offline";
  }
}

async function refreshProgress() {
  try {
    const stats = await (await api("/api/progress")).json();
    $("stats").innerHTML = `
      <div><b>${stats.streak_days}</b><span>streak</span></div>
      <div><b>${stats.today_minutes}</b><span>min</span></div>
      <div><b>${stats.due_cards}</b><span>due</span></div>
      <div><b>${stats.favorites}</b><span>★</span></div>`;
  } catch {
    $("stats").innerHTML = "";
  }
}

function updateQueue(title, segment = null) {
  $("queueTitle").textContent = title || "Ready";
  $("queueNow").textContent = segment?.text || "Pick a practice mode.";
}

function queueFromStory(mode = "sentence") {
  if (!currentStory) return [];
  const plan = currentStory.listening_plan || {};
  if (mode === "full") return plan.full_loop || [];
  if (mode === "shadow") return (plan.shadowing || []).map((item) => ({text: item.spanish, lang: "es", pause_seconds: item.pause_seconds || 2.2}));
  return (plan.sentence_loop || []).flatMap((item) => item.sequence || []);
}

async function playSegments(segments, meta = {}) {
  currentQueue = normalizeSegments(segments);
  if (!currentQueue.length) return;
  const started = Date.now();
  updateQueue(meta.title || "Playing", currentQueue[0]);
  for (currentSegmentIndex = 0; currentSegmentIndex < currentQueue.length; currentSegmentIndex += 1) {
    const segment = currentQueue[currentSegmentIndex];
    updateQueue(`${currentSegmentIndex + 1}/${currentQueue.length}`, segment);
    try {
      const res = await api("/api/tts", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({segments: [segment], lang: segment.lang})
      });
      const blob = await res.blob();
      audio.src = URL.createObjectURL(blob);
      audio.playbackRate = Number($("speedSelect").value || 1);
      await audio.play();
      await waitForAudioEnd(audio);
    } catch {
      await speakInBrowser(segment.text, segment.lang);
    }
    const basePause = Number($("pauseSelect").value || 0.9);
    await delay(((segment.pause_seconds || 0.35) + basePause) * 1000);
  }
  updateQueue("Done", currentQueue[currentQueue.length - 1]);
  await trackEvent(meta.event_type || "playback", meta.item_type || "", meta.item_id || "", Math.round((Date.now() - started) / 1000), {segments: currentQueue.length});
}

async function replayCurrentSegment() {
  const segment = currentQueue[currentSegmentIndex] || currentQueue[0];
  if (segment) await playSegments([segment], {title: "Replay", event_type: "replay"});
}

$("replaySegment").addEventListener("click", replayCurrentSegment);

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
  refreshProgress();
});

$("recordBtn").addEventListener("click", async () => {
  if (recorder && recorder.state === "recording") {
    recorder.stop();
    setRecordButton(false);
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
  setRecordButton(true);
});

function setRecordButton(isRecording) {
  $("recordBtn").innerHTML = isRecording ? '<span aria-hidden="true">■</span>' : '<span aria-hidden="true">●</span>';
  $("recordBtn").classList.toggle("recording", isRecording);
  $("recordBtn").setAttribute("aria-label", isRecording ? "Stop recording" : "Record");
}

$("startDaily").addEventListener("click", () => startDaily());
document.querySelectorAll("[data-topic]").forEach((button) => {
  button.addEventListener("click", () => startDaily(button.dataset.topic));
});

async function startDaily(topic = "daily life") {
  $("dailyOutput").replaceChildren(card("<strong>Building...</strong><p>Making your morning Spanish session.</p>"));
  const data = await (await api("/api/daily-session", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({topic, level: $("storyLevel").value || "beginner", length: "short", tense: "present"})
  })).json();
  currentStory = data.story;
  renderDaily(data);
  renderStory(currentStory);
  refreshProgress();
}

function renderDaily(data) {
  const cards = (data.due_cards || []).map((item) => `<span class="chip">${item.spanish} = ${item.english}</span>`).join("");
  $("dailyOutput").replaceChildren(card(`
    <div class="split-head">
      <div><strong>${data.story.title}</strong><p>${data.coach_prompt}</p></div>
      <button class="primary icon-button" id="dailyPlay" title="Play daily session" aria-label="Play daily session">▶</button>
    </div>
    <div class="chips">${cards || '<span class="chip">fresh story vocab ready</span>'}</div>
    <div class="actions">
      <button class="icon-button" id="dailySpeak" title="Pronunciation check" aria-label="Pronunciation check">🎙</button>
      <button class="icon-button" id="dailyStar" title="Favorite" aria-label="Favorite">★</button>
      <button class="icon-button" id="dailyStoryTab" title="Open story" aria-label="Open story">▤</button>
    </div>
    <p id="pronunciationResult" class="muted"></p>`));
  $("dailyPlay").addEventListener("click", () => playSegments(queueFromStory("sentence"), {title: "Daily", event_type: "daily_playback", item_type: "story", item_id: currentStory.id}));
  $("dailySpeak").addEventListener("click", pronunciationCheck);
  $("dailyStar").addEventListener("click", () => favoriteCurrentStory());
  $("dailyStoryTab").addEventListener("click", () => setActiveTab("stories"));
}

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
  renderStory(currentStory);
  refreshProgress();
});

$("playStory").addEventListener("click", async () => {
  await playSegments(queueFromStory("sentence"), {title: "Story", event_type: "story_playback", item_type: "story", item_id: currentStory?.id || ""});
});

$("favoriteStory").addEventListener("click", favoriteCurrentStory);

async function favoriteCurrentStory() {
  if (!currentStory) return;
  await api("/api/favorites", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({item_type: "story", item_id: currentStory.id, label: currentStory.title, payload: {topic: currentStory.topic, level: currentStory.level}})
  });
  refreshProgress();
}

async function pronunciationCheck() {
  if (!currentStory) return;
  const target = (currentStory.listening_plan?.sentence_loop || [])[0]?.spanish || currentStory.spanish_text.split(".")[0];
  updateQueue("Say this", {text: target});
  const stream = await navigator.mediaDevices.getUserMedia({audio: true});
  chunks = [];
  const localRecorder = new MediaRecorder(stream);
  localRecorder.ondataavailable = (event) => chunks.push(event.data);
  localRecorder.onstop = async () => {
    const blob = new Blob(chunks, {type: "audio/webm"});
    const form = new FormData();
    form.append("file", blob, "speech.webm");
    const transcript = await (await api("/api/audio/transcribe", {method: "POST", body: form})).json();
    const score = await (await api("/api/pronunciation", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({target, spoken: transcript.text || ""})
    })).json();
    $("pronunciationResult").textContent = `${score.score}% · missing: ${(score.missing || []).join(", ") || "none"}`;
    stream.getTracks().forEach((track) => track.stop());
    refreshProgress();
  };
  localRecorder.start();
  setTimeout(() => localRecorder.state === "recording" && localRecorder.stop(), 4200);
}

$("playLoop").addEventListener("click", async () => {
  const segments = $("loopText").value.split(/\n+/).map((line, index) => {
    const text = line.trim();
    return text ? {text, lang: index % 3 === 1 ? "en-us" : "es"} : null;
  }).filter(Boolean);
  await playSegments(segments, {title: "Loop", event_type: "loop_playback"});
});

$("addVocab").addEventListener("click", async () => {
  const data = await (await api("/api/vocab", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({spanish: $("vocabSpanish").value, english: $("vocabEnglish").value, example_sentence: $("vocabExample").value})
  })).json();
  $("vocabOutput").prepend(renderCard(data));
  refreshProgress();
});

$("loadDue").addEventListener("click", loadDueCards);

async function loadDueCards() {
  const data = await (await api("/api/vocab/due")).json();
  $("vocabOutput").replaceChildren(...data.map(renderCard));
}

function renderCard(item) {
  const el = card(`<strong class="spanish">${item.spanish}</strong><p>${item.english}</p><p class="muted">${item.example_sentence || ""}</p>`);
  ["again", "hard", "good", "easy"].forEach((rating) => {
    const b = document.createElement("button");
    const symbols = {again: "↺", hard: "−", good: "✓", easy: "★"};
    b.textContent = symbols[rating];
    b.title = rating;
    b.setAttribute("aria-label", rating);
    b.className = "review-button";
    b.addEventListener("click", async () => {
      await api(`/api/vocab/${item.id}/review`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({rating})});
      el.remove();
      refreshProgress();
    });
    el.appendChild(b);
  });
  return el;
}

function renderStory(story) {
  const vocab = (story.vocabulary || []).map((item) => `<span class="chip">${item.spanish} = ${item.english}</span>`).join("");
  const questions = (story.questions || []).map((q) => `<li>${q}</li>`).join("");
  const source = story.source ? `<p class="muted">Source: ${story.source}${story.generation_error ? " (" + story.generation_error + ")" : ""}</p>` : "";
  $("storyOutput").innerHTML = `
    <h2>${story.title}</h2>
    ${source}
    <p class="spanish">${story.spanish_text}</p>
    <p class="english">${story.english_text}</p>
    <div class="chips">${vocab}</div>
    <h3>Practice Questions</h3>
    <p class="muted">Answer these out loud after listening.</p>
    <ol>${questions}</ol>
    <div class="actions">
      <button data-play-mode="sentence" class="primary icon-button" title="Clause loop" aria-label="Clause loop">▶</button>
      <button data-play-mode="full" class="icon-button" title="Full story" aria-label="Full story">▸▸</button>
      <button data-play-mode="shadow" class="icon-button" title="Shadowing" aria-label="Shadowing">◌</button>
      <button data-play-mode="speak" class="icon-button" title="Pronunciation check" aria-label="Pronunciation check">🎙</button>
    </div>`;
  $("storyOutput").querySelectorAll("[data-play-mode]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (button.dataset.playMode === "speak") return pronunciationCheck();
      await playSegments(queueFromStory(button.dataset.playMode), {title: "Story", event_type: "story_playback", item_type: "story", item_id: story.id});
    });
  });
}

function normalizeSegments(segments) {
  return (segments || []).map((segment, index) => {
    if (typeof segment === "string") return {text: segment, lang: index % 3 === 1 ? "en-us" : "es"};
    return {
      text: segment.text || segment.spanish || segment.english || "",
      lang: segment.lang || (segment.english ? "en-us" : "es"),
      pause_seconds: segment.pause_seconds
    };
  }).filter((segment) => segment.text);
}

async function trackEvent(event_type, item_type = "", item_id = "", seconds = 0, payload = {}) {
  try {
    await api("/api/events", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({event_type, item_type, item_id, seconds, payload})
    });
    refreshProgress();
  } catch {}
}

function waitForAudioEnd(player) {
  return new Promise((resolve) => {
    player.onended = resolve;
    player.onerror = resolve;
  });
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function speakInBrowser(text, lang) {
  return new Promise((resolve) => {
    if (!window.speechSynthesis) {
      resolve();
      return;
    }
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = lang === "es" ? "es-ES" : "en-US";
    utterance.rate = lang === "es" ? 0.92 : 0.96;
    utterance.onend = resolve;
    utterance.onerror = resolve;
    window.speechSynthesis.speak(utterance);
  });
}

refreshHealth();
refreshProgress();

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/static/sw.js").catch(() => {});
}
