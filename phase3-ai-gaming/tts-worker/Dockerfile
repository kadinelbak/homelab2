FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates espeak-ng ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir piper-tts==1.2.0 kokoro-onnx==0.4.9 soundfile==0.13.1

ENV JARVIS_PIPER_MODEL_DIR=/models/piper \
    JARVIS_PIPER_MODEL=en_US-lessac-high.onnx \
    JARVIS_KOKORO_MODEL_DIR=/models/kokoro \
    JARVIS_KOKORO_MODEL=kokoro-v1.0.onnx \
    JARVIS_KOKORO_VOICES=voices-v1.0.bin

RUN mkdir -p /models/piper \
    && python - <<'PY'
from pathlib import Path
import urllib.request

base = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/high"
model_dir = Path("/models/piper")
for name in ("en_US-lessac-high.onnx", "en_US-lessac-high.onnx.json"):
    target = model_dir / name
    urllib.request.urlretrieve(f"{base}/{name}", target)
PY

RUN mkdir -p /models/kokoro \
    && python - <<'PY'
from pathlib import Path
import urllib.request

base = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
model_dir = Path("/models/kokoro")
for name in ("kokoro-v1.0.onnx", "voices-v1.0.bin"):
    target = model_dir / name
    urllib.request.urlretrieve(f"{base}/{name}", target)
PY

WORKDIR /app
COPY app.py /app/app.py

EXPOSE 8101
CMD ["python", "/app/app.py"]
