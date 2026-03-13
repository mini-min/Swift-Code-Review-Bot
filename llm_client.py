"""
LLM 클라이언트 — Gemini / OpenAI / Claude

지원 프로바이더:
  gemini    (무료) Google Gemini 2.5 Flash
  openai    (유료) GPT-4.1
  anthropic (유료) Claude Sonnet 4
"""

import os
from typing import Optional

PROVIDERS = {
    "gemini": {
        "name": "Google Gemini",
        "default_model": "gemini-2.5-flash",
        "free": True,
        "key_env": "GEMINI_API_KEY",
        "key_url": "https://aistudio.google.com/apikey",
    },
    "openai": {
        "name": "OpenAI",
        "default_model": "gpt-4.1",
        "free": False,
        "key_env": "OPENAI_API_KEY",
        "key_url": "https://platform.openai.com/api-keys",
    },
    "anthropic": {
        "name": "Anthropic Claude",
        "default_model": "claude-sonnet-4-20250514",
        "free": False,
        "key_env": "ANTHROPIC_API_KEY",
        "key_url": "https://console.anthropic.com",
    },
}


class LLMClient:
    def __init__(self, provider: str, api_key: str, model: Optional[str] = None):
        self.provider = provider.lower()
        self.api_key = api_key

        info = PROVIDERS.get(self.provider)
        if not info:
            raise ValueError(f"지원하지 않는 프로바이더: {provider}. 사용 가능: gemini, openai, anthropic")

        self.model = model or info["default_model"]
        self.provider_name = info["name"]

    def chat(self, system_prompt: str, user_message: str, max_tokens: int = 4096) -> str:
        if self.provider == "anthropic":
            return self._call_anthropic(system_prompt, user_message, max_tokens)
        else:
            return self._call_openai_compatible(system_prompt, user_message, max_tokens)

    def _call_openai_compatible(self, system_prompt: str, user_message: str, max_tokens: int) -> str:
        """Gemini와 OpenAI 모두 OpenAI 호환 API를 사용합니다."""
        import httpx

        base_urls = {
            "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
            "openai": "https://api.openai.com/v1",
        }

        resp = httpx.post(
            f"{base_urls[self.provider]}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def _call_anthropic(self, system_prompt: str, user_message: str, max_tokens: int) -> str:
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)
        resp = client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        return resp.content[0].text


def create_llm_client(provider: str, model: Optional[str] = None) -> LLMClient:
    """환경변수에서 API 키를 읽어 클라이언트를 생성합니다.

    키 탐색 순서:
      1. 프로바이더 전용 키 (GEMINI_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY)
      2. 범용 키 (AI_API_KEY) — 하나만 쓸 때 편의용
    """
    info = PROVIDERS.get(provider.lower())
    if not info:
        raise ValueError(f"지원하지 않는 프로바이더: {provider}")

    api_key = os.environ.get(info["key_env"]) or os.environ.get("AI_API_KEY")

    if not api_key:
        raise ValueError(
            f"{info['name']} API 키가 없습니다.\n"
            f"GitHub Secret에 {info['key_env']} 를 등록하세요.\n"
            f"키 발급: {info['key_url']}"
        )

    return LLMClient(provider=provider, api_key=api_key, model=model)
