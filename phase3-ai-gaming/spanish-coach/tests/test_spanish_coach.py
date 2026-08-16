import importlib
import os
import pathlib
import sys

from fastapi.testclient import TestClient


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_app(tmp_path):
    os.environ["SPANISH_COACH_DATABASE_URL"] = f"sqlite:///{tmp_path / 'test.sqlite3'}"
    os.environ["SPANISH_COACH_TOKEN"] = "secret"
    os.environ["SPANISH_COACH_LLM_BASE_URL"] = ""
    if "app" in sys.modules:
        del sys.modules["app"]
    module = importlib.import_module("app")
    module.init_db()
    return module, TestClient(module.app)


def auth():
    return {"Authorization": "Bearer secret"}


def test_token_auth_rejects_invalid_requests(tmp_path):
    _, client = load_app(tmp_path)
    response = client.post("/api/chat", json={"message": "hola"})
    assert response.status_code == 401


def test_chat_uses_spanish_prompt_and_saves_vocab(tmp_path):
    module, client = load_app(tmp_path)
    messages = module.tutor_prompt("I want coffee")
    assert "Spanish" in messages[0]["content"]
    response = client.post("/api/chat", headers=auth(), json={"message": "I want coffee"})
    assert response.status_code == 200
    data = response.json()
    assert data["reply"]
    assert data["vocab"][0]["spanish"] == "aprender"


def test_vocab_review_updates_schedule(tmp_path):
    _, client = load_app(tmp_path)
    created = client.post("/api/vocab", headers=auth(), json={"spanish": "pan", "english": "bread"}).json()
    reviewed = client.post(f"/api/vocab/{created['id']}/review", headers=auth(), json={"rating": "good"}).json()
    assert reviewed["repetitions"] == 1
    assert reviewed["interval_days"] == 1


def test_story_generation_fallback_has_listening_plan_and_vocab(tmp_path):
    module, client = load_app(tmp_path)
    prompt = module.story_prompt(module.StoryCreate(topic="cafe"))
    assert "Spanish" in prompt[0]["content"]
    response = client.post("/api/stories", headers=auth(), json={"topic": "cafe", "level": "beginner"})
    assert response.status_code == 200
    data = response.json()
    assert data["spanish_text"]
    assert data["listening_plan"]["sentence_loop"][0]["sequence"][0]["lang"] == "es"
    assert data["listening_plan"]["sentence_loop"][0]["sequence"][1]["lang"] == "en-us"
    assert data["vocabulary"]


def test_vocab_deduplicates_across_sources(tmp_path):
    module, _ = load_app(tmp_path)
    cleaned = module.clean_vocab([
        {"spanish": "pan", "english": "bread"},
        {"spanish": "Pan", "english": "bread"},
        {"spanish": "", "english": "blank"},
    ])
    assert len(cleaned) == 1


def test_tts_posts_segments_to_worker(tmp_path, monkeypatch):
    module, client = load_app(tmp_path)

    class FakeResponse:
        content = b"audio"
        headers = {"content-type": "audio/ogg"}

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, headers=None, json=None, files=None, data=None):
            assert json["text"] == "hola"
            assert json["lang"] == "es"
            return FakeResponse()

    monkeypatch.setattr(module.httpx, "AsyncClient", FakeClient)
    response = client.post("/api/tts", headers=auth(), json={"segments": [{"text": "hola", "lang": "es"}]})
    assert response.status_code == 200
    assert response.content == b"audio"
