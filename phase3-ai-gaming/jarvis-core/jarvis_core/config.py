import os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    token: str = ""
    database_url: str = "sqlite:///./jarvis-core-dev.db"
    redis_url: str = "redis://localhost:6379/0"
    port: int = 8097
    user_timezone: str = "America/New_York"
    media_pipeline_url: str = "http://media-creation-api:18110"
    google_tools_url: str = "http://google-tools-worker:18200"
    google_tools_token: str = ""
    codex_worker_url: str = "http://codex-worker:18300"
    codex_worker_token: str = ""
    homelab_public_base_url: str = "http://kadin-main-sys.tail00cf0e.ts.net"
    media_automation_internal_base_url: str = "http://gluetun"
    pihole_url: str = "http://100.79.132.39:8053/admin/"
    calendar_provider: str = "google"
    calendar_allow_simulated_fallback: bool = False
    dev_auth_user: str = "local-user"
    fast_llm_provider: str = os.environ.get("JARVIS_FAST_LLM_PROVIDER", "external_openai_compatible")
    fast_llm_model: str = os.environ.get("JARVIS_FAST_LLM_MODEL", "llama-3.1-70b-instruct")
    fast_llm_base_url: str = os.environ.get("JARVIS_FAST_LLM_BASE_URL", "")
    fast_llm_api_key: str = os.environ.get("JARVIS_FAST_LLM_API_KEY", "")
    deep_llm_provider: str = os.environ.get("JARVIS_DEEP_LLM_PROVIDER", "external_openai_compatible")
    deep_llm_model: str = os.environ.get("JARVIS_DEEP_LLM_MODEL", "nemotron-3-super-120b-a12b")
    deep_llm_base_url: str = os.environ.get("JARVIS_DEEP_LLM_BASE_URL", "")
    deep_llm_api_key: str = os.environ.get("JARVIS_DEEP_LLM_API_KEY", "")
    vision_llm_provider: str = os.environ.get("JARVIS_VISION_LLM_PROVIDER", "external_openai_compatible")
    vision_llm_model: str = os.environ.get("JARVIS_VISION_LLM_MODEL", "gemma-4-31b-it")
    vision_llm_base_url: str = os.environ.get("JARVIS_VISION_LLM_BASE_URL", "")
    vision_llm_api_key: str = os.environ.get("JARVIS_VISION_LLM_API_KEY", "")
    llm_timeout_seconds: int = int(os.environ.get("JARVIS_LLM_TIMEOUT_SECONDS", "90"))
    automation_runner_enabled: bool = True
    automation_runner_interval_seconds: int = 60

    class Config:
        env_prefix = "JARVIS_CORE_"


settings = Settings()
