"""Resolução do provider conforme configuração."""

from __future__ import annotations

from modernizer.config import get_settings
from modernizer.llm.anthropic_provider import AnthropicProvider
from modernizer.llm.base import LLMProvider
from modernizer.llm.gemini_provider import GeminiProvider
from modernizer.llm.openai_provider import OpenAIProvider

# Default por provider quando o usuário trocar via env sem passar modelo explícito.
DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-sonnet-4-5-20250929",
    "openai": "gpt-4o",
    "gemini": "gemini-2.5-pro",
}


def get_provider(name: str | None = None, model: str | None = None) -> LLMProvider:
    settings = get_settings()
    provider_name = (name or settings.llm_provider).lower()
    # Se o caller trocou de provider mas não informou modelo, usa o default
    # do provider escolhido em vez do default global (que pode ser de outro).
    if model is None and name is not None and name.lower() != settings.llm_provider.lower():
        resolved_model = DEFAULT_MODELS.get(provider_name, settings.llm_model)
    else:
        resolved_model = model or settings.llm_model

    if provider_name == "anthropic":
        return AnthropicProvider(settings.anthropic_api_key, resolved_model)
    if provider_name == "openai":
        return OpenAIProvider(settings.openai_api_key, resolved_model)
    if provider_name == "gemini":
        return GeminiProvider(settings.google_api_key, resolved_model)
    raise ValueError(f"Provider LLM desconhecido: {provider_name}")
