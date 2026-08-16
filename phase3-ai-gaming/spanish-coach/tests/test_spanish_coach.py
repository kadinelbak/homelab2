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
    response = client.post("/api/stories", headers=auth(), json={"topic": "Family", "level": "intermediate", "length": "medium"})
    assert response.status_code == 200
    data = response.json()
    assert data["spanish_text"]
    assert data["source"] == "fallback"
    assert "ñ" in data["spanish_text"]
    assert len(data["listening_plan"]["sentence_loop"]) >= 10
    assert data["listening_plan"]["sentence_loop"][0]["sequence"][0]["lang"] == "es"
    assert data["listening_plan"]["sentence_loop"][0]["sequence"][1]["lang"] == "en-us"
    assert data["vocabulary"]


def test_story_length_and_level_change_fallback_size(tmp_path):
    module, _ = load_app(tmp_path)
    short = module.fallback_story(module.StoryCreate(topic="Family", level="beginner", length="short"))
    long = module.fallback_story(module.StoryCreate(topic="Family", level="advanced", length="long"))
    assert len(long["spanish_text"].split()) > len(short["spanish_text"].split()) * 2
    assert "mañana" in long["spanish_text"]


def test_listening_plan_uses_clause_sized_story_chunks(tmp_path):
    module, _ = load_app(tmp_path)
    plan = module.listening_plan(
        "La abuela quiere visitar el mercado, pero el hermano menor sueña con ir al parque.",
        "The grandmother wants to visit the market, but the younger brother dreams of going to the park.",
    )
    assert len(plan["sentence_loop"]) == 2
    assert plan["sentence_loop"][0]["spanish"] == "La abuela quiere visitar el mercado"
    assert plan["sentence_loop"][1]["spanish"].startswith("pero el hermano menor")
    assert plan["sentence_loop"][0]["english"] == "The grandmother wants to visit the market"
    assert plan["sentence_loop"][0]["sequence"][0]["lang"] == "es"
    assert plan["sentence_loop"][0]["sequence"][1]["lang"] == "en-us"
    assert plan["shadowing"][0]["pause_seconds"] == 2.2


def test_sentence_split_handles_closing_quotes(tmp_path):
    module, _ = load_app(tmp_path)
    sentences = module.split_sentences('Her dad says, "First we buy fruit." The mom smiles.')
    assert sentences == ['Her dad says, "First we buy fruit."', "The mom smiles."]


def test_vocab_deduplicates_across_sources(tmp_path):
    module, _ = load_app(tmp_path)
    cleaned = module.clean_vocab([
        {"spanish": "español", "english": "Spanish"},
        {"spanish": "Español", "english": "Spanish"},
        {"spanish": "", "english": "blank"},
    ])
    assert len(cleaned) == 1
    assert cleaned[0]["spanish"] == "español"


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
