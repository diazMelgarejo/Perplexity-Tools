import pytest
from datetime import datetime, timezone
from perpetua.discovery.backend import Backend, BackendKind, BackendHealth
from perpetua.discovery.registry import BackendRegistry
from perpetua.discovery.selector import select_backend
from perpetua.discovery.errors import NoBackendAvailableError

NOW = datetime.now(timezone.utc)

def _online(name, url, kind, models):
    return Backend(name, url, kind, tuple(models), BackendHealth.ONLINE, NOW)


@pytest.fixture
def reg():
    r = BackendRegistry()
    r._backends["ollama-local"] = _online("ollama-local", "http://localhost:11434/v1",
                                          BackendKind.OLLAMA, ["qwen3.5:9b-nvfp4"])
    r._backends["lmstudio-win"] = _online("lmstudio-win", "http://192.168.254.103:1234/v1",
                                          BackendKind.LMSTUDIO, ["qwen3-coder-30b"])
    return r


def test_model_hint_wins_over_tier(reg):
    b = select_backend(reg, model_hint="qwen3-coder-30b", task_type="reasoning", target_tier="mac")
    assert b.name == "lmstudio-win"


def test_coding_on_shared_prefers_windows(reg):
    b = select_backend(reg, model_hint=None, task_type="coding", target_tier="shared")
    assert b.name == "lmstudio-win"


def test_reasoning_on_shared_prefers_mac(reg):
    b = select_backend(reg, model_hint=None, task_type="reasoning", target_tier="shared")
    assert b.name == "ollama-local"


def test_no_match_raises(reg):
    reg._backends.clear()
    with pytest.raises(NoBackendAvailableError):
        select_backend(reg, model_hint=None, task_type="coding", target_tier="shared")
