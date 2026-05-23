from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from typing import Any, Protocol, runtime_checkable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_GEMINI_LIVE_MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"
GEMINI_LIVE_TOKEN_URL = "https://generativelanguage.googleapis.com/v1alpha/auth_tokens"
GEMINI_LIVE_WEBSOCKET_URL = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1alpha."
    "GenerativeService.BidiGenerateContentConstrained"
)
VOICE_TOKEN_PURPOSES = {"input", "output"}


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


class GeminiLiveVoiceAdapter:
    """Gemini Live browser audio adapter around the local text agent loop."""

    def __init__(self, model: str = DEFAULT_GEMINI_LIVE_MODEL):
        self.model = model

    def describe(self) -> VoiceAdapterInfo:
        return VoiceAdapterInfo(
            name="gemini-live",
            realtime=True,
            provider_examples=("Gemini Live Voice",),
            notes=(
                "Gemini Live handles browser audio while agentic-loop keeps "
                "tools, rules, memory, and transcripts."
            ),
        )


class GeminiLiveTokenError(RuntimeError):
    """Raised when a Gemini Live ephemeral token cannot be minted."""


class GeminiLiveTokenClient:
    """Minimal stdlib client for Gemini Live ephemeral auth tokens."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_GEMINI_LIVE_MODEL,
        token_url: str = GEMINI_LIVE_TOKEN_URL,
        websocket_url: str = GEMINI_LIVE_WEBSOCKET_URL,
        timeout_s: float = 10.0,
        urlopen_fn: Any = None,
        now_fn: Any = None,
    ):
        self.api_key = (
            api_key
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
        )
        self.model = model
        self.token_url = token_url
        self.websocket_url = websocket_url
        self.timeout_s = timeout_s
        self.urlopen_fn = urlopen_fn or urlopen
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    def available(self) -> bool:
        return bool(self.api_key)

    def unavailable_reason(self) -> str | None:
        if self.available():
            return None
        return "Set GEMINI_API_KEY or GOOGLE_API_KEY to enable Gemini Live voice."

    def create_token(
        self,
        purpose: str,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise GeminiLiveTokenError(
                self.unavailable_reason() or "Gemini API key is missing."
            )
        payload = self.token_request_payload(purpose)
        url = self._token_endpoint()
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            response = self.urlopen_fn(request, timeout=self.timeout_s)
            try:
                raw = response.read().decode("utf-8")
            finally:
                close = getattr(response, "close", None)
                if close is not None:
                    close()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GeminiLiveTokenError(
                f"Gemini token request failed with HTTP {exc.code}: {detail}"
            ) from exc
        except URLError as exc:
            raise GeminiLiveTokenError(f"Gemini token request failed: {exc.reason}") from exc
        except OSError as exc:
            raise GeminiLiveTokenError(f"Gemini token request failed: {exc}") from exc

        data = json.loads(raw or "{}")
        token = data.get("name")
        if not token and isinstance(data.get("authToken"), dict):
            token = data["authToken"].get("name")
        if not isinstance(token, str) or not token:
            raise GeminiLiveTokenError("Gemini token response did not include a token name.")
        return {
            "token": token,
            "websocket_url": self.websocket_url,
            "model": self.model,
            "purpose": purpose,
            "session_id": session_id,
            "expire_time": payload["expireTime"],
            "new_session_expire_time": payload["newSessionExpireTime"],
            "setup": payload["bidiGenerateContentSetup"],
        }

    def token_request_payload(self, purpose: str) -> dict[str, Any]:
        if purpose not in VOICE_TOKEN_PURPOSES:
            allowed = ", ".join(sorted(VOICE_TOKEN_PURPOSES))
            raise ValueError(f"purpose must be one of: {allowed}")
        now = self.now_fn()
        expire_time = _utc_timestamp(now + timedelta(minutes=30))
        new_session_expire_time = _utc_timestamp(now + timedelta(minutes=1))
        return {
            "uses": 1,
            "expireTime": expire_time,
            "newSessionExpireTime": new_session_expire_time,
            "bidiGenerateContentSetup": self._live_setup(purpose),
        }

    def _token_endpoint(self) -> str:
        separator = "&" if "?" in self.token_url else "?"
        return f"{self.token_url}{separator}{urlencode({'key': self.api_key})}"

    def _live_setup(self, purpose: str) -> dict[str, Any]:
        setup: dict[str, Any] = {
            "model": _model_resource_name(self.model),
            "generationConfig": {
                "responseModalities": ["TEXT" if purpose == "input" else "AUDIO"],
                "temperature": 0,
            },
            "systemInstruction": {
                "parts": [
                    {
                        "text": (
                            "Transcribe the user's speech. Return only speech transcription; "
                            "do not answer the user."
                            if purpose == "input"
                            else "Speak exactly the assistant text provided by the local agent. "
                            "Do not add, remove, summarize, or answer independently."
                        )
                    }
                ]
            },
        }
        if purpose == "input":
            setup["inputAudioTranscription"] = {}
        else:
            setup["outputAudioTranscription"] = {}
        return setup


def _model_resource_name(model: str) -> str:
    if model.startswith("models/"):
        return model
    return f"models/{model}"


def _utc_timestamp(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
