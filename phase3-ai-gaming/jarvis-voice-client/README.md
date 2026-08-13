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

Use tray mode for normal laptop use. It starts the local SSH tunnel, listens for `hey_jarvis`, and keeps `Ctrl+Alt+J` as a push-to-talk fallback.

```powershell
python client.py --tray
```

Use `python client.py --listen` for console wake-word debugging. Run it as a separate command, not appended to `--once`.

```powershell
python client.py --listen
```

Use `python client.py --push-to-talk` to test one push-to-talk turn from the console.

The client listens locally for `hey_jarvis`, records the request, sends audio to Jarvis Chat for Whisper transcription, sends the transcript to Jarvis Core, and plays the Kokoro response.

Jarvis Chat remains the only server-facing endpoint the laptop needs. Jarvis Chat routes Phase 4 voice requests such as daily brief, task capture, portfolio evidence capture, and homelab maintenance notes to Jarvis Core internally, so the laptop does not need a separate Jarvis Core tunnel.

The default config expects an SSH tunnel from laptop `127.0.0.1:18100` to server `127.0.0.1:18100`. Tray mode starts and reconnects that tunnel automatically. You can still use `.\start_tunnel.ps1` before console debugging, or change `JARVIS_CHAT_URL` if Jarvis Chat is intentionally exposed another way.

Tray menu actions:

- Pause or resume wake listening
- Push to talk
- Restart tunnel
- Run diagnostics
- Open logs
- Quit

Useful config:

```powershell
JARVIS_ENABLE_WAKE_WORD=true
JARVIS_ENABLE_PUSH_TO_TALK=true
JARVIS_PUSH_TO_TALK_HOTKEY=ctrl+alt+j
JARVIS_SUPPRESS_WAKE_WHILE_SPEAKING=true
JARVIS_LOG_DIR=logs
```

## Start at login

After `--once` and `--tray` behave well:

```powershell
.\install_startup.ps1
```

The installer prefers a Windows Scheduled Task and falls back to a user Startup-folder shortcut if task registration is blocked.

Remove it with:

```powershell
.\uninstall_startup.ps1
```
