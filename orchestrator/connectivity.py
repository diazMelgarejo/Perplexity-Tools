from __future__ import annotations

from typing import Any, Dict

import httpx


def _probe(url: str, timeout: float = 2.5) -> Dict[str, Any]:
    try:
        r = httpx.get(url, timeout=timeout)
        return {"ok": r.status_code < 400, "status_code": r.status_code, "url": url}
    except Exception as exc:
        return {"ok": False, "status_code": None, "url": url, "error": str(exc)}


def check_ollama(host: str = "http://127.0.0.1:11434") -> Dict[str, Any]:
    """Works for shared Ollama on Mac or Windows."""
    return _probe(f"{host.rstrip('/')}/api/tags")


def check_lm_studio(host: str = "http://127.0.0.1:1234") -> Dict[str, Any]:
    """LM Studio OpenAI-compatible endpoint on Mac or Windows."""
    return _probe(f"{host.rstrip('/')}/v1/models")


def check_mlx(host: str = "http://127.0.0.1:8081") -> Dict[str, Any]:
    """MLX server on Mac (mlx-lm serve)."""
    return _probe(f"{host.rstrip('/')}/v1/models")


def check_perplexity() -> Dict[str, Any]:
    return _probe("https://api.perplexity.ai")


def check_openrouter() -> Dict[str, Any]:
    return _probe("https://openrouter.ai/api/v1/models")


def check_anthropic() -> Dict[str, Any]:
    return _probe("https://api.anthropic.com")


def backend_health_map(
    ollama_host: str = "http://127.0.0.1:11434",
    lm_studio_host: str = "http://127.0.0.1:1234",
    mlx_host: str = "http://127.0.0.1:8081",
) -> Dict[str, Dict[str, Any]]:
    """One-shot health snapshot for all configured backends."""
    return {
        "ollama": check_ollama(ollama_host),
        "lm_studio": check_lm_studio(lm_studio_host),
        "mlx": check_mlx(mlx_host),
        "perplexity": check_perplexity(),
        "openrouter": check_openrouter(),
        "anthropic": check_anthropic(),
    }
