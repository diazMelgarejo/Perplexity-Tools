from __future__ import annotations

from orchestrator import fastapi_app


def test_health_uses_plain_string_defaults(monkeypatch):
    captured = {}

    def fake_backend_health_map(*, ollama_host, lm_studio_host, mlx_host):
        captured["ollama_host"] = ollama_host
        captured["lm_studio_host"] = lm_studio_host
        captured["mlx_host"] = mlx_host
        return {"ok": True}

    monkeypatch.setattr(fastapi_app, "backend_health_map", fake_backend_health_map)
    monkeypatch.setattr(
        fastapi_app,
        "load_runtime_payload",
        lambda: {
            "gateway": {"gateway_ready": True},
            "routing": {"distributed": True},
        },
    )

    response = fastapi_app.health()

    assert response["status"] == "ok"
    assert response["runtime"] == {
        "available": True,
        "gateway_ready": True,
        "distributed": True,
    }
    assert captured == {
        "ollama_host": "http://127.0.0.1:11434",
        "lm_studio_host": "http://127.0.0.1:1234",
        "mlx_host": "http://127.0.0.1:8081",
    }
