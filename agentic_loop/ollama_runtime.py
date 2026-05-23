import json
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable

from .model_selection import DEFAULT_OLLAMA_HOST, ModelSelection


class OllamaRuntimeError(RuntimeError):
    pass


PrintFn = Callable[[str], None]
PromptFn = Callable[[str], str]


def list_ollama_models(host: str = DEFAULT_OLLAMA_HOST, timeout_s: float = 5.0) -> set[str]:
    url = f"{host.rstrip('/')}/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise OllamaRuntimeError(f"Ollama HTTP {exc.code} while checking models: {body}") from exc
    except urllib.error.URLError as exc:
        raise OllamaRuntimeError(f"Could not reach Ollama at {host}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise OllamaRuntimeError("Ollama returned invalid JSON while checking models.") from exc

    names: set[str] = set()
    for item in data.get("models", []):
        if isinstance(item, str) and item.strip():
            names.add(item.strip())
        if isinstance(item, dict):
            for key in ("name", "model"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    names.add(value.strip())
    return names


def pull_ollama_model(
    model: str,
    host: str = DEFAULT_OLLAMA_HOST,
    timeout_s: float = 1200.0,
    print_fn: PrintFn = print,
) -> None:
    request = urllib.request.Request(
        f"{host.rstrip('/')}/api/pull",
        data=json.dumps({"name": model, "stream": True}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            last_status = ""
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("error"):
                    raise OllamaRuntimeError(str(event["error"]))
                status = event.get("status")
                if isinstance(status, str) and status and status != last_status:
                    print_fn(f"ollama: {status}")
                    last_status = status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise OllamaRuntimeError(f"Ollama HTTP {exc.code} while pulling {model}: {body}") from exc
    except urllib.error.URLError as exc:
        raise OllamaRuntimeError(f"Could not reach Ollama at {host}: {exc.reason}") from exc


def ollama_model_installed(model: str, installed_models: Iterable[str]) -> bool:
    requested = model.strip()
    installed = {item.strip() for item in installed_models if item.strip()}
    if requested in installed:
        return True
    return ":" not in requested and f"{requested}:latest" in installed


def ensure_ollama_model_available(
    selection: ModelSelection,
    *,
    prompt_fn: PromptFn | None = None,
    print_fn: PrintFn = print,
    list_models_fn: Callable[[str], Iterable[str]] | None = None,
    pull_model_fn: Callable[[str, str, PrintFn], None] | None = None,
) -> bool:
    if selection.provider != "ollama" or not selection.model_name:
        return True

    model = selection.model_name
    host = selection.ollama_host or DEFAULT_OLLAMA_HOST
    prompt = prompt_fn or input
    list_models = list_models_fn or list_ollama_models
    pull_model = pull_model_fn or _pull_model_with_print

    try:
        installed_models = list_models(host)
    except OllamaRuntimeError as exc:
        print_fn(f"Could not check Ollama models: {exc}")
        print_fn(f"Start Ollama, or pull the model later with: ollama pull {model}")
        return False

    if ollama_model_installed(model, installed_models):
        return True

    print_fn(f"Ollama model is not installed: {model}")
    if not _confirm(f"Download {model} now? [Y/n] ", prompt):
        print_fn(f"Skipping model download. Pull later with: ollama pull {model}")
        return False

    print_fn(f"Pulling Ollama model: {model}")
    try:
        pull_model(model, host, print_fn)
    except OllamaRuntimeError as exc:
        print_fn(f"Could not pull {model}: {exc}")
        print_fn(f"Retry later with: ollama pull {model}")
        return False
    return True


def _pull_model_with_print(model: str, host: str, print_fn: PrintFn) -> None:
    pull_ollama_model(model, host=host, print_fn=print_fn)


def _confirm(prompt: str, prompt_fn: PromptFn) -> bool:
    try:
        answer = prompt_fn(prompt).strip().lower()
    except EOFError:
        return False
    if not answer:
        return True
    return answer in {"y", "yes"}
