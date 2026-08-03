# Jarvis Voice Client

Windows laptop voice client for Jarvis.

## Setup

```powershell
cd phase3-ai-gaming\jarvis-voice-client
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item config.example.env .env
.\start_tunnel.ps1
python client.py --diagnose
python client.py --once
```

Use `python client.py --listen` for continuous wake-word mode. Run it as a separate command, not appended to `--once`.

```powershell
python client.py --listen
```

The client listens locally for `hey_jarvis`, records the request, sends audio to Jarvis Chat for Whisper transcription, sends the transcript to Jarvis Core, and plays the Kokoro response.

Jarvis Chat remains the only server-facing endpoint the laptop needs.

The default config expects an SSH tunnel from laptop `127.0.0.1:18100` to server `127.0.0.1:18100`. Use `.\start_tunnel.ps1` before running the client, or change `JARVIS_CHAT_URL` if Jarvis Chat is intentionally exposed another way.

## Start at login

After `--once` and `--listen` behave well:

```powershell
.\install_startup.ps1
```

Remove it with:

```powershell
.\uninstall_startup.ps1
```
