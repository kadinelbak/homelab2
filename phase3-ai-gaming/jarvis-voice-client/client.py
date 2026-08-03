#!/usr/bin/env python3
import argparse
import audioop
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import wave
from dataclasses import dataclass, field
from pathlib import Path

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
    wake_threshold: float = 0.99
    wake_consecutive_hits: int = 4
    wake_inference_framework: str = "onnx"
    wake_cooldown_seconds: float = 30.0
    post_turn_cooldown_seconds: float = 10.0
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
            record_max_seconds=float(os.environ.get("JARVIS_RECORD_MAX_SECONDS", cls.record_max_seconds)),
            record_start_timeout_seconds=float(os.environ.get("JARVIS_RECORD_START_TIMEOUT_SECONDS", cls.record_start_timeout_seconds)),
            record_min_seconds=float(os.environ.get("JARVIS_RECORD_MIN_SECONDS", cls.record_min_seconds)),
            record_silence_seconds=float(os.environ.get("JARVIS_RECORD_SILENCE_SECONDS", cls.record_silence_seconds)),
            record_rms_threshold=int(os.environ.get("JARVIS_RECORD_RMS_THRESHOLD", cls.record_rms_threshold)),
            tts_voice=os.environ.get("JARVIS_TTS_VOICE", cls.tts_voice),
        )


@dataclass
class VoiceTurn:
    transcript: str = ""
    response_text: str = ""
    approval_required: bool = False
    states: list[str] = field(default_factory=list)


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
        data = json.dumps({"text": text, "voice": self.config.tts_voice}).encode("utf-8")
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


class JarvisVoiceSession:
    def __init__(self, client, speaker):
        self.client = client
        self.speaker = speaker

    def speak(self, text):
        try:
            audio, content_type = self.client.synthesize(text)
            self.speaker.play_audio(audio, content_type)
            return True
        except Exception as exc:
            self.speaker.print_status(f"TTS unavailable: {exc}")
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
            return turn
        turn.states.append("transcribe")
        turn.transcript = self.client.transcribe(wav_bytes)
        if not turn.transcript:
            turn.response_text = "I did not catch that."
            self.speaker.print_jarvis(turn.response_text)
            self.speak(turn.response_text)
            turn.states.append("idle")
            return turn
        if hasattr(self.speaker, "print_user"):
            self.speaker.print_user(turn.transcript)
        turn.states.append("request")
        data = self.client.ask(turn.transcript)
        turn.response_text = data.get("text") or "Jarvis returned no response text."
        turn.approval_required = bool(data.get("approval_required"))
        turn.states.append("speak")
        self.speaker.print_jarvis(turn.response_text)
        self.speak(turn.response_text)
        turn.states.append("idle")
        return turn


class ConsoleSpeaker:
    def print_jarvis(self, text):
        print(f"Jarvis: {text}")

    def print_user(self, text):
        print(f"You: {text}")

    def print_status(self, text):
        print(text)

    def play_audio(self, audio_bytes, content_type):
        suffix = ".ogg" if "ogg" in (content_type or "") else ".audio"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(audio_bytes)
            path = tmp.name
        try:
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


def listen_for_wake(config):
    import numpy as np
    import sounddevice as sd
    import openwakeword
    from openwakeword.model import Model

    openwakeword.utils.download_models(model_names=[config.wake_phrase])
    model = Model(wakeword_models=[config.wake_phrase], inference_framework=config.wake_inference_framework)
    block_samples = 1280
    last_wake = 0.0
    consecutive_hits = 0
    with sd.RawInputStream(samplerate=config.sample_rate, channels=1, dtype="int16", blocksize=block_samples) as stream:
        while True:
            data, _ = stream.read(block_samples)
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
    client = JarvisChatClient(config)
    session = JarvisVoiceSession(client, ConsoleSpeaker())
    session.speaker.print_jarvis(config.greeting)
    session.speak(config.greeting)
    print("Listening to your request...")
    wav_bytes = record_until_silence(config)
    session.handle_recording(wav_bytes, greet=False)


def run_listen(config):
    client = JarvisChatClient(config)
    session = JarvisVoiceSession(client, ConsoleSpeaker())
    print(f"Listening for {config.wake_phrase}.")
    for score in listen_for_wake(config):
        print(f"Wake detected: {score:.2f}")
        session.speaker.print_jarvis(config.greeting)
        session.speak(config.greeting)
        print("Listening to your request...")
        wav_bytes = record_until_silence(config)
        session.handle_recording(wav_bytes, greet=False)
        time.sleep(config.post_turn_cooldown_seconds)


def diagnose(config):
    print("Jarvis voice client diagnostics")
    print(f"Chat URL: {config.chat_url}")
    print(f"Wake phrase/model: {config.wake_phrase}")
    print(f"Wake inference framework: {config.wake_inference_framework}")
    print(f"Wake threshold: {config.wake_threshold}")
    print(f"Wake consecutive hits: {config.wake_consecutive_hits}")
    print(f"Post-turn cooldown seconds: {config.post_turn_cooldown_seconds}")
    print(f"Sample rate: {config.sample_rate}")
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
    parser.add_argument("--diagnose", action="store_true", help="Check Jarvis Chat, audio devices, and wake model setup.")
    parser.add_argument("--env", default=".env", help="Path to local env config.")
    args = parser.parse_args()
    load_dotenv(Path(args.env))
    config = VoiceConfig.from_env()
    if args.diagnose:
        diagnose(config)
    elif args.listen:
        run_listen(config)
    else:
        run_once(config)


if __name__ == "__main__":
    main()
