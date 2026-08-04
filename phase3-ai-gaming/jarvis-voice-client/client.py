#!/usr/bin/env python3
import argparse
import audioop
import json
import logging
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import wave
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from urllib.parse import urlparse

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")


def load_dotenv(path):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


@dataclass
class VoiceConfig:
    chat_url: str = "http://100.79.132.39:18100"
    chat_token: str = ""
    wake_phrase: str = "hey_jarvis"
    greeting: str = "Hey Kad, what do you need?"
    sample_rate: int = 16000
    wake_threshold: float = 0.98
    wake_consecutive_hits: int = 4
    wake_inference_framework: str = "onnx"
    wake_cooldown_seconds: float = 30.0
    post_turn_cooldown_seconds: float = 10.0
    enable_wake_word: bool = True
    enable_push_to_talk: bool = True
    push_to_talk_hotkey: str = "ctrl+alt+j"
    suppress_wake_while_speaking: bool = True
    log_dir: str = "logs"
    tunnel_server: str = "kadin@100.79.132.39"
    tunnel_local_port: int = 18100
    tunnel_remote_port: int = 18100
    record_max_seconds: float = 18.0
    record_start_timeout_seconds: float = 5.0
    record_min_seconds: float = 1.0
    record_silence_seconds: float = 1.8
    record_rms_threshold: int = 450
    tts_voice: str = "af_heart"

    @classmethod
    def from_env(cls):
        return cls(
            chat_url=os.environ.get("JARVIS_CHAT_URL", cls.chat_url).rstrip("/"),
            chat_token=os.environ.get("JARVIS_CHAT_TOKEN", ""),
            wake_phrase=os.environ.get("JARVIS_WAKE_PHRASE", cls.wake_phrase),
            greeting=os.environ.get("JARVIS_GREETING", cls.greeting),
            sample_rate=int(os.environ.get("JARVIS_SAMPLE_RATE", cls.sample_rate)),
            wake_threshold=float(os.environ.get("JARVIS_WAKE_THRESHOLD", cls.wake_threshold)),
            wake_consecutive_hits=int(os.environ.get("JARVIS_WAKE_CONSECUTIVE_HITS", cls.wake_consecutive_hits)),
            wake_inference_framework=os.environ.get("JARVIS_WAKE_INFERENCE_FRAMEWORK", cls.wake_inference_framework),
            wake_cooldown_seconds=float(os.environ.get("JARVIS_WAKE_COOLDOWN_SECONDS", cls.wake_cooldown_seconds)),
            post_turn_cooldown_seconds=float(os.environ.get("JARVIS_POST_TURN_COOLDOWN_SECONDS", cls.post_turn_cooldown_seconds)),
            enable_wake_word=env_bool("JARVIS_ENABLE_WAKE_WORD", cls.enable_wake_word),
            enable_push_to_talk=env_bool("JARVIS_ENABLE_PUSH_TO_TALK", cls.enable_push_to_talk),
            push_to_talk_hotkey=os.environ.get("JARVIS_PUSH_TO_TALK_HOTKEY", cls.push_to_talk_hotkey),
            suppress_wake_while_speaking=env_bool("JARVIS_SUPPRESS_WAKE_WHILE_SPEAKING", cls.suppress_wake_while_speaking),
            log_dir=os.environ.get("JARVIS_LOG_DIR", cls.log_dir),
            tunnel_server=os.environ.get("JARVIS_TUNNEL_SERVER", cls.tunnel_server),
            tunnel_local_port=int(os.environ.get("JARVIS_TUNNEL_LOCAL_PORT", cls.tunnel_local_port)),
            tunnel_remote_port=int(os.environ.get("JARVIS_TUNNEL_REMOTE_PORT", cls.tunnel_remote_port)),
            record_max_seconds=float(os.environ.get("JARVIS_RECORD_MAX_SECONDS", cls.record_max_seconds)),
            record_start_timeout_seconds=float(os.environ.get("JARVIS_RECORD_START_TIMEOUT_SECONDS", cls.record_start_timeout_seconds)),
            record_min_seconds=float(os.environ.get("JARVIS_RECORD_MIN_SECONDS", cls.record_min_seconds)),
            record_silence_seconds=float(os.environ.get("JARVIS_RECORD_SILENCE_SECONDS", cls.record_silence_seconds)),
            record_rms_threshold=int(os.environ.get("JARVIS_RECORD_RMS_THRESHOLD", cls.record_rms_threshold)),
            tts_voice=os.environ.get("JARVIS_TTS_VOICE", cls.tts_voice),
        )


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return bool(default)
    return value.strip().lower() in {"1", "true", "yes", "on"}


