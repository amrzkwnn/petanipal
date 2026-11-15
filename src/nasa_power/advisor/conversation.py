"""6-class open-question router, permission-to-save detector, and backend-only LLM phrasing."""

from __future__ import annotations

import os
from typing import Any, Literal

import requests

from .farm_memory import FarmMemoryRecord, next_useful_question

IntentClass = Literal[
    "explanation_of_result",
    "what_if_scenario",
    "general_farming",
    "missing_facts",
    "high_stakes_safety",
    "out_of_scope",
]

_SAFETY_KEYWORDS = (
    "pesticide",
    "herbicide",
    "fungicide",
    "insecticide",
    "chemical",
    "spray",
    "racun",
    "sembur",
    "dosage",
    "dose",
    "leaf curl",
    "diagnose",
    "disease",
    "penyakit",
    "blight",
    "wilt",
    "poison",
    "toxic",
)

_WHAT_IF_KEYWORDS = (
    "what if",
    "kalau",
    "jika",
    "suppose",
    "late rain",
    "drought",
    "kemarau",
    "heavy rain",
    "hot season",
    "el nino",
    "la nina",
    "next month",
    "bulan depan",
)

_EXPLANATION_KEYWORDS = (
    "why",
    "kenapa",
    "mengapa",
    "explain",
    "terangkan",
    "score",
    "skor",
    "rank",
    "compare",
    "banding",
    "basis",
    "risk",
    "risiko",
)

_FIELD_FACT_KEYWORDS = (
    "lower part",
    "lower area",
    "lower corner",
    "bahagian bawah",
    "bahagian rendah",
    "always gets wet",
    "stays wet",
    "selalu basah",
    "air bertakung",
    "bertakung",
    "waterlogged",
    "flooded last",
    "my field",
    "ladang saya",
    "poor drainage",
    "saliran buruk",
    "no irrigation",
    "tiada pengairan",
    "dries out fast",
    "cepat kering",
)

_OUT_OF_SCOPE_KEYWORDS = (
    "bitcoin",
    "crypto",
    "football",
    "movie",
    "politics",
    "lottery",
    "stock market",
    "recipe",
    "programming",
)


def classify_farmer_message(message: str, language: Literal["en", "ms"] = "en") -> IntentClass:
    """Classify a farmer's open question into one of 6 deterministic routing classes."""
    _ = language
    text = (message or "").strip().lower()
    if not text:
        return "missing_facts"
    if any(kw in text for kw in _SAFETY_KEYWORDS):
        return "high_stakes_safety"
    if any(kw in text for kw in _WHAT_IF_KEYWORDS):
        return "what_if_scenario"
    if any(kw in text for kw in _EXPLANATION_KEYWORDS):
        return "explanation_of_result"
    if any(kw in text for kw in _FIELD_FACT_KEYWORDS):
        return "missing_facts"
    if any(kw in text for kw in _OUT_OF_SCOPE_KEYWORDS):
        return "out_of_scope"
    return "general_farming"


def _extract_field_observation(message: str) -> dict[str, str] | None:
    """Detect volunteered field facts that require explicit farmer confirmation before saving."""
    text = (message or "").strip()
    lower = text.lower()
    if lower.endswith("?") and not any(
        k in lower for k in ("my field", "ladang saya", "lower part", "lower area", "bahagian bawah", "bahagian rendah")
    ):
        return None
    if not any(kw in lower for kw in _FIELD_FACT_KEYWORDS):
        return None

    if any(k in lower for k in ("lower part", "lower area", "lower corner", "bahagian bawah", "bahagian rendah")):
        zone = "lower area"
    elif any(k in lower for k in ("upper", "higher", "bahagian atas", "bahagian tinggi")):
        zone = "upper area"
    else:
        zone = "field"

    return {
        "zone": zone,
        "observation": text,
        "prompt_en": f"Should I remember this about your {zone}: \"{text}\"?",
        "prompt_ms": f"Perlukah saya ingat pemerhatian ini untuk {zone} anda: \"{text}\"?",
    }


