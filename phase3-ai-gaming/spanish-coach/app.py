import base64
import json
import os
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import JSON, DateTime, Float, Integer, String, Text, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


APP_NAME = "spanish-coach"
TARGET_LANGUAGE = "Spanish"
DEFAULT_DATABASE_URL = "sqlite:////data/spanish_coach.sqlite3"

DATABASE_URL = os.environ.get("SPANISH_COACH_DATABASE_URL", DEFAULT_DATABASE_URL)
TOKEN = os.environ.get("SPANISH_COACH_TOKEN", "")
LLM_MODEL = os.environ.get("SPANISH_COACH_LLM_MODEL") or os.environ.get("JARVIS_FAST_LLM_MODEL", "llama-3.1-70b-instruct")
LLM_BASE_URL = (os.environ.get("SPANISH_COACH_LLM_BASE_URL") or os.environ.get("JARVIS_FAST_LLM_BASE_URL", "")).rstrip("/")
LLM_API_KEY = os.environ.get("SPANISH_COACH_LLM_API_KEY") or os.environ.get("JARVIS_FAST_LLM_API_KEY", "")
TTS_URL = os.environ.get("SPANISH_COACH_TTS_URL", "http://tts-worker:8101").rstrip("/")
TTS_TOKEN = os.environ.get("SPANISH_COACH_TTS_TOKEN") or os.environ.get("JARVIS_TTS_TOKEN", "")
TTS_VOICE = os.environ.get("SPANISH_COACH_TTS_VOICE") or os.environ.get("JARVIS_TTS_VOICE", "default")
WHISPER_URL = os.environ.get("SPANISH_COACH_WHISPER_URL", "http://whisper-worker:8099").rstrip("/")
WHISPER_TOKEN = os.environ.get("WHISPER_WORKER_TOKEN", "")

engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class PracticeSession(Base):
    __tablename__ = "practice_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    target_language: Mapped[str] = mapped_column(String(32), default="spanish", index=True)
    user_text: Mapped[str] = mapped_column(Text)
    tutor_text: Mapped[str] = mapped_column(Text)
    corrections: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    extracted_vocab: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


class VocabCard(Base):
    __tablename__ = "vocab_cards"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    target_language: Mapped[str] = mapped_column(String(32), default="spanish", index=True)
    spanish: Mapped[str] = mapped_column(String(240), index=True)
    english: Mapped[str] = mapped_column(String(240))
    example_sentence: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    difficulty: Mapped[float] = mapped_column(Float, default=2.5)
    interval_days: Mapped[int] = mapped_column(Integer, default=0)
    repetitions: Mapped[int] = mapped_column(Integer, default=0)
    lapses: Mapped[int] = mapped_column(Integer, default=0)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    review_history: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Story(Base):
    __tablename__ = "stories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    target_language: Mapped[str] = mapped_column(String(32), default="spanish", index=True)
    title: Mapped[str] = mapped_column(String(240))
    level: Mapped[str] = mapped_column(String(32), default="beginner")
    topic: Mapped[str] = mapped_column(String(240), default="")
    spanish_text: Mapped[str] = mapped_column(Text)
    english_text: Mapped[str] = mapped_column(Text)
    vocabulary: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    questions: Mapped[list[str]] = mapped_column(JSON, default=list)
    listening_plan: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


def init_db() -> None:
    if DATABASE_URL.startswith("sqlite"):
        path = DATABASE_URL.removeprefix("sqlite:///")
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Spanish Coach", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


def get_db():
    with SessionLocal() as db:
        yield db


def token_configured() -> bool:
    return bool(TOKEN and not TOKEN.startswith("CHANGE_ME"))


def require_auth(authorization: str | None = Header(default=None)) -> None:
    if not token_configured():
        return
    if authorization != f"Bearer {TOKEN}":
        raise HTTPException(status_code=401, detail="unauthorized")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_json_object(raw: str, fallback: dict[str, Any]) -> dict[str, Any]:
    raw = (raw or "").strip()
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return fallback
    return fallback


