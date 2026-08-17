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


def test_ten_minute_story_length_expands_fallback_and_prompt(tmp_path):
    module, client = load_app(tmp_path)
    shape = module.story_shape("beginner", "ten_minutes")
    assert shape["sentences"] >= 40
    assert shape["minutes"] == 10
    prompt = module.story_prompt(module.StoryCreate(topic="travel", length="ten_minutes"))
    assert "10 minutes" in prompt[1]["content"]
    story = module.fallback_story(module.StoryCreate(topic="travel", length="ten_minutes"))
    assert len(module.split_sentences(story["spanish_text"])) >= 40
    response = client.post("/api/stories", headers=auth(), json={"topic": "travel", "level": "beginner", "length": "ten_minutes"})
    assert response.status_code == 200
    data = response.json()
    assert len(module.split_sentences(data["spanish_text"])) >= 40
    assert len(data["listening_plan"]["sentence_loop"]) >= 40


def test_story_prompt_includes_freshness_seed(tmp_path):
    module, _ = load_app(tmp_path)
    prompt = module.story_prompt(module.StoryCreate(topic="travel"))
    assert "Freshness seed:" in prompt[1]["content"]
    assert "different protagonist" in prompt[1]["content"]


def test_fallback_story_varies_by_topic_category(tmp_path, monkeypatch):
    module, _ = load_app(tmp_path)

    class FakeUuid:
        int = 0
        hex = "abc123"

    monkeypatch.setattr(module.uuid, "uuid4", lambda: FakeUuid())
    travel = module.fallback_story(module.StoryCreate(topic="travel"))
    food = module.fallback_story(module.StoryCreate(topic="food"))
    work = module.fallback_story(module.StoryCreate(topic="work"))
    assert "mapa" in travel["spanish_text"].lower()
    assert "receta" in food["spanish_text"].lower()
    assert "reunión" in work["spanish_text"].lower()
    assert len({travel["title"], food["title"], work["title"]}) == 3


def test_family_fallback_has_multiple_plot_shapes(tmp_path, monkeypatch):
    module, _ = load_app(tmp_path)

    class FakeUuid:
        hex = "abc123"

    values = [0, 1, 2]

    def fake_uuid4():
        item = FakeUuid()
        item.int = values.pop(0)
        return item

    monkeypatch.setattr(module.uuid, "uuid4", fake_uuid4)
    titles = [module.fallback_story(module.StoryCreate(topic="family"))["title"] for _ in range(3)]
    assert any("llamada" in title.lower() for title in titles)
    assert any("cumpleaños" in title.lower() for title in titles)
    assert len(set(titles)) == 3


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


def test_listening_plan_does_not_split_scene_label_colons(tmp_path):
    module, _ = load_app(tmp_path)
    plan = module.listening_plan(
        "Primera escena 2: Lucía llega a una estación grande con una maleta roja.",
        "First scene 2: Lucía arrives at a large station with a red suitcase.",
    )
    assert len(plan["sentence_loop"]) == 1
    assert plan["sentence_loop"][0]["spanish"].startswith("Primera escena 2:")
    assert plan["sentence_loop"][0]["english"].startswith("First scene 2:")


def test_listening_plan_merges_short_intro_clause(tmp_path):
    module, _ = load_app(tmp_path)
    plan = module.listening_plan(
        "En el andén, conoce a una estudiante que también viaja sola.",
        "On the platform, she meets a student who is also traveling alone.",
    )
    assert len(plan["sentence_loop"]) == 1
    assert plan["sentence_loop"][0]["spanish"] == "En el andén conoce a una estudiante que también viaja sola."
    assert plan["sentence_loop"][0]["english"] == "On the platform she meets a student who is also traveling alone."


def test_ten_minute_fallback_does_not_prefix_repeated_sentences_with_colons(tmp_path):
    module, _ = load_app(tmp_path)
    story = module.fallback_story(module.StoryCreate(topic="travel", length="ten_minutes"))
    sentences = module.split_sentences(story["spanish_text"])
    assert len(sentences) >= 40
    assert not any(sentence.startswith(("Primera escena", "Segunda escena", "Tercera escena", "Cuarta escena")) and ":" in sentence for sentence in sentences)


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


def test_daily_session_returns_story_vocab_and_progress(tmp_path):
    _, client = load_app(tmp_path)
    response = client.post("/api/daily-session", headers=auth(), json={"topic": "food", "level": "beginner", "length": "short"})
    assert response.status_code == 200
    data = response.json()
    assert data["kind"] == "morning_spanish"
    assert data["story"]["spanish_text"]
    assert data["due_cards"]
    assert data["stats"]["today_events"] >= 1
    assert "Spanish follow-up is ready" in data["summary"]


def test_favorites_progress_and_pronunciation_feedback(tmp_path):
    _, client = load_app(tmp_path)
    favorite = client.post("/api/favorites", headers=auth(), json={"item_type": "phrase", "item_id": "hola", "label": "hola"}).json()
    assert favorite["label"] == "hola"
    score = client.post("/api/pronunciation", headers=auth(), json={"target": "mañana voy al mercado", "spoken": "manana voy mercado"}).json()
    assert score["score"] < 100
    progress = client.get("/api/progress", headers=auth()).json()
    assert progress["favorites"] == 1
    assert progress["today_events"] >= 1


def test_jarvis_morning_spanish_summary(tmp_path):
    _, client = load_app(tmp_path)
    response = client.get("/api/jarvis/morning-spanish", headers=auth())
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["text"]
    assert data["session"]["story_id"]


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
