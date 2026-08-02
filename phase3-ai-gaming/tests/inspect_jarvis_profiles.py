#!/usr/bin/env python3
import json
import os
import urllib.request


profiles = {}
for name, prefix in (("fast_70b", "JARVIS_FAST_LLM"), ("deep_120b", "JARVIS_DEEP_LLM")):
    base_url = os.environ.get(prefix + "_BASE_URL", "").rstrip("/")
    api_key = os.environ.get(prefix + "_API_KEY", "")
    profiles[name] = {
        "provider": os.environ.get(prefix + "_PROVIDER", ""),
        "model": os.environ.get(prefix + "_MODEL", ""),
        "base_url": base_url,
        "configured": bool(base_url and api_key),
    }
    if base_url and api_key:
        request = urllib.request.Request(base_url + "/models", headers={"Authorization": f"Bearer {api_key}"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.load(response)
            profiles[name]["available_relevant_models"] = sorted(
                item.get("id") for item in payload.get("data", [])
                if item.get("id") and any(term in item["id"].lower() for term in ("llama", "nemotron"))
            )
        except Exception as exc:
            profiles[name]["models_error"] = str(exc)[:200]
        if os.environ.get("TEST_TOOL_CALLING") == "1":
            body = json.dumps({
                "model": profiles[name]["model"],
                "messages": [{"role": "user", "content": "Call jarvis_test_tool with value ready. Do not answer normally."}],
                "tools": [{
                    "type": "function",
                    "function": {
                        "name": "jarvis_test_tool",
                        "description": "A harmless tool-call format test.",
                        "parameters": {
                            "type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"],
                        },
                    },
                }],
                "tool_choice": "auto",
                "temperature": 0,
                "max_tokens": 200,
            }).encode("utf-8")
            request = urllib.request.Request(
                base_url + "/chat/completions", data=body, method="POST",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    payload = json.load(response)
                message = (payload.get("choices") or [{}])[0].get("message") or {}
                profiles[name]["native_tool_call"] = {
                    "supported": bool(message.get("tool_calls")),
                    "finish_reason": (payload.get("choices") or [{}])[0].get("finish_reason"),
                    "tool_names": [call.get("function", {}).get("name") for call in message.get("tool_calls") or []],
                }
            except Exception as exc:
                profiles[name]["native_tool_call"] = {"supported": False, "error": str(exc)[:200]}

print(json.dumps(profiles, indent=2, sort_keys=True))
