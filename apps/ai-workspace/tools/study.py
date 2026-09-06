"""Study AI tools routed through the BotConnector AI Gateway (:18270)."""
from __future__ import annotations

import json
import re
from typing import Any

import httpx

GATEWAY = "http://127.0.0.1:18270/v1/chat"
MAX_INPUT_CHARS = 60_000

DETAIL_GUIDANCE = {
    "singkat": "Buat sangat ringkas: maksimal 7 poin utama dan satu kesimpulan.",
    "terstruktur": (
        "Susun dengan judul, subjudul, poin penting, istilah kunci, contoh, dan kesimpulan."
    ),
    "ujian": (
        "Fokus untuk persiapan ujian: konsep wajib, hubungan antarkonsep, rumus/fakta penting, "
        "kesalahan umum, dan pertanyaan yang mungkin muncul."
    ),
    "mendalam": (
        "Buat pembahasan mendalam namun tetap jelas: konteks, konsep inti, rincian, contoh, "
        "keterkaitan, keterbatasan, dan kesimpulan."
    ),
}

DIFFICULTY_GUIDANCE = {
    "mudah": "Gunakan pertanyaan langsung untuk menguji pemahaman dasar.",
    "sedang": "Campurkan pemahaman konsep dan penerapan sederhana.",
    "sulit": "Gunakan analisis, penerapan, dan distraktor yang masuk akal.",
}

BASE_SYSTEM = (
    "Kamu adalah tutor Indonesia yang teliti dan wajib setia pada sumber. Bila materi diberikan, "
    "gunakan hanya informasi yang dinyatakan secara eksplisit di materi. Jangan menambah pengetahuan "
    "umum, contoh, kepanjangan istilah, definisi, asumsi, kesalahan umum, atau kesimpulan yang tidak "
    "didukung materi. Bila bagian yang diminta tidak tersedia, tulis 'Tidak dijelaskan dalam materi'. "
    "Pertahankan istilah sumber dan gunakan bahasa Indonesia yang jelas serta mudah dipindai."
)


