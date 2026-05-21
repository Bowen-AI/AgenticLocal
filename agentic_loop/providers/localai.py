from .openai_compatible import OpenAICompatibleChatModel


class LocalAIChatModel(OpenAICompatibleChatModel):
    def __init__(
        self,
        model: str,
        host: str = "http://127.0.0.1:8080/v1",
        api_key: str | None = None,
        timeout_s: float = 120.0,
    ):
        base_url = host.rstrip("/")
        if not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"
        super().__init__(
            model=model,
            base_url=base_url,
            api_key=api_key,
            timeout_s=timeout_s,
        )
