from dataclasses import dataclass
from typing import Any


DEFAULT_INTERACTIVE_PROVIDER = "ollama"
DEFAULT_INTERACTIVE_MODEL = "qwen3.5:4b-mlx"
DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"


PROVIDER_REGISTRY = [
    {
        "provider": "rule",
        "label": "Rule-based local planner",
        "description": "Deterministic dependency-free planner for tests, demos, and offline checks.",
        "model_required": False,
        "api_base_required": False,
        "api_key_supported": False,
    },
    {
        "provider": "ollama",
        "label": "Ollama",
        "description": "Local Ollama chat model selected at request time.",
        "model_required": True,
        "api_base_required": False,
        "api_key_supported": False,
        "host_field": "ollama_host",
    },
    {
        "provider": "openai",
        "label": "OpenAI",
        "description": "OpenAI chat-completions-compatible API.",
        "model_required": True,
        "api_base_required": False,
        "api_key_supported": True,
        "default_api_base": "https://api.openai.com/v1",
    },
    {
        "provider": "openai-compatible",
        "label": "OpenAI-compatible",
        "description": "Any OpenAI-compatible chat completions endpoint, including compatible hosted APIs.",
        "model_required": True,
        "api_base_required": True,
        "api_key_supported": True,
    },
    {
        "provider": "gemini",
        "label": "Gemini OpenAI-compatible",
        "description": "Gemini or another Google-compatible OpenAI-style endpoint.",
        "model_required": True,
        "api_base_required": True,
        "api_key_supported": True,
    },
    {
        "provider": "localai",
        "label": "LocalAI",
        "description": "LocalAI OpenAI-compatible server.",
        "model_required": True,
        "api_base_required": False,
        "api_key_supported": True,
        "default_api_base": "http://127.0.0.1:8080/v1",
    },
]


PROVIDERS = {item["provider"] for item in PROVIDER_REGISTRY}


@dataclass(frozen=True)
class ModelSelection:
    provider: str = "rule"
    model_name: str | None = None
    ollama_host: str | None = None
    api_base: str | None = None
    api_key: str | None = None

    @classmethod
    def from_values(
        cls,
        provider: str | None = None,
        model_name: str | None = None,
        ollama_host: str | None = None,
        api_base: str | None = None,
        api_key: str | None = None,
    ) -> "ModelSelection":
        return cls(
            provider=(provider or "rule").strip(),
            model_name=_blank_to_none(model_name),
            ollama_host=_blank_to_none(ollama_host),
            api_base=_blank_to_none(api_base),
            api_key=_blank_to_none(api_key),
        ).validated()

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any] | None,
        fallback: "ModelSelection | None" = None,
    ) -> "ModelSelection":
        fallback = fallback or cls()
        if not payload:
            return fallback.validated()
        model_payload = payload.get("model")
        if isinstance(model_payload, dict):
            provider = model_payload.get("provider", fallback.provider)
            model_name = model_payload.get("name", model_payload.get("model", fallback.model_name))
            ollama_host = model_payload.get("ollama_host", fallback.ollama_host)
            api_base = model_payload.get("api_base", fallback.api_base)
            api_key = model_payload.get("api_key", fallback.api_key)
        else:
            provider = payload.get("provider", fallback.provider)
            model_name = payload.get("model", fallback.model_name)
            ollama_host = payload.get("ollama_host", fallback.ollama_host)
            api_base = payload.get("api_base", fallback.api_base)
            api_key = payload.get("api_key", fallback.api_key)
        return cls.from_values(
            provider=provider,
            model_name=model_name,
            ollama_host=ollama_host,
            api_base=api_base,
            api_key=api_key,
        )

    def with_fallback(self, fallback: "ModelSelection") -> "ModelSelection":
        return ModelSelection(
            provider=self.provider or fallback.provider,
            model_name=self.model_name or fallback.model_name,
            ollama_host=self.ollama_host or fallback.ollama_host,
            api_base=self.api_base or fallback.api_base,
            api_key=self.api_key or fallback.api_key,
        ).validated()

    def validated(self) -> "ModelSelection":
        if self.provider not in PROVIDERS:
            raise ValueError(f"unknown provider: {self.provider}")
        metadata = provider_metadata(self.provider)
        if metadata.get("model_required") and not self.model_name:
            raise ValueError(f"provider {self.provider} requires a model")
        if metadata.get("api_base_required") and not self.api_base:
            raise ValueError(f"provider {self.provider} requires api_base")
        return self

    def to_dict(self, include_secret: bool = False) -> dict[str, Any]:
        payload = {
            "provider": self.provider,
            "model": self.model_name,
            "ollama_host": self.ollama_host,
            "api_base": self.api_base,
            "api_key_configured": bool(self.api_key),
        }
        if include_secret:
            payload["api_key"] = self.api_key
        return payload


def provider_metadata(provider: str) -> dict[str, Any]:
    for item in PROVIDER_REGISTRY:
        if item["provider"] == provider:
            return dict(item)
    raise ValueError(f"unknown provider: {provider}")


def provider_registry() -> list[dict[str, Any]]:
    return [dict(item) for item in PROVIDER_REGISTRY]


def render_model_selection(selection: ModelSelection) -> str:
    model = selection.model_name or "(none)"
    return f"{selection.provider} {model}"


def parse_model_command(value: str, fallback: ModelSelection | None = None) -> ModelSelection:
    fallback = fallback or ModelSelection()
    parts = value.split()
    if not parts:
        return fallback
    data: dict[str, Any] = {}
    positional = []
    for part in parts:
        if "=" in part:
            key, item = part.split("=", 1)
            data[key.strip().replace("-", "_")] = item.strip()
        else:
            positional.append(part)

    if positional:
        data.setdefault("provider", positional[0])
    if len(positional) > 1:
        data.setdefault("model", positional[1])

    provider = data.get("provider", fallback.provider)
    provider_changed = provider != fallback.provider
    model_name = data.get("model", data.get("name"))
    if model_name is None and not provider_changed:
        model_name = fallback.model_name
    if model_name is None and provider_changed and provider == DEFAULT_INTERACTIVE_PROVIDER:
        model_name = DEFAULT_INTERACTIVE_MODEL

    return ModelSelection.from_values(
        provider=provider,
        model_name=model_name,
        ollama_host=data.get("ollama_host", fallback.ollama_host),
        api_base=data.get("api_base", None if provider_changed else fallback.api_base),
        api_key=data.get("api_key", None if provider_changed else fallback.api_key),
    )


def _blank_to_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
