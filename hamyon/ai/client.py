"""Gemini bilan ishlash: tuzilmali javob, qayta urinish, zaxira model, jurnal."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, ValidationError

from hamyon.ai import prompts
from hamyon.ai.schemas import ParseResult
from hamyon.config import settings
from hamyon.db.database import Database

log = logging.getLogger(__name__)


class AIError(RuntimeError):
    """AI javob bera olmadi (limit, tarmoq, buzuq javob)."""


class AIClient:
    def __init__(self, db: Database | None = None, api_key: str | None = None,
                 model: str | None = None, fallback_model: str | None = None):
        key = api_key or settings.gemini_api_key
        if not key:
            raise AIError("GEMINI_API_KEY berilmagan")
        self.client = genai.Client(api_key=key)
        fallbacks = (fallback_model or settings.gemini_fallback_model).split(",")
        self.models = [m.strip() for m in dict.fromkeys([model or settings.gemini_model, *fallbacks]) if m.strip()]
        self.db = db

    # ------------------------------------------------------------------ low level
    async def _generate(self, *, purpose: str, system: str, contents: list[Any],
                        schema: type[BaseModel] | None, temperature: float,
                        member_id: int | None, timeout: float) -> tuple[str, Any]:
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            response_mime_type="application/json" if schema else "text/plain",
            response_schema=schema,
        )
        last_exc: Exception | None = None
        for model in self.models:
            for attempt in range(2):
                started = time.monotonic()
                try:
                    resp = await asyncio.wait_for(
                        self.client.aio.models.generate_content(model=model, contents=contents, config=config),
                        timeout=timeout,
                    )
                    text = resp.text or ""
                    parsed = None
                    if schema:
                        parsed = resp.parsed if isinstance(resp.parsed, schema) else schema.model_validate_json(text)
                    await self._log(member_id, purpose, model, contents, text, True, started)
                    return text, parsed
                except genai_errors.APIError as exc:
                    last_exc = exc
                    code = getattr(exc, "code", None)
                    await self._log(member_id, purpose, model, contents, f"APIError {code}: {exc}", False, started)
                    log.warning("Gemini %s xato (%s, urinish %s): %s", model, code, attempt + 1, exc)
                    if code in (429, 500, 502, 503, 504) and attempt == 0:
                        await asyncio.sleep(1.5)
                        continue
                    break  # boshqa modelga o'tamiz
                except asyncio.TimeoutError as exc:
                    last_exc = exc
                    await self._log(member_id, purpose, model, contents, "TimeoutError", False, started)
                    log.warning("Gemini %s %ss ichida javob bermadi - keyingi modelga o'tamiz", model, timeout)
                    break
                except (ValidationError, json.JSONDecodeError, ValueError) as exc:
                    last_exc = exc
                    await self._log(member_id, purpose, model, contents, f"{type(exc).__name__}: {exc}", False, started)
                    log.warning("Gemini %s javobi yaroqsiz (urinish %s): %s", model, attempt + 1, exc)
                    if attempt == 0:
                        continue
                    break
                except Exception as exc:  # tarmoq va h.k.
                    last_exc = exc
                    await self._log(member_id, purpose, model, contents, f"{type(exc).__name__}: {exc}", False, started)
                    log.exception("Gemini %s kutilmagan xato", model)
                    break
        raise AIError(str(last_exc) if last_exc else "AI javob bermadi")

    async def _log(self, member_id, purpose, model, contents, output, ok, started) -> None:
        if not self.db or not self.db.conn:
            return
        text_parts = []
        for c in contents:
            if isinstance(c, str):
                text_parts.append(c)
            else:
                text_parts.append("<media>")
        try:
            await self.db.execute(
                "INSERT INTO ai_log (member_id, purpose, model, input, output, ok, latency_ms) VALUES (?,?,?,?,?,?,?)",
                (member_id, purpose, model, "\n".join(text_parts)[-6000:], str(output)[:6000], int(ok),
                 int((time.monotonic() - started) * 1000)),
            )
        except Exception:
            log.debug("ai_log yozilmadi", exc_info=True)

    # ------------------------------------------------------------------ high level
    async def parse(self, context: str, text: str | None = None, *, audio: bytes | None = None,
                    audio_mime: str = "audio/ogg", image: bytes | None = None, image_mime: str = "image/jpeg",
                    member_id: int | None = None) -> ParseResult:
        system = prompts.PARSER_SYSTEM
        contents: list[Any] = [context]
        purpose = "parse"
        if audio is not None:
            system += "\n\n" + prompts.VOICE_ADDENDUM
            contents.append(types.Part.from_bytes(data=audio, mime_type=audio_mime))
            contents.append("=== XABAR ===\n(ovozli xabar yuqorida)" + (f"\nIzoh: {text}" if text else ""))
            purpose = "voice"
        elif image is not None:
            system += "\n\n" + prompts.RECEIPT_ADDENDUM
            contents.append(types.Part.from_bytes(data=image, mime_type=image_mime))
            contents.append("=== XABAR ===\n(rasm yuqorida)" + (f"\nRasm izohi (caption): {text}" if text else ""))
            purpose = "photo"
        else:
            contents.append(f"=== XABAR ===\n{text}")
        timeout = 75 if (audio or image) else 30
        _, parsed = await self._generate(purpose=purpose, system=system, contents=contents,
                                         schema=ParseResult, temperature=0.1, member_id=member_id, timeout=timeout)
        return parsed

    async def correct(self, context: str, entries: list[dict], correction: str,
                      member_id: int | None = None) -> ParseResult:
        payload = (
            f"{context}\n\n=== JORIY YOZUVLAR (JSON) ===\n{json.dumps(entries, ensure_ascii=False, indent=1)}"
            f"\n\n=== TUZATISH ===\n{correction}"
        )
        system = prompts.CORRECTION_SYSTEM + "\n\n--- Reference: full parsing rules ---\n" + prompts.PARSER_SYSTEM
        _, parsed = await self._generate(purpose="correct", system=system, contents=[payload],
                                         schema=ParseResult, temperature=0.1, member_id=member_id, timeout=45)
        return parsed

    async def answer(self, question: str, facts: dict, member_id: int | None = None) -> str:
        payload = f"SAVOL: {question}\n\nFACTS:\n{json.dumps(facts, ensure_ascii=False, indent=1)}"
        text, _ = await self._generate(purpose="answer", system=prompts.ANSWER_SYSTEM, contents=[payload],
                                       schema=None, temperature=0.3, member_id=member_id, timeout=45)
        return text.strip()

    async def insight(self, facts: dict) -> str:
        payload = f"FACTS:\n{json.dumps(facts, ensure_ascii=False, indent=1)}"
        text, _ = await self._generate(purpose="insight", system=prompts.INSIGHT_SYSTEM, contents=[payload],
                                       schema=None, temperature=0.4, member_id=None, timeout=45)
        return text.strip()
