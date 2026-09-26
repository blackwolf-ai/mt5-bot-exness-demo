"""Claude assistant: chat with memory, vision, documents and live web search."""
from __future__ import annotations

import base64
import logging

import anthropic

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are the owner's personal assistant inside Telegram. The owner is a CFD/forex trader "
    "who runs an MT5 account at Exness. Be concise and practical; replies are read on a phone, "
    "so prefer short paragraphs and simple lists, and avoid tables. You may use web search for "
    "anything time-sensitive (news, prices, economic calendar) and say where facts came from. "
    "When discussing trades, be clear about risk and never present a trade idea as certain."
)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AIDisabled(RuntimeError):
    pass


class AIClient:
    def __init__(self, api_key: str, model: str, effort: str, web_search: bool):
        self.enabled = bool(api_key)
        self.model = model
        self.effort = effort
        self.web_search = web_search
        self._client = anthropic.AsyncAnthropic(api_key=api_key) if api_key else None

    async def complete(self, messages: list[dict], system: str = SYSTEM_PROMPT, web: bool | None = None) -> str:
        if not self._client:
            raise AIDisabled("ANTHROPIC_API_KEY is not set, so AI features are off.")
        use_web = self.web_search if web is None else web
        kwargs: dict = dict(
            model=self.model,
            max_tokens=16000,
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": self.effort},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
        if use_web:
            kwargs["tools"] = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}]

        convo = list(messages)
        response = None
        for _ in range(4):  # server tools may pause a long turn; resume it a few times
            response = await self._client.beta.messages.create(messages=convo, **kwargs)
            if response.stop_reason != "pause_turn":
                break
            convo = convo + [{"role": "assistant", "content": response.content}]

        if response.stop_reason == "refusal":
            return "I can't help with that request."
        text = "".join(block.text for block in response.content if block.type == "text").strip()
        if response.stop_reason == "max_tokens":
            text += "\n\n[reply was cut off — ask me to continue]"
        return text or "(no text in reply)"

    async def chat(self, history: list[dict], user_text: str) -> str:
        return await self.complete(history + [{"role": "user", "content": user_text}])

    async def describe_image(self, image: bytes, media_type: str, prompt: str) -> str:
        content = [
            {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                         "data": base64.standard_b64encode(image).decode()}},
            {"type": "text", "text": prompt or "Describe this image. If it is a trading chart, "
                                               "analyse trend, key levels and patterns."},
        ]
        return await self.complete([{"role": "user", "content": content}], web=False)

    async def analyse_pdf(self, pdf: bytes, prompt: str) -> str:
        content = [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                            "data": base64.standard_b64encode(pdf).decode()}},
            {"type": "text", "text": prompt or "Summarise this document and list the key points."},
        ]
        return await self.complete([{"role": "user", "content": content}], web=False)

    async def one_shot(self, instruction: str, text: str, web: bool = False) -> str:
        return await self.complete([{"role": "user", "content": f"{instruction}\n\n{text}"}], web=web)


def friendly_error(exc: Exception) -> str:
    if isinstance(exc, AIDisabled):
        return str(exc)
    if isinstance(exc, anthropic.AuthenticationError):
        return "Claude API key is invalid. Check ANTHROPIC_API_KEY."
    if isinstance(exc, anthropic.RateLimitError):
        return "Claude is rate-limited right now, try again in a minute."
    if isinstance(exc, anthropic.BadRequestError):
        return f"Claude rejected the request: {exc.message}"
    if isinstance(exc, anthropic.APIStatusError):
        return f"Claude API error ({exc.status_code}). Try again shortly."
    if isinstance(exc, anthropic.APIConnectionError):
        return "Can't reach the Claude API (network problem)."
    log.exception("Unexpected AI error", exc_info=exc)
    return "Something went wrong talking to Claude."
