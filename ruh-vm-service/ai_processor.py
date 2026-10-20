from __future__ import annotations

import base64
import json
from pathlib import Path

import fitz
from openai import OpenAI

from config import OPENAI_API_KEY, OPENAI_MODEL


class UnsupportedNoticeFile(Exception):
    pass


def _client() -> OpenAI:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    return OpenAI(api_key=OPENAI_API_KEY)


def _prompt(title: str) -> str:
    return f"""
You analyze university notices from Sri Lanka.

Notice title: {title}

Extract these fields where present:
- subject_code: module/subject code such as CSC1234, otherwise null
- subject_name: subject/module name, otherwise null
- degree_programme: broader degree programme, otherwise null
- semester_exam: level, semester, academic year, or examination session, otherwise null
- deadline: explicit deadline including time when stated, otherwise null
- summary: factual one- or two-sentence summary without greetings

Do not confuse a degree programme with a subject name. Do not invent missing details.
Return only valid JSON with exactly these keys:
{{
  "subject_code": null,
  "subject_name": null,
  "degree_programme": null,
  "semester_exam": null,
  "deadline": null,
  "summary": ""
}}
""".strip()


def _image_message(data: bytes, media_type: str, prompt: str) -> list[dict]:
    encoded = base64.b64encode(data).decode("ascii")
    return [
        {"type": "text", "text": prompt},
        {
            "type": "image_url",
            "image_url": {"url": f"data:{media_type};base64,{encoded}", "detail": "high"},
        },
    ]


def analyze_notice(title: str, filepath: str, file_type: str) -> dict:
    lower_title = (title or "").lower()
    if any(term in lower_title for term in ("exam center", "exam centre", "examination center", "examination centre")):
        return {
            "subject_code": None,
            "subject_name": None,
            "degree_programme": None,
            "semester_exam": None,
            "deadline": None,
            "summary": "Examination-centre allocation notice. Verify the original document for the assigned centre.",
        }

    path = Path(filepath)
    if not path.is_file():
        raise FileNotFoundError(filepath)

    prompt = _prompt(title)
    kind = (file_type or path.suffix.lstrip(".")).lower()
    content: list[dict]

    if kind == "pdf":
        with fitz.open(path) as doc:
            if doc.page_count < 1:
                raise ValueError("PDF has no pages")
            pix = doc.load_page(0).get_pixmap(dpi=150, alpha=False)
            content = _image_message(pix.tobytes("png"), "image/png", prompt)
    elif kind in {"jpg", "jpeg", "png", "webp"}:
        media_type = "image/jpeg" if kind in {"jpg", "jpeg"} else f"image/{kind}"
        content = _image_message(path.read_bytes(), media_type, prompt)
    elif kind in {"txt", "html", "htm"}:
        text = path.read_text(encoding="utf-8", errors="replace")[:120000]
        content = [{"type": "text", "text": f"{prompt}\n\nNotice content:\n{text}"}]
    else:
        raise UnsupportedNoticeFile(f"AI analysis is not configured for .{kind or 'unknown'} files")

    response = _client().chat.completions.create(
        model=OPENAI_MODEL,
        temperature=0.2,
        max_tokens=700,
        messages=[{"role": "user", "content": content}],
    )
    raw = (response.choices[0].message.content or "").strip()
    if raw.startswith("```json"):
        raw = raw[7:]
    elif raw.startswith("```"):
        raw = raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    data = json.loads(raw.strip())

    allowed = ["subject_code", "subject_name", "degree_programme", "semester_exam", "deadline", "summary"]
    return {key: data.get(key) for key in allowed}
