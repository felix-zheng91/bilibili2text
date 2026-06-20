from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web-ui"))

from backend.routes import runtime_routes  # noqa: E402
from backend.schemas import OpenPublicCustomLlmTestRequest  # noqa: E402


def test_open_public_custom_llm_test_route_calls_litellm(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(runtime_routes, "is_open_public_mode", lambda: True)

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="hello"))]
        )

    monkeypatch.setattr(runtime_routes, "completion", fake_completion)

    response = runtime_routes.test_open_public_custom_llm(
        OpenPublicCustomLlmTestRequest(
            base_url="https://llm.example.com/v1/",
            api_key="sk-custom",
            model="custom-model",
        )
    )

    assert response.ok is True
    assert response.content == "hello"
    assert captured["model"] == "openai/custom-model"
    assert captured["api_base"] == "https://llm.example.com/v1"
    assert captured["api_key"] == "sk-custom"
    assert captured["messages"] == [{"role": "user", "content": "hi"}]