def story_shape(level: str, length: str) -> dict[str, int | str]:
    level_key = str(level or "beginner").lower()
    length_key = str(length or "short").lower()
    sentence_counts = {"short": 5, "medium": 10, "long": 16}
    base = int(sentence_counts.get(length_key, 5))
    if level_key in {"intermediate", "advanced"}:
        base += 3
    if level_key == "advanced":
        base += 4
    cefr = {"beginner": "A1-A2", "intermediate": "B1-B2", "advanced": "B2-C1"}.get(level_key, "A1-A2")
    return {"sentences": base, "cefr": cefr}


def tutor_prompt(message: str) -> list[dict[str, str]]:
    system = (
        "You are a private Spanish learning coach. The learner's target language is Spanish. "
        "Respond as compact JSON with keys: reply, corrections, next_phrase, vocab. "
        "Keep the tone warm and practical. Use Spanish first, then brief English support. "
        "corrections is an array of objects with original, corrected, explanation. "
        "vocab is an array of objects with spanish, english, example_sentence, tags."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": message}]


def story_prompt(req: "StoryCreate") -> list[dict[str, str]]:
    shape = story_shape(req.level, req.length)
    system = (
        "You generate varied interactive Spanish learning stories. The target language is Spanish. "
        "Return compact JSON only with keys title, spanish_text, english_text, vocabulary, questions. "
        "vocabulary is an array of objects with spanish, english, example_sentence, tags. "
        "questions is an array of 3 comprehension or speaking questions in Spanish with brief English glosses. "
        "Use correct Spanish orthography, including ñ and accents such as español, mañana, pequeño, está, and también when appropriate. "
        "Never reuse cafe/Ana boilerplate unless the topic truly asks for it."
    )
    user = (
        f"Level: {req.level}. Topic: {req.topic or 'daily life'}. Length: {req.length}. "
        f"Target about {shape['sentences']} Spanish sentences at CEFR {shape['cefr']}. "
        f"Tense focus: {req.tense or 'present and practical past'}. "
        f"Required vocab focus: {req.vocab_focus or 'common useful words'}. "
        "Make the story specific, with a small decision or emotional turn, and include one question that asks the learner what they would say next."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


async def call_llm(messages: list[dict[str, str]]) -> str:
    if not LLM_BASE_URL or not LLM_API_KEY:
        raise RuntimeError("llm_not_configured")
    headers = {"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": LLM_MODEL, "messages": messages, "temperature": 0.72}
    urls = [f"{LLM_BASE_URL}/chat/completions"]
    if not LLM_BASE_URL.rstrip("/").endswith("/v1"):
        urls.append(f"{LLM_BASE_URL}/v1/chat/completions")
    last_error = None
    async with httpx.AsyncClient(timeout=90) as client:
        for url in dict.fromkeys(urls):
            try:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
            except Exception as exc:
                last_error = exc
                continue
    raise RuntimeError(f"llm_request_failed: {last_error}")


def fallback_tutor(message: str) -> dict[str, Any]:
    return {
        "reply": "Vamos a practicar. Dime una frase sencilla en español y la mejoramos juntos. In English: say one simple sentence and I will help you polish it.",
        "corrections": [],
        "next_phrase": "Quiero aprender español todos los días.",
        "vocab": [
            {
                "spanish": "aprender",
                "english": "to learn",
                "example_sentence": "Quiero aprender español.",
                "tags": ["starter"],
            }
        ],
        "source": "fallback",
        "input": message,
    }


def replace_words(text_value: str, replacements: dict[str, str]) -> str:
    for source, target in replacements.items():
        text_value = text_value.replace(source, target)
    return text_value


def fallback_story(req: "StoryCreate") -> dict[str, Any]:
    topic = (req.topic or "la familia").strip()
    level = str(req.level or "beginner").lower()
    length = str(req.length or "short").lower()
    tense = (req.tense or "presente").strip().lower()
    shape = story_shape(level, length)
    topic_lower = topic.lower()
    if "famil" in topic_lower:
        title = "La decisión de la familia"
        seed = [
            ("El sábado por la mañana, la familia Rivera prepara el desayuno en una cocina pequeña.", "On Saturday morning, the Rivera family prepares breakfast in a small kitchen."),
            ("La abuela quiere visitar el mercado, pero el hermano menor sueña con ir al parque.", "The grandmother wants to visit the market, but the younger brother dreams of going to the park."),
            ("Sofía escucha a todos y escribe dos planes en una hoja amarilla.", "Sofía listens to everyone and writes two plans on a yellow sheet of paper."),
            ("Su papá dice: «Primero compramos fruta fresca y después jugamos fútbol».", "Her dad says, \"First we buy fresh fruit and then we play soccer.\""),
            ("La mamá sonríe porque la solución incluye a todos.", "The mom smiles because the solution includes everyone."),
            ("En el mercado, Sofía pide piña, pan y un kilo de tomates con mucha confianza.", "At the market, Sofía asks for pineapple, bread, and a kilo of tomatoes with a lot of confidence."),
            ("El vendedor le contesta rápido, y ella pregunta otra vez sin tener vergüenza.", "The seller answers quickly, and she asks again without being embarrassed."),
            ("Cuando llegan al parque, el hermano menor enseña una canción nueva.", "When they arrive at the park, the younger brother teaches a new song."),
            ("La abuela canta despacio, y todos repiten las palabras hasta reírse.", "The grandmother sings slowly, and everyone repeats the words until they laugh."),
            ("Al final, Sofía entiende que una buena familia no siempre está de acuerdo, pero sí se escucha.", "In the end, Sofía understands that a good family does not always agree, but it does listen."),
            ("Antes de dormir, escribe en su diario: «Mañana voy a hablar con más paciencia».", "Before sleeping, she writes in her diary: \"Tomorrow I am going to speak with more patience.\""),
            ("También anota tres palabras nuevas para practicarlas en voz alta.", "She also writes down three new words to practice out loud."),
            ("Su hermano toca la puerta y le pregunta si mañana pueden cocinar juntos.", "Her brother knocks on the door and asks if tomorrow they can cook together."),
            ("Sofía responde que sí, pero solo si él lava los platos después.", "Sofía answers yes, but only if he washes the dishes afterward."),
            ("Los dos se ríen porque saben que el trato es justo.", "They both laugh because they know the deal is fair."),
            ("La casa queda tranquila, llena de pequeñas promesas para el día siguiente.", "The house becomes quiet, full of small promises for the next day."),
            ("Si tú estuvieras allí, podrías decir: «Yo también quiero ayudar».", "If you were there, you could say: \"I also want to help.\""),
            ("Esa frase sencilla abre una conversación nueva.", "That simple phrase opens a new conversation."),
        ]
        vocab = [
            {"spanish": "mañana", "english": "morning / tomorrow", "example_sentence": "Mañana voy a hablar con más paciencia.", "tags": ["story", "ñ"]},
            {"spanish": "pequeña", "english": "small", "example_sentence": "La familia está en una cocina pequeña.", "tags": ["story", "adjective"]},
            {"spanish": "vergüenza", "english": "embarrassment", "example_sentence": "Ella pregunta otra vez sin vergüenza.", "tags": ["story", "emotion"]},
            {"spanish": "también", "english": "also", "example_sentence": "Yo también quiero ayudar.", "tags": ["story", "accent"]},
        ]
    else:
        title = f"Una historia sobre {topic}"
        seed = [
            (f"Esta mañana, Lucía encuentra algo extraño relacionado con {topic}.", f"This morning, Lucía finds something unusual related to {topic}."),
            ("Al principio no sabe qué decir, así que respira y observa con atención.", "At first she does not know what to say, so she breathes and observes carefully."),
            ("Un señor amable le hace una pregunta rápida en español.", "A kind man asks her a quick question in Spanish."),
            ("Lucía entiende la idea principal, pero necesita repetir una palabra nueva.", "Lucía understands the main idea, but she needs to repeat a new word."),
            ("Ella responde despacio: «¿Puede decirlo otra vez, por favor?».", "She answers slowly: \"Can you say it again, please?\""),
            ("La conversación cambia, y de pronto todo parece más fácil.", "The conversation changes, and suddenly everything seems easier."),
            ("Después escribe la palabra en su teléfono para practicarla más tarde.", "Afterward she writes the word on her phone to practice it later."),
            ("Por la noche, cuenta la experiencia a su familia con orgullo.", "At night, she tells her family about the experience with pride."),
            ("Su hermana pequeña dice que aprender español suena como una aventura.", "Her little sister says that learning Spanish sounds like an adventure."),
            ("Lucía sonríe y promete enseñar una frase nueva cada día.", "Lucía smiles and promises to teach one new phrase every day."),
            ("La primera frase es: «No entiendo todavía, pero quiero aprender».", "The first phrase is: \"I do not understand yet, but I want to learn.\""),
            ("Todos la repiten juntos hasta que la pronunciación mejora.", "Everyone repeats it together until the pronunciation improves."),
            ("Lucía descubre que la confianza crece cuando practica en voz alta.", "Lucía discovers that confidence grows when she practices out loud."),
            ("Si tú fueras Lucía, ¿qué frase practicarías después?", "If you were Lucía, what phrase would you practice next?"),
        ]
        vocab = [
            {"spanish": "español", "english": "Spanish", "example_sentence": "Un señor le habla en español.", "tags": ["story", "ñ"]},
            {"spanish": "todavía", "english": "yet / still", "example_sentence": "No entiendo todavía.", "tags": ["story", "accent"]},
            {"spanish": "enseñar", "english": "to teach", "example_sentence": "Promete enseñar una frase nueva.", "tags": ["story", "ñ"]},
            {"spanish": "pronunciación", "english": "pronunciation", "example_sentence": "La pronunciación mejora.", "tags": ["story", "accent"]},
        ]
    variant = uuid.uuid4().int % 3
    if "famil" in topic_lower:
        variants = [
            {"Rivera": "Rivera", "Sofía": "Sofía", "papá": "papá", "mamá": "mamá", "mercado": "mercado", "parque": "parque"},
            {"Rivera": "Morales", "Sofía": "Camila", "papá": "tío", "mamá": "tía", "mercado": "panadería", "parque": "plaza"},
            {"Rivera": "Cruz", "Sofía": "Valeria", "papá": "abuelo", "mamá": "abuela", "mercado": "tienda", "parque": "jardín"},
        ]
        replacements = variants[variant]
        title = f"La decisión de la familia {replacements['Rivera']}"
    else:
        variants = [
            {"Lucía": "Lucía", "señor": "señor", "teléfono": "teléfono"},
            {"Lucía": "Marisol", "señor": "vecino", "teléfono": "cuaderno"},
            {"Lucía": "Elena", "señor": "profesor", "teléfono": "diario"},
        ]
        replacements = variants[variant]
        title = f"{title}: versión {variant + 1}"
    seed = [
        (
            replace_words(es, replacements),
            replace_words(en, replacements),
        )
        for es, en in seed
    ]
    count = int(shape["sentences"])
    selected = seed[: min(count, len(seed))]
    if tense.startswith("past") or tense.startswith("pretérito") or tense.startswith("preter"):
        selected = [(es.replace("Esta mañana", "Ayer").replace("encuentra", "encontró").replace("prepara", "preparó"), en) for es, en in selected]
    spanish_text = " ".join(es for es, _ in selected)
    english_text = " ".join(en for _, en in selected)
    return {
        "title": title,
        "spanish_text": spanish_text,
        "english_text": english_text,
        "vocabulary": vocab,
        "questions": [
            "¿Qué problema pequeño aparece en la historia? / What small problem appears in the story?",
            "¿Qué frase podrías decir tú en esa situación? / What phrase could you say in that situation?",
            "¿Qué palabra nueva quieres repetir tres veces? / What new word do you want to repeat three times?",
        ],
        "source": "fallback",
        "requested": {"level": level, "length": length, "topic": topic, "tense": tense},
    }


def clean_vocab(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    seen: set[str] = set()
    cleaned: list[dict[str, Any]] = []
    for item in items or []:
        spanish = str(item.get("spanish") or "").strip()
        english = str(item.get("english") or "").strip()
        if not spanish or not english:
            continue
        key = spanish.casefold()
        if key in seen:
            continue
        seen.add(key)
        tags = item.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        cleaned.append(
            {
                "spanish": spanish,
                "english": english,
                "example_sentence": str(item.get("example_sentence") or ""),
                "tags": [str(tag) for tag in tags[:6]],
            }
        )
    return cleaned


def split_sentences(text_value: str) -> list[str]:
    pattern = r"[^.!?]+(?:[.!?]+[\"'»”]?|$)"
    return [match.group(0).strip() for match in re.finditer(pattern, text_value) if match.group(0).strip()]


def split_clauses(sentence: str, lang: str) -> list[str]:
    sentence = sentence.strip()
    if not sentence:
        return []
    if len(sentence.split()) <= 7:
        return [sentence]
    if lang == "es":
        pattern = r"(?<=[,;:])\s+|\s+(?=pero\b|porque\b|cuando\b|si\b|aunque\b|después\b)"
    else:
        pattern = r"(?<=[,;:])\s+|\s+(?=but\b|because\b|when\b|if\b|although\b|after\b|then\b)"
    parts = [part.strip(" ,;:") for part in re.split(pattern, sentence, flags=re.I) if part.strip(" ,;:")]
    if len(parts) <= 1:
        return [sentence]
    return parts


def listening_plan(spanish_text: str, english_text: str) -> dict[str, Any]:
    spanish_sentences = split_sentences(spanish_text)
    english_sentences = split_sentences(english_text)
    paired = []
    for index, spanish in enumerate(spanish_sentences):
        english = english_sentences[index] if index < len(english_sentences) else ""
        spanish_clauses = split_clauses(spanish, "es")
        english_clauses = split_clauses(english, "en")
        for clause_index, spanish_clause in enumerate(spanish_clauses):
            english_clause = english_clauses[clause_index] if clause_index < len(english_clauses) else english
            paired.append(
                {
                    "spanish": spanish_clause,
                    "english": english_clause,
                    "sentence_index": index,
                    "sequence": [
                        {"text": spanish_clause, "lang": "es"},
                        {"text": english_clause, "lang": "en-us"},
                        {"text": spanish_clause, "lang": "es"},
                    ],
                }
            )
    return {
        "sentence_loop": paired,
        "full_loop": [
            {"text": spanish_text, "lang": "es"},
            {"text": english_text, "lang": "en-us"},
            {"text": spanish_text, "lang": "es"},
        ],
        "shadowing": [{"spanish": item["spanish"], "pause_seconds": 2.2} for item in paired],
    }


def schedule_review(card: VocabCard, rating: str) -> None:
    rating = rating.lower()
    quality = {"again": 1, "hard": 3, "good": 4, "easy": 5}.get(rating)
    if quality is None:
        raise HTTPException(status_code=400, detail="rating must be again, hard, good, or easy")
    previous = {"interval_days": card.interval_days, "difficulty": card.difficulty, "repetitions": card.repetitions}
    if quality < 3:
        card.repetitions = 0
        card.interval_days = 1
        card.lapses += 1
    else:
        card.repetitions += 1
        if card.repetitions == 1:
            card.interval_days = 1
        elif card.repetitions == 2:
            card.interval_days = 3 if rating == "hard" else 6
        else:
            multiplier = card.difficulty + (0.3 if rating == "easy" else -0.15 if rating == "hard" else 0)
            card.interval_days = max(1, round(card.interval_days * multiplier))
    card.difficulty = max(1.3, card.difficulty + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)))
    card.due_at = now_utc() + timedelta(days=card.interval_days)
    card.updated_at = now_utc()
    history = list(card.review_history or [])
    history.append({"at": now_utc().isoformat(), "rating": rating, "before": previous, "after": {"interval_days": card.interval_days, "difficulty": card.difficulty, "repetitions": card.repetitions}})
    card.review_history = history


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    save_vocab: bool = True


class VocabCreate(BaseModel):
    spanish: str
    english: str
    example_sentence: str = ""
    tags: list[str] = []


class ReviewRequest(BaseModel):
    rating: str


class TTSRequest(BaseModel):
    text: str | None = None
    segments: list[str | dict[str, Any]] | None = None
    voice: str | None = None
    format: str = "ogg"
    lang: str | None = None


class StoryCreate(BaseModel):
    level: str = "beginner"
    topic: str = ""
    length: str = "short"
    tense: str = ""
    vocab_focus: str = ""
    save_vocab: bool = True


@app.get("/")
def index() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/health")
async def health(db: Session = Depends(get_db)) -> dict[str, Any]:
    checks: dict[str, Any] = {"app": True, "llm_configured": bool(LLM_BASE_URL and LLM_API_KEY)}
    try:
        db.execute(text("select 1"))
        checks["database"] = True
    except Exception as exc:
        checks["database"] = str(exc)
    async with httpx.AsyncClient(timeout=3) as client:
        for name, url in {"tts": TTS_URL, "whisper": WHISPER_URL}.items():
            try:
                response = await client.get(f"{url}/health")
                checks[name] = response.status_code < 500
            except Exception as exc:
                checks[name] = str(exc)
    return {"ok": checks.get("database") is True, "service": APP_NAME, "checks": checks}


@app.post("/api/chat", dependencies=[Depends(require_auth)])
async def chat(req: ChatRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        raw = await call_llm(tutor_prompt(req.message))
        data = parse_json_object(raw, fallback_tutor(req.message))
    except Exception:
        data = fallback_tutor(req.message)
    vocab = clean_vocab(data.get("vocab"))
    session = PracticeSession(user_text=req.message, tutor_text=str(data.get("reply") or ""), corrections=data.get("corrections") or [], extracted_vocab=vocab)
    db.add(session)
    if req.save_vocab:
        upsert_vocab(db, vocab)
    db.commit()
    return {"id": session.id, "reply": session.tutor_text, "corrections": session.corrections, "next_phrase": data.get("next_phrase", ""), "vocab": vocab}


def upsert_vocab(db: Session, vocab: list[dict[str, Any]]) -> None:
    for item in vocab:
        existing = db.scalar(select(VocabCard).where(VocabCard.spanish.ilike(item["spanish"])))
        if existing:
            tags = sorted(set((existing.tags or []) + item.get("tags", [])))
            existing.tags = tags
            if item.get("example_sentence") and not existing.example_sentence:
                existing.example_sentence = item["example_sentence"]
            existing.updated_at = now_utc()
            continue
        db.add(VocabCard(spanish=item["spanish"], english=item["english"], example_sentence=item.get("example_sentence", ""), tags=item.get("tags", [])))


@app.post("/api/audio/transcribe", dependencies=[Depends(require_auth)])
async def transcribe(file: UploadFile = File(...)) -> dict[str, Any]:
    headers = {}
    if WHISPER_TOKEN and not WHISPER_TOKEN.startswith("CHANGE_ME"):
        headers["Authorization"] = f"Bearer {WHISPER_TOKEN}"
    content = await file.read()
    files = {"file": (file.filename or "audio.webm", content, file.content_type or "application/octet-stream")}
    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(f"{WHISPER_URL}/transcribe", headers=headers, files=files, data={"language": "es"})
        response.raise_for_status()
    return response.json()


@app.post("/api/tts", dependencies=[Depends(require_auth)])
async def tts(req: TTSRequest) -> Response:
    segments = req.segments or ([req.text] if req.text else [])
    first = segments[0] if segments else ""
    if isinstance(first, dict):
        text_value = str(first.get("text") or "").strip()
        lang = str(first.get("lang") or req.lang or "").strip() or None
    else:
        text_value = str(first or "").strip()
        lang = req.lang
    if not text_value:
        raise HTTPException(status_code=400, detail="text or segments required")
    headers = {}
    if TTS_TOKEN and not TTS_TOKEN.startswith("CHANGE_ME"):
        headers["Authorization"] = f"Bearer {TTS_TOKEN}"
    payload = {"text": text_value, "voice": req.voice or TTS_VOICE, "format": req.format, "max_chars": 0, "lang": lang}
    async with httpx.AsyncClient(timeout=240) as client:
        response = await client.post(f"{TTS_URL}/tts/synthesize", headers=headers, json=payload)
        response.raise_for_status()
    return Response(content=response.content, media_type=response.headers.get("content-type", "audio/ogg"))


@app.get("/api/vocab/due", dependencies=[Depends(require_auth)])
def due_vocab(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    cards = db.scalars(select(VocabCard).where(VocabCard.due_at <= now_utc()).order_by(VocabCard.due_at).limit(100)).all()
    return [card_dict(card) for card in cards]


@app.post("/api/vocab", dependencies=[Depends(require_auth)])
def create_vocab(req: VocabCreate, db: Session = Depends(get_db)) -> dict[str, Any]:
    item = {"spanish": req.spanish, "english": req.english, "example_sentence": req.example_sentence, "tags": req.tags}
    vocab = clean_vocab([item])
    if not vocab:
        raise HTTPException(status_code=400, detail="spanish and english are required")
    upsert_vocab(db, vocab)
    db.commit()
    card = db.scalar(select(VocabCard).where(VocabCard.spanish.ilike(vocab[0]["spanish"])))
    return card_dict(card)


@app.post("/api/vocab/{card_id}/review", dependencies=[Depends(require_auth)])
def review_vocab(card_id: str, req: ReviewRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    card = db.get(VocabCard, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="card not found")
    schedule_review(card, req.rating)
    db.commit()
    return card_dict(card)


@app.post("/api/stories", dependencies=[Depends(require_auth)])
async def create_story(req: StoryCreate, db: Session = Depends(get_db)) -> dict[str, Any]:
    source = "llm"
    generation_error = ""
    try:
        raw = await call_llm(story_prompt(req))
        data = parse_json_object(raw, fallback_story(req))
        if data.get("source") == "fallback":
            source = "fallback_parse"
    except Exception:
        generation_error = "story_model_unavailable"
        data = fallback_story(req)
        source = "fallback"
    vocab = clean_vocab(data.get("vocabulary"))
    story = Story(
        title=str(data.get("title") or "Spanish Story"),
        level=req.level,
        topic=req.topic,
        spanish_text=str(data.get("spanish_text") or ""),
        english_text=str(data.get("english_text") or ""),
        vocabulary=vocab,
        questions=[str(q) for q in (data.get("questions") or [])],
        listening_plan=listening_plan(str(data.get("spanish_text") or ""), str(data.get("english_text") or "")),
    )
    db.add(story)
    if req.save_vocab:
        upsert_vocab(db, vocab)
    db.commit()
    result = story_dict(story)
    result["source"] = source
    if generation_error:
        result["generation_error"] = generation_error
    return result


@app.get("/api/stories", dependencies=[Depends(require_auth)])
def list_stories(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    stories = db.scalars(select(Story).order_by(Story.created_at.desc()).limit(50)).all()
    return [story_dict(story, include_text=False) for story in stories]


@app.get("/api/stories/{story_id}", dependencies=[Depends(require_auth)])
def get_story(story_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    story = db.get(Story, story_id)
    if not story:
        raise HTTPException(status_code=404, detail="story not found")
    return story_dict(story)


@app.get("/api/sessions", dependencies=[Depends(require_auth)])
def list_sessions(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    sessions = db.scalars(select(PracticeSession).order_by(PracticeSession.created_at.desc()).limit(50)).all()
    return [
        {
            "id": item.id,
            "user_text": item.user_text,
            "tutor_text": item.tutor_text,
            "corrections": item.corrections,
            "extracted_vocab": item.extracted_vocab,
            "created_at": item.created_at.isoformat(),
        }
        for item in sessions
    ]


def card_dict(card: VocabCard) -> dict[str, Any]:
    return {
        "id": card.id,
        "target_language": card.target_language,
        "spanish": card.spanish,
        "english": card.english,
        "example_sentence": card.example_sentence,
        "tags": card.tags or [],
        "difficulty": card.difficulty,
        "interval_days": card.interval_days,
        "repetitions": card.repetitions,
        "lapses": card.lapses,
        "due_at": card.due_at.isoformat(),
    }


def story_dict(story: Story, include_text: bool = True) -> dict[str, Any]:
    data = {
        "id": story.id,
        "target_language": story.target_language,
        "title": story.title,
        "level": story.level,
        "topic": story.topic,
        "vocabulary": story.vocabulary or [],
        "questions": story.questions or [],
        "created_at": story.created_at.isoformat(),
    }
    if include_text:
        data.update({"spanish_text": story.spanish_text, "english_text": story.english_text, "listening_plan": story.listening_plan or {}})
    return data


@app.get("/api/audio/story/{story_id}", dependencies=[Depends(require_auth)])
def story_audio_payload(story_id: str, mode: str = "sentence_loop", db: Session = Depends(get_db)) -> dict[str, Any]:
    story = db.get(Story, story_id)
    if not story:
        raise HTTPException(status_code=404, detail="story not found")
    plan = story.listening_plan or listening_plan(story.spanish_text, story.english_text)
    if mode == "full_loop":
        segments = plan["full_loop"]
    elif mode == "shadowing":
        segments = [{"text": item["spanish"], "lang": "es", "pause_seconds": item.get("pause_seconds", 3)} for item in plan["shadowing"]]
    else:
        segments = [segment for item in plan["sentence_loop"] for segment in item["sequence"] if segment]
    return {"story_id": story.id, "mode": mode, "segments": segments}