def _deterministic_reply(
    intent: IntentClass,
    memory: FarmMemoryRecord,
    comparison: dict[str, Any] | None,
    pending_confirmation: dict[str, str] | None,
    language: Literal["en", "ms"],
) -> str:
    is_ms = language == "ms"
    if intent == "high_stakes_safety":
        return (
            "Saya tidak boleh mendiagnosis penyakit atau menetapkan racun kimia/dos. "
            "Sila rujuk Pegawai Pertanian tempatan (Jabatan Pertanian) atau baca label rasmi produk sebelum membuat semburan."
            if is_ms
            else "I cannot diagnose crop diseases or prescribe chemical pesticides or dosages. "
            "Please consult a local agricultural officer (DOA) or follow the official product label before spraying."
        )

    if intent == "out_of_scope":
        return (
            "Saya hanya dapat membantu perbandingan giliran tanaman, risiko cuaca NASA POWER, dan memori ladang anda."
            if is_ms
            else "I can only help with crop-rotation comparisons, NASA POWER weather-risk patterns, and your Farm Memory."
        )

    if intent == "what_if_scenario":
        return (
            "Anda boleh menguji senario 'Penanaman Kering', 'Hujan Lebat Semasa Menuai', atau 'Musim Panas' pada kawalan senario di atas untuk melihat bagaimana risiko setiap tanaman berubah berdasarkan data sejarah."
            if is_ms
            else "You can switch the scenario selector above to Dry Planting, Heavy Rain at Harvest, or Hot Season to compare how historical weather risk shifts across your 3 rotation options."
        )

    if intent == "explanation_of_result":
        if comparison and comparison.get("rotations"):
            top = comparison["rotations"][0]
            name = top.get("crop_name_ms" if is_ms else "crop_name_en", top.get("crop_id", ""))
            score = top.get("score", "")
            return (
                f"Pilihan teratas ialah {name} (skor risiko sejarah {score}/100) berdasarkan: {comparison.get('answer_basis', '')}"
                if is_ms
                else f"The top-ranked comparison option is {name} (historical-risk score {score}/100), grounded in: {comparison.get('answer_basis', '')}"
            )
        return (
            "Jalankan perbandingan tanaman terlebih dahulu supaya saya dapat menerangkan skor risiko sejarah untuk ladang anda."
            if is_ms
            else "Run a crop comparison first so I can explain the historical weather-risk scores for your field."
        )

    if pending_confirmation is not None:
        return pending_confirmation["prompt_ms" if is_ms else "prompt_en"]

    return (
        f"Untuk {memory.locality}, bandingkan 3 pilihan giliran tanaman di atas dan sahkan butiran ladang yang masih belum pasti sebelum membuat keputusan."
        if is_ms
        else f"For {memory.locality}, compare the 3 rotation options above and verify any unknown field details with local judgment before planting."
    )


def _optional_llm_phrase(
    draft_reply: str,
    message: str,
    intent: IntentClass,
    language: Literal["en", "ms"],
) -> str:
    """Optionally polish non-safety replies when OPENAI_API_KEY is configured server-side."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or intent == "high_stakes_safety":
        return draft_reply

    lang_name = "Bahasa Melayu" if language == "ms" else "plain English"
    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "gpt-4o-mini",
                "temperature": 0.2,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            f"Rewrite the deterministic farm-advisor reply in clear, concise {lang_name}. "
                            "Never prescribe a single crop, never promise yield or future prices, and keep all facts unchanged."
                        ),
                    },
                    {"role": "user", "content": f"Farmer asked: {message}\nDeterministic reply: {draft_reply}"},
                ],
            },
            timeout=15,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        return content or draft_reply
    except (requests.RequestException, KeyError, IndexError, TypeError):
        return draft_reply


def handle_farmer_chat(
    message: str,
    memory: FarmMemoryRecord,
    comparison: dict[str, Any] | None = None,
    language: Literal["en", "ms"] = "en",
) -> dict[str, Any]:
    """Route an open farmer question without mutating FarmMemoryStore."""
    intent = classify_farmer_message(message, language=language)
    pending_confirmation = (
        None if intent in ("high_stakes_safety", "out_of_scope") else _extract_field_observation(message)
    )
    draft = _deterministic_reply(intent, memory, comparison, pending_confirmation, language)
    reply = _optional_llm_phrase(draft, message, intent, language)
    next_q = next_useful_question(memory)

    basis = (
        comparison.get("answer_basis")
        if comparison and comparison.get("answer_basis")
        else f"Farm Memory ({memory.locality}) and deterministic 6-class router (intent={intent})."
    )
    return {
        "intent": intent,
        "reply": reply,
        "answer_basis": basis,
        "pending_confirmation": pending_confirmation,
        "next_question": next_q,
    }