class VoiceState(str, Enum):
    DISCONNECTED = "disconnected"
    LISTENING = "listening"
    RECORDING = "recording"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    PAUSED = "paused"
    ERROR = "error"


@dataclass
class VoiceTurn:
    transcript: str = ""
    response_text: str = ""
    approval_required: bool = False
    states: list[str] = field(default_factory=list)


def setup_logging(config):
    log_dir = Path(config.log_dir)
    if not log_dir.is_absolute():
        log_dir = Path.cwd() / log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(log_dir / "jarvis-voice-client.log"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    return log_dir


def normalized_query(text):
    return re.sub(r"[^a-z0-9 ]+", "", str(text or "").lower()).strip()


def easter_egg_response(text):
    if normalized_query(text) == "how fat is zach":
        return "Zach is running in full legendary mode today."
    return None


def display_time_from_iso(match):
    value = match.group(0)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    hour = parsed.hour % 12 or 12
    minute = f":{parsed.minute:02d}" if parsed.minute else ""
    suffix = "AM" if parsed.hour < 12 else "PM"
    return f"{hour}{minute} {suffix}"


def normalize_response_text(text):
    text = str(text or "").strip()
    text = re.sub(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:[+-]\d{2}:\d{2}|Z)?\b", display_time_from_iso, text)
    text = re.sub(r"\s*\|\s*", ", ", text)
    text = re.sub(r"\s*->\s*", " to ", text)
    text = re.sub(r"\n(?:Event ID|Task ID|Message ID|Document ID):\s*[A-Za-z0-9_.:-]+", "", text)
    text = re.sub(r"\b[A-Za-z ]+\s+<no-reply@accounts\.google\.com>", "Google Accounts", text)
    text = re.sub(r"\b[A-Za-z ]+\s+<noreply-accounts@google\.com>", "Google Accounts", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def encode_multipart(field_name, filename, content_type, data):
    boundary = "----jarvisvoice" + uuid.uuid4().hex
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode(),
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            data,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return body, f"multipart/form-data; boundary={boundary}"


class JarvisChatClient:
    def __init__(self, config):
        self.config = config

    def headers(self, content_type=None):
        headers = {}
        if content_type:
            headers["Content-Type"] = content_type
        if self.config.chat_token:
            headers["Authorization"] = f"Bearer {self.config.chat_token}"
        return headers

    def request_json(self, path, payload, timeout=180):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.config.chat_url + path,
            data=data,
            method="POST",
            headers=self.headers("application/json"),
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8") or "{}")

    def transcribe(self, wav_bytes):
        body, content_type = encode_multipart("audio", "request.wav", "audio/wav", wav_bytes)
        req = urllib.request.Request(
            self.config.chat_url + "/api/voice/transcribe",
            data=body,
            method="POST",
            headers=self.headers(content_type),
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as response:
                data = json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(body or "{}")
                detail = payload.get("error") or payload.get("message") or body
            except json.JSONDecodeError:
                detail = body or str(exc)
            raise RuntimeError(f"transcription_failed: {detail}") from exc
        if not data.get("ok"):
            raise RuntimeError(data.get("error") or "transcription_failed")
        return (data.get("text") or "").strip()

    def ask(self, text):
        return self.request_json(
            "/api/voice/request",
            {"text": text, "source": "wake-word-client", "inputs": {"client": "jarvis-voice-client"}},
            timeout=300,
        )

    def synthesize(self, text):
        data = json.dumps({"text": text, "voice": self.config.tts_voice, "format": "wav"}).encode("utf-8")
        req = urllib.request.Request(
            self.config.chat_url + "/api/voice/synthesize",
            data=data,
            method="POST",
            headers=self.headers("application/json"),
        )
        with urllib.request.urlopen(req, timeout=240) as response:
            return response.read(), response.headers.get("Content-Type", "audio/ogg")

    def health(self):
        req = urllib.request.Request(self.config.chat_url + "/health", headers=self.headers())
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8") or "{}")


class TunnelManager:
    def __init__(self, config):
        self.config = config
        parsed = urlparse(config.chat_url)
        self.host = parsed.hostname or "127.0.0.1"
        self.port = parsed.port or config.tunnel_local_port
        self.process = None

    def is_connected(self):
        try:
            with socket.create_connection((self.host, self.port), timeout=1.5):
                return True
        except OSError:
            return False

    def ensure(self):
        if self.is_connected():
            return True
        if self.host not in {"127.0.0.1", "localhost"}:
            return False
        args = [
            "ssh",
            "-N",
            "-L",
            f"{self.config.tunnel_local_port}:127.0.0.1:{self.config.tunnel_remote_port}",
            self.config.tunnel_server,
        ]
        try:
            self.process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            logging.warning("tunnel start failed: %s", exc)
            return False
        deadline = time.time() + 6
        while time.time() < deadline:
            if self.is_connected():
                return True
            time.sleep(0.25)
        return False

    def restart(self):
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
            except OSError:
                pass
        self.process = None
        return self.ensure()


class JarvisVoiceSession:
    def __init__(self, client, speaker, state_callback=None):
        self.client = client
        self.speaker = speaker
        self.state_callback = state_callback or (lambda state, message="": None)

    def set_state(self, state, message=""):
        self.state_callback(state, message)
        if message:
            logging.info("%s: %s", state.value if isinstance(state, VoiceState) else state, message)

    def speak(self, text):
        try:
            self.set_state(VoiceState.SPEAKING, text[:120])
            audio, content_type = self.client.synthesize(text)
            self.speaker.play_audio(audio, content_type)
            return True
        except Exception as exc:
            self.speaker.print_status(f"TTS unavailable: {exc}")
            self.set_state(VoiceState.ERROR, str(exc))
            return False

    def handle_recording(self, wav_bytes, greet=True):
        turn = VoiceTurn(states=["wake", "greet"])
        if greet:
            self.speaker.print_jarvis(self.client.config.greeting)
            self.speak(self.client.config.greeting)
        if not wav_bytes:
            turn.response_text = "I did not hear anything."
            self.speaker.print_jarvis(turn.response_text)
            self.speak(turn.response_text)
            turn.states.append("idle")
            self.set_state(VoiceState.LISTENING)
            return turn
        turn.states.append("transcribe")
        self.set_state(VoiceState.PROCESSING, "Transcribing")
        turn.transcript = self.client.transcribe(wav_bytes)
        if not turn.transcript:
            turn.response_text = "I did not catch that."
            self.speaker.print_jarvis(turn.response_text)
            self.speak(turn.response_text)
            turn.states.append("idle")
            self.set_state(VoiceState.LISTENING)
            return turn
        if hasattr(self.speaker, "print_user"):
            self.speaker.print_user(turn.transcript)
        logging.info("transcript: %s", turn.transcript)
        egg = easter_egg_response(turn.transcript)
        if egg:
            turn.response_text = egg
            turn.states.append("request")
            turn.states.append("speak")
            self.speaker.print_jarvis(turn.response_text)
            self.speak(turn.response_text)
            turn.states.append("idle")
            self.set_state(VoiceState.LISTENING)
            return turn
        turn.states.append("request")
        self.set_state(VoiceState.PROCESSING, "Asking Jarvis")
        data = self.client.ask(turn.transcript)
        turn.response_text = normalize_response_text(data.get("text") or "Jarvis returned no response text.")
        turn.approval_required = bool(data.get("approval_required"))
        turn.states.append("speak")
        self.speaker.print_jarvis(turn.response_text)
        self.speak(turn.response_text)
        turn.states.append("idle")
        self.set_state(VoiceState.LISTENING)
        return turn


class ConsoleSpeaker:
    def print_jarvis(self, text):
        print(f"Jarvis: {text}")

    def print_user(self, text):
        print(f"You: {text}")

    def print_status(self, text):
        print(text)

    def play_audio(self, audio_bytes, content_type):
        suffix = ".wav" if "wav" in (content_type or "") else ".ogg" if "ogg" in (content_type or "") else ".audio"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(audio_bytes)
            path = tmp.name
        try:
            if suffix == ".wav" and os.name == "nt":
                import winsound

                winsound.PlaySound(path, winsound.SND_FILENAME)
                return
            import pygame

            pygame.mixer.init()
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.05)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass


def wav_bytes_from_pcm(frames, sample_rate):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        path = tmp.name
    try:
        with wave.open(path, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(b"".join(frames))
        return Path(path).read_bytes()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def record_until_silence(config):
    import sounddevice as sd

    block_samples = int(config.sample_rate * 0.1)
    start_blocks = max(1, int(config.record_start_timeout_seconds / 0.1))
    min_voice_blocks = max(1, int(config.record_min_seconds / 0.1))
    silence_blocks_needed = max(1, int(config.record_silence_seconds / 0.1))
    max_blocks = max(1, int(config.record_max_seconds / 0.1))
    frames = []
    pre_voice_blocks = 0
    silent_blocks = 0
    voice_blocks = 0
    heard_speech = False
    with sd.RawInputStream(samplerate=config.sample_rate, channels=1, dtype="int16", blocksize=block_samples) as stream:
        for _ in range(max_blocks):
            data, _ = stream.read(block_samples)
            chunk = bytes(data)
            is_silent = audioop.rms(chunk, 2) < config.record_rms_threshold
            if not heard_speech and is_silent:
                pre_voice_blocks += 1
                if pre_voice_blocks >= start_blocks:
                    break
                continue
            heard_speech = True
            frames.append(chunk)
            if is_silent:
                silent_blocks += 1
                if voice_blocks >= min_voice_blocks and silent_blocks >= silence_blocks_needed:
                    break
            else:
                voice_blocks += 1
                silent_blocks = 0
    if not frames:
        return b""
    return wav_bytes_from_pcm(frames, config.sample_rate)


class VoiceController:
    def __init__(self, config, speaker=None, tunnel=None, recorder=None, client=None):
        self.config = config
        self.speaker = speaker or ConsoleSpeaker()
        self.tunnel = tunnel or TunnelManager(config)
        self.client = client or JarvisChatClient(config)
        self.session = JarvisVoiceSession(self.client, self.speaker, self.set_state)
        self.recorder = recorder or record_until_silence
        self.state = VoiceState.DISCONNECTED
        self.state_message = ""
        self.state_lock = threading.Lock()
        self.turn_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.paused = False
        self.suppress_until = 0.0
        self.on_state_change = None

    def set_state(self, state, message=""):
        with self.state_lock:
            self.state = state
            self.state_message = message
        if self.on_state_change:
            self.on_state_change(state, message)

    def should_accept_wake(self):
        if self.stop_event.is_set() or self.paused:
            return False
        if self.config.suppress_wake_while_speaking and self.state in {VoiceState.SPEAKING, VoiceState.RECORDING, VoiceState.PROCESSING}:
            return False
        return time.time() >= self.suppress_until

    def ensure_connected(self):
        if self.tunnel.ensure():
            self.set_state(VoiceState.LISTENING)
            return True
        self.set_state(VoiceState.DISCONNECTED, "Jarvis Chat tunnel unavailable")
        self.speaker.print_status("Jarvis Chat tunnel unavailable.")
        return False

    def restart_tunnel(self):
        self.set_state(VoiceState.DISCONNECTED, "Restarting tunnel")
        ok = self.tunnel.restart()
        self.set_state(VoiceState.LISTENING if ok else VoiceState.ERROR, "Tunnel restarted" if ok else "Tunnel restart failed")
        return ok

    def pause(self):
        self.paused = True
        self.set_state(VoiceState.PAUSED)

    def resume(self):
        self.paused = False
        self.set_state(VoiceState.LISTENING)

    def stop(self):
        self.stop_event.set()

    def record_turn(self, trigger="wake"):
        if not self.turn_lock.acquire(blocking=False):
            self.speaker.print_status("Jarvis is already handling a request.")
            return None
        try:
            return self._record_turn_locked(trigger)
        finally:
            self.turn_lock.release()

    def _record_turn_locked(self, trigger="wake"):
        if not self.ensure_connected():
            return None
        self.speaker.print_jarvis(self.config.greeting)
        self.session.speak(self.config.greeting)
        self.speaker.print_status("Listening to your request...")
        self.set_state(VoiceState.RECORDING, trigger)
        wav_bytes = self.recorder(self.config)
        turn = self.session.handle_recording(wav_bytes, greet=False)
        self.suppress_until = time.time() + self.config.post_turn_cooldown_seconds
        self.set_state(VoiceState.LISTENING)
        return turn

    def push_to_talk(self):
        if not self.config.enable_push_to_talk:
            self.speaker.print_status("Push-to-talk is disabled.")
            return None
        if self.paused:
            self.speaker.print_status("Jarvis is paused.")
            return None
        return self.record_turn("push-to-talk")

    def listen_forever(self):
        if not self.config.enable_wake_word:
            self.speaker.print_status("Wake word is disabled.")
            return
        self.ensure_connected()
        self.speaker.print_status(f"Listening for {self.config.wake_phrase}.")
        for score in listen_for_wake(config=self.config, should_listen=self.should_accept_wake):
            if self.stop_event.is_set():
                break
            self.speaker.print_status(f"Wake detected: {score:.2f}")
            self.record_turn("wake")


def listen_for_wake(config, should_listen=None):
    import numpy as np
    import sounddevice as sd
    import openwakeword
    from openwakeword.model import Model

    should_listen = should_listen or (lambda: True)
    openwakeword.utils.download_models(model_names=[config.wake_phrase])
    model = Model(wakeword_models=[config.wake_phrase], inference_framework=config.wake_inference_framework)
    block_samples = 1280
    last_wake = 0.0
    consecutive_hits = 0
    with sd.RawInputStream(samplerate=config.sample_rate, channels=1, dtype="int16", blocksize=block_samples) as stream:
        while True:
            data, _ = stream.read(block_samples)
            if not should_listen():
                consecutive_hits = 0
                time.sleep(0.05)
                continue
            audio = np.frombuffer(bytes(data), dtype=np.int16)
            prediction = model.predict(audio)
            score = max(float(value) for value in prediction.values()) if prediction else 0.0
            now = time.time()
            if score >= config.wake_threshold:
                consecutive_hits += 1
            else:
                consecutive_hits = 0
            if consecutive_hits >= config.wake_consecutive_hits and now - last_wake > config.wake_cooldown_seconds:
                last_wake = now
                consecutive_hits = 0
                yield score


def run_once(config):
    controller = VoiceController(config)
    controller.record_turn("once")


def run_listen(config):
    VoiceController(config).listen_forever()


def run_push_to_talk(config):
    VoiceController(config).push_to_talk()


def tray_image(state):
    from PIL import Image, ImageDraw

    colors = {
        VoiceState.DISCONNECTED: "#666666",
        VoiceState.LISTENING: "#2ea043",
        VoiceState.RECORDING: "#d29922",
        VoiceState.PROCESSING: "#58a6ff",
        VoiceState.SPEAKING: "#a371f7",
        VoiceState.PAUSED: "#8b949e",
        VoiceState.ERROR: "#f85149",
    }
    image = Image.new("RGB", (64, 64), "#0d1117")
    draw = ImageDraw.Draw(image)
    draw.ellipse((12, 12, 52, 52), fill=colors.get(state, "#666666"))
    draw.ellipse((25, 25, 39, 39), fill="#0d1117")
    return image


def run_threaded(name, target):
    thread = threading.Thread(target=target, name=name, daemon=True)
    thread.start()
    return thread


def run_tray(config):
    try:
        import pystray
    except ImportError as exc:
        raise RuntimeError("Tray mode needs pystray and Pillow. Run: pip install -r requirements.txt") from exc

    log_dir = setup_logging(config)
    controller = VoiceController(config)
    icon = pystray.Icon("Jarvis", tray_image(controller.state), "Jarvis")

    def refresh(state=None, message=""):
        state = state or controller.state
        icon.icon = tray_image(state)
        icon.title = f"Jarvis: {state.value}"
        if message:
            logging.info("tray: %s", message)
        try:
            icon.update_menu()
        except Exception:
            pass

    controller.on_state_change = refresh

    def threaded_action(action):
        return lambda *_: run_threaded(f"jarvis-{action.__name__}", action)

    def pause_resume(*_):
        if controller.paused:
            controller.resume()
        else:
            controller.pause()

    def diagnostics(*_):
        def run():
            try:
                diagnose(config)
            except Exception as exc:
                logging.exception("diagnostics failed: %s", exc)
                controller.set_state(VoiceState.ERROR, str(exc))

        run_threaded("jarvis-diagnostics", run)

    def open_logs(*_):
        path = log_dir / "jarvis-voice-client.log"
        path.touch(exist_ok=True)
        if os.name == "nt":
            os.startfile(str(path))
        else:
            controller.speaker.print_status(str(path))

    def quit_app(*_):
        controller.stop()
        icon.stop()

    def status_text(_):
        return f"Status: {controller.state.value}"

    def pause_text(_):
        return "Resume" if controller.paused else "Pause"

    icon.menu = pystray.Menu(
        pystray.MenuItem(status_text, None, enabled=False),
        pystray.MenuItem("Push to talk", threaded_action(controller.push_to_talk), enabled=lambda _: config.enable_push_to_talk),
        pystray.MenuItem(pause_text, pause_resume),
        pystray.MenuItem("Restart tunnel", threaded_action(controller.restart_tunnel)),
        pystray.MenuItem("Run diagnostics", diagnostics),
        pystray.MenuItem("Open logs", open_logs),
        pystray.MenuItem("Quit", quit_app),
    )

    if config.enable_push_to_talk:
        try:
            import keyboard

            keyboard.add_hotkey(config.push_to_talk_hotkey, lambda: run_threaded("jarvis-push-to-talk", controller.push_to_talk))
            logging.info("registered hotkey %s", config.push_to_talk_hotkey)
        except Exception as exc:
            logging.warning("push-to-talk hotkey unavailable: %s", exc)
            controller.speaker.print_status(f"Push-to-talk hotkey unavailable: {exc}")

    if config.enable_wake_word:
        run_threaded("jarvis-wake-listener", controller.listen_forever)
    else:
        controller.ensure_connected()
    refresh()
    icon.run()


def diagnose(config):
    print("Jarvis voice client diagnostics")
    print(f"Chat URL: {config.chat_url}")
    print(f"Tunnel target: {config.tunnel_local_port}:127.0.0.1:{config.tunnel_remote_port} via {config.tunnel_server}")
    print(f"Wake word enabled: {config.enable_wake_word}")
    print(f"Push-to-talk enabled: {config.enable_push_to_talk}")
    print(f"Push-to-talk hotkey: {config.push_to_talk_hotkey}")
    print(f"Wake phrase/model: {config.wake_phrase}")
    print(f"Wake inference framework: {config.wake_inference_framework}")
    print(f"Wake threshold: {config.wake_threshold}")
    print(f"Wake consecutive hits: {config.wake_consecutive_hits}")
    print(f"Post-turn cooldown seconds: {config.post_turn_cooldown_seconds}")
    print(f"Sample rate: {config.sample_rate}")
    try:
        tunnel = TunnelManager(config)
        print(f"Tunnel/local chat port: connected={tunnel.is_connected()}")
    except Exception as exc:
        print(f"Tunnel/local chat port: failed: {exc}")
    try:
        health = JarvisChatClient(config).health()
        print(f"Jarvis Chat: ok={health.get('ok')} auth_required={health.get('auth_required')}")
    except Exception as exc:
        print(f"Jarvis Chat: failed: {exc}")
    try:
        import sounddevice as sd

        print("Audio devices:")
        print(sd.query_devices())
    except Exception as exc:
        print(f"Audio devices: failed: {exc}")
    try:
        import openwakeword
        from openwakeword.model import Model

        openwakeword.utils.download_models(model_names=[config.wake_phrase])
        model = Model(wakeword_models=[config.wake_phrase], inference_framework=config.wake_inference_framework)
        print(f"Wake model loaded: {list(getattr(model, 'models', {}).keys()) or config.wake_phrase}")
    except Exception as exc:
        print(f"Wake model: failed: {exc}")
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Record one request without wake-word listening.")
    parser.add_argument("--listen", action="store_true", help="Listen continuously for the wake phrase.")
    parser.add_argument("--push-to-talk", action="store_true", help="Record one request through the push-to-talk path.")
    parser.add_argument("--tray", action="store_true", help="Run the Windows tray app.")
    parser.add_argument("--diagnose", action="store_true", help="Check Jarvis Chat, audio devices, and wake model setup.")
    parser.add_argument("--env", default=".env", help="Path to local env config.")
    args = parser.parse_args()
    load_dotenv(Path(args.env))
    config = VoiceConfig.from_env()
    if args.diagnose:
        diagnose(config)
    elif args.tray:
        run_tray(config)
    elif args.push_to_talk:
        run_push_to_talk(config)
    elif args.listen:
        run_listen(config)
    else:
        run_once(config)


if __name__ == "__main__":
    main()
