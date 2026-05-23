import argparse
import json
import urllib.request
from urllib.parse import urlparse

from .model_selection import DEFAULT_OLLAMA_HOST, ModelSelection, provider_registry
from .ollama_runtime import ensure_ollama_model_available


def run_client(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="agentic-loop client")
    parser.add_argument("message", nargs="?", help="Message or goal to send to the running server.")
    parser.add_argument("--server", default="http://127.0.0.1:8765")
    parser.add_argument("--endpoint", choices=["chat", "run"], default="chat")
    parser.add_argument("--session-id", default=None)
    parser.add_argument(
        "--provider",
        choices=["rule", "ollama", "openai", "openai-compatible", "gemini", "localai"],
        default=None,
    )
    parser.add_argument("--model", default=None)
    parser.add_argument("--ollama-host", default=None)
    parser.add_argument("--api-base", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--workflow", default=None)
    parser.add_argument("--rule", action="append", default=[])
    parser.add_argument("--no-rule", action="append", default=[])
    parser.add_argument("--models", action="store_true", help="List server model/provider registry.")
    parser.add_argument("--json", action="store_true", help="Print raw JSON response.")
    args = parser.parse_args(argv)

    base_url = args.server.rstrip("/")
    if args.models:
        payload = _get_json(f"{base_url}/registry/models")
        print(json.dumps(payload, indent=2, sort_keys=True) if args.json else _render_models(payload))
        return 0

    if not args.message:
        parser.error("message is required unless --models is used")

    payload = {
        "message": args.message,
        "session_id": args.session_id,
        "workflow": args.workflow,
        "rules": {"enable": args.rule, "disable": args.no_rule},
    }
    if any([args.provider, args.model, args.ollama_host, args.api_base, args.api_key]):
        payload["model"] = {
            "provider": args.provider,
            "name": args.model,
            "ollama_host": args.ollama_host,
            "api_base": args.api_base,
            "api_key": args.api_key,
        }
    if (
        args.provider == "ollama"
        and args.model is not None
        and _should_preflight_ollama(base_url, args.ollama_host)
    ):
        model_selection = ModelSelection.from_values(
            provider="ollama",
            model_name=args.model,
            ollama_host=args.ollama_host or DEFAULT_OLLAMA_HOST,
        )
        if not ensure_ollama_model_available(model_selection):
            return 1

    response = _post_json(f"{base_url}/{args.endpoint}", payload)
    if args.json:
        print(json.dumps(response, indent=2, sort_keys=True))
    else:
        if response.get("session_id"):
            print(f"session_id: {response['session_id']}")
        if response.get("model"):
            model = response["model"]
            rendered_model = model.get("model") or "(none)"
            print(f"model: {model.get('provider')} {rendered_model}")
        print(response.get("final_answer", response))
    return 0


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_json(url: str, payload: dict) -> dict:
    cleaned = _drop_none(payload)
    request = urllib.request.Request(
        url,
        data=json.dumps(cleaned).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def _drop_none(value):
    if isinstance(value, dict):
        return {key: _drop_none(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_drop_none(item) for item in value]
    return value


def _should_preflight_ollama(server_url: str, ollama_host: str | None) -> bool:
    if ollama_host:
        return True
    host = (urlparse(server_url).hostname or "").lower()
    return host in {"", "localhost", "127.0.0.1", "::1"}


def _render_models(payload: dict) -> str:
    lines = ["Providers:"]
    for item in payload.get("providers") or provider_registry():
        required = "model required" if item.get("model_required") else "model optional"
        api_base = "api_base required" if item.get("api_base_required") else "api_base optional"
        lines.append(f"- {item['provider']}: {required}, {api_base}")
    current = payload.get("current") or {}
    lines.append(
        f"Current: {current.get('provider', 'rule')} {current.get('model') or '(none)'}"
    )
    return "\n".join(lines)
