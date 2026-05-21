from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class VoiceAdapterInfo:
    name: str
    realtime: bool
    provider_examples: tuple[str, ...]
    notes: str


@runtime_checkable
class VoiceAdapter(Protocol):
    def describe(self) -> VoiceAdapterInfo:
        ...


class BrowserSpeechVoiceAdapter:
    """Current local browser voice path: Web Speech API around the text agent."""

    def describe(self) -> VoiceAdapterInfo:
        return VoiceAdapterInfo(
            name="browser-web-speech",
            realtime=False,
            provider_examples=("SpeechRecognition", "speechSynthesis"),
            notes="Browser STT/TTS sends text turns through the normal /chat session.",
        )


class RealtimeVoiceAdapterSpec:
    """Provider-neutral placeholder for live audio adapters."""

    def __init__(self, provider_name: str, config: dict[str, Any] | None = None):
        self.provider_name = provider_name
        self.config = config or {}

    def describe(self) -> VoiceAdapterInfo:
        return VoiceAdapterInfo(
            name=self.provider_name,
            realtime=True,
            provider_examples=("Gemini Live Voice", "OpenAI Realtime"),
            notes="Realtime audio adapters must still route tool and memory work through policy.",
        )