def _clamp(value: int, low: int, high: int, default: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def _compact(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    clipped = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return (clipped or text[: limit - 1]).rstrip() + "…"


def _extract_array(text: str) -> list[Any]:
    cleaned = re.sub(r"^```(?:json)?", "", text.strip(), flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON array")
    candidate = re.sub(r",(\s*[}\]])", r"\1", cleaned[start : end + 1])
    parsed = json.loads(candidate)
    if not isinstance(parsed, list):
        raise ValueError("response is not a JSON array")
    return parsed


def _normalize_answer(answer: Any, options: list[str]) -> int:
    if isinstance(answer, bool):
        return 0
    if isinstance(answer, int):
        if 0 <= answer < len(options):
            return answer
        if 1 <= answer <= len(options):
            return answer - 1
    raw = str(answer or "").strip()
    if re.fullmatch(r"[A-Da-d]", raw):
        return ord(raw.upper()) - ord("A")
    if raw.isdigit():
        number = int(raw)
        if 0 <= number < len(options):
            return number
        if 1 <= number <= len(options):
            return number - 1
    lowered = raw.casefold()
    for index, option in enumerate(options):
        if option.casefold() == lowered:
            return index
    return 0


async def _call(messages: list[dict[str, str]], task: str, max_tokens: int, temperature: float):
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            GATEWAY,
            json={
                "messages": messages,
                "task": task,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
        )
        response.raise_for_status()
        data = response.json()
    return str(data.get("content", "")), {
        "provider": data.get("provider"),
        "model": data.get("model"),
        "latency_ms": data.get("latency_ms"),
    }


async def _structured_call(
    system: str,
    text: str,
    task: str,
    max_tokens: int,
) -> tuple[list[Any], dict[str, Any]]:
    last_error: Exception | None = None
    previous = ""
    meta: dict[str, Any] = {}
    for attempt in range(2):
        user = text
        if attempt and previous:
            user += (
                "\n\nRespons JSON sebelumnya tidak valid. Perbaiki format dan balas hanya JSON array "
                "yang valid, tanpa markdown atau teks tambahan."
            )
        raw, meta = await _call(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            task,
            max_tokens,
            0.35,
        )
        previous = raw
        try:
            return _extract_array(raw), meta
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    raise ValueError(f"JSON hasil AI tidak valid: {last_error}")


async def run(
    mode: str,
    text: str,
    question: str = "",
    task: str = "fast",
    detail: str = "terstruktur",
    card_count: int = 8,
    quiz_count: int = 5,
    difficulty: str = "sedang",
    quiz_type: str = "pilihan_ganda",
    focus: str = "",
) -> dict[str, Any]:
    mode = (mode or "").strip().lower()
    text = (text or "").strip()[:MAX_INPUT_CHARS]
    focus = (focus or "").strip()[:500]
    detail = detail if detail in DETAIL_GUIDANCE else "terstruktur"
    difficulty = difficulty if difficulty in DIFFICULTY_GUIDANCE else "sedang"
    card_count = _clamp(card_count, 4, 20, 8)
    quiz_count = _clamp(quiz_count, 3, 15, 5)

    focus_note = f"\nFokus khusus: {focus}" if focus else ""

    if mode in {"ringkas", "jelaskan", "panduan"}:
        if not text:
            raise ValueError("materi kosong")

        if mode == "ringkas":
            instruction = (
                f"{BASE_SYSTEM}\nTugas: ringkas materi berikut. {DETAIL_GUIDANCE[detail]}"
                f"{focus_note}"
            )
            max_tokens = 1700 if detail != "mendalam" else 2600
        elif mode == "jelaskan":
            instruction = (
                f"{BASE_SYSTEM}\nTugas: jelaskan materi seperti tutor sabar untuk pemula. "
                "Gunakan analogi sehari-hari, contoh konkret, dan bagian 'Inti yang perlu diingat'."
                f" {DETAIL_GUIDANCE[detail]}{focus_note}"
            )
            max_tokens = 2200
        else:
            instruction = (
                f"{BASE_SYSTEM}\nBuat PANDUAN BELAJAR terstruktur dengan bagian berikut: "
                "Tujuan belajar, gambaran umum, konsep utama, penjelasan per bagian, istilah penting, "
                "contoh, kesalahan umum, hal wajib diingat, latihan mandiri, dan rencana ulang belajar. "
                "Setiap bagian harus berasal dari materi. Untuk bagian yang tidak didukung sumber, tulis "
                "'Tidak dijelaskan dalam materi' dan jangan mengisinya dari pengetahuan umum. "
                f"{DETAIL_GUIDANCE[detail]}{focus_note}"
            )
            max_tokens = 2800

        content, meta = await _call(
            [{"role": "system", "content": instruction}, {"role": "user", "content": text}],
            task,
            max_tokens,
            0.25 if mode == "panduan" else 0.35,
        )
        return {
            "mode": mode,
            "type": "text",
            "content": content.strip(),
            "_meta": meta,
        }

    if mode == "tanya":
        query = (question or "").strip()
        if not query:
            raise ValueError("pertanyaan kosong")
        if text:
            user = f"Materi acuan:\n{text}\n\nPertanyaan siswa:\n{query}"
            citation = (
                "Bila materi memiliki penanda 'SUMBER' atau 'Halaman', sebutkan sumber/halaman yang "
                "mendukung jawaban. Jangan membuat nomor halaman yang tidak ada."
            )
        else:
            user = query
            citation = "Tidak ada materi acuan; jelaskan bila jawaban berasal dari pengetahuan umum."
        system = (
            f"{BASE_SYSTEM}\nJawab pertanyaan dengan urutan: Jawaban inti, Penjelasan, dan Hal yang perlu "
            f"diingat. {citation}{focus_note}"
        )
        content, meta = await _call(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            task,
            1800,
            0.35,
        )
        return {
            "mode": mode,
            "type": "text",
            "content": content.strip(),
            "_meta": meta,
        }

    if mode == "flashcard":
        if not text:
            raise ValueError("materi kosong")
        system = (
            f"{BASE_SYSTEM}\nBuat tepat {card_count} flashcard dari materi. "
            "Balas HANYA JSON array valid tanpa markdown dengan bentuk: "
            '[{"q":"pertanyaan singkat","a":"jawaban ringkas dan jelas"}]. '
            "Satu kartu hanya menguji satu konsep. Pertanyaan maksimal 160 karakter dan jawaban maksimal "
            "320 karakter atau tiga kalimat pendek. Ringkas dengan kata sendiri tanpa menyalin paragraf panjang. "
            "Sebarkan kartu pada konsep penting, jangan duplikat, dan jangan menguji trivia yang tidak penting."
            f"{focus_note}"
        )
        items, meta = await _structured_call(system, text, task, 2600)
        clean = [
            {"q": _compact(item.get("q", ""), 180), "a": _compact(item.get("a", ""), 360)}
            for item in items
            if isinstance(item, dict) and str(item.get("q", "")).strip()
        ][:card_count]
        if not clean:
            raise ValueError("AI tidak menghasilkan flashcard yang valid")
        return {"mode": mode, "type": "cards", "items": clean, "_meta": meta}

    if mode == "kuis":
        if not text:
            raise ValueError("materi kosong")
        # v3 currently normalizes all quiz requests to four-option multiple choice.
        quiz_type = "pilihan_ganda" if quiz_type != "pilihan_ganda" else quiz_type
        system = (
            f"{BASE_SYSTEM}\nBuat tepat {quiz_count} soal pilihan ganda tingkat {difficulty}. "
            f"{DIFFICULTY_GUIDANCE[difficulty]} "
            "Balas HANYA JSON array valid tanpa markdown dengan bentuk: "
            '[{"q":"soal","options":["opsi A","opsi B","opsi C","opsi D"],'
            '"answer":0,"why":"alasan jawaban benar"}]. '
            "answer wajib indeks 0-3. Setiap soal wajib memiliki tepat empat opsi dan hanya satu jawaban "
            "yang benar menurut materi. Distraktor harus jelas salah berdasarkan materi, bukan jawaban yang "
            "sebagian benar atau ambigu. Pertanyaan maksimal 200 karakter, setiap opsi maksimal 160 karakter, "
            "dan penjelasan maksimal 320 karakter. Jangan menduplikasi soal."
            f"{focus_note}"
        )
        items, meta = await _structured_call(system, text, task, 3600)
        clean: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            question_text = _compact(item.get("q", ""), 220)
            raw_options = item.get("options")
            if not question_text or not isinstance(raw_options, list):
                continue
            options = [_compact(option, 180) for option in raw_options if str(option).strip()][:4]
            if len(options) != 4:
                continue
            clean.append(
                {
                    "q": question_text,
                    "options": options,
                    "answer": _normalize_answer(item.get("answer"), options),
                    "why": _compact(item.get("why", ""), 360),
                }
            )
        clean = clean[:quiz_count]
        if not clean:
            raise ValueError("AI tidak menghasilkan kuis yang valid")
        return {"mode": mode, "type": "quiz", "items": clean, "_meta": meta}

    raise ValueError(f"mode tidak dikenal: {mode}")
