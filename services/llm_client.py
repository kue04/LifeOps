from __future__ import annotations

import json
from typing import Any

from config import settings


class LLMClient:
    def json_complete(self, system_prompt: str, user_input: str) -> dict[str, Any]:
        if settings.llm_mode == "deepseek":
            return self._deepseek_json(system_prompt, user_input)
        if settings.llm_mode == "openai":
            return self._openai_json(system_prompt, user_input)
        return {"mode": "mock", "content": None}

    def _deepseek_json(self, system_prompt: str, user_input: str) -> dict[str, Any]:
        if not settings.deepseek_api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is required when LIFEOPS_LLM_MODE=deepseek")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Install openai package before enabling DeepSeek mode") from exc

        client = OpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url)
        response = client.chat.completions.create(
            model=settings.deepseek_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ],
            response_format={"type": "json_object"},
            stream=False,
        )
        text = response.choices[0].message.content or "{}"
        return json.loads(text)

    def _openai_json(self, system_prompt: str, user_input: str) -> dict[str, Any]:
        if settings.llm_mode != "openai":
            return {"mode": "mock", "content": None}
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required when LIFEOPS_LLM_MODE=openai")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Install openai package before enabling OpenAI mode") from exc

        client = OpenAI(api_key=settings.openai_api_key)
        response = client.responses.create(
            model=settings.openai_model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ],
        )
        text = response.output_text
        return json.loads(text)


llm_client = LLMClient()
