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


# --- Mirror exclusion (hardware safety policy) ---

@pytest.fixture
def reg_with_mirror(reg):
    """Registry with lmstudio-mac mirror online alongside real backends."""
    reg._backends["lmstudio-mac"] = _online(
        "lmstudio-mac", "http://localhost:1234/v1",
        BackendKind.LMSTUDIO, ["qwen3.5-27b-claude-4.6-opus-reasoning-distilled-v2"],
    )
    return reg


def test_mirror_never_selected_for_mac_tier(reg_with_mirror):
    """Mac tier must use Ollama only — lmstudio-mac excluded even when it's LMSTUDIO."""
    b = select_backend(reg_with_mirror, model_hint=None, task_type="coding", target_tier="mac")
    assert b.name == "ollama-local"


def test_mirror_never_selected_for_shared_coding(reg_with_mirror):
    """shared+coding prefers LMSTUDIO, but must pick lmstudio-win, not the mirror."""
    b = select_backend(reg_with_mirror, model_hint=None, task_type="coding", target_tier="shared")
    assert b.name == "lmstudio-win"


def test_mirror_excluded_even_when_only_lmstudio_online():
    """If lmstudio-win is offline, shared+coding should fall back to Ollama, never the mirror."""
    r = BackendRegistry()
    r._backends["ollama-local"] = _online("ollama-local", "http://localhost:11434/v1",
                                          BackendKind.OLLAMA, ["qwen3.5:9b-nvfp4"])
    r._backends["lmstudio-mac"] = _online("lmstudio-mac", "http://localhost:1234/v1",
                                          BackendKind.LMSTUDIO, ["heavy-model"])
    b = select_backend(r, model_hint=None, task_type="coding", target_tier="shared")
    assert b.name == "ollama-local"  # fallback, not the mirror


def test_model_hint_skips_mirror():
    """model_hint must not route to a mirror backend even if the model appears there."""
    r = BackendRegistry()
    r._backends["lmstudio-mac"] = _online("lmstudio-mac", "http://localhost:1234/v1",
                                          BackendKind.LMSTUDIO,
                                          ["qwen3.5-27b-claude-4.6-opus-reasoning-distilled-v2"])
    with pytest.raises(NoBackendAvailableError):
        select_backend(r, model_hint="qwen3.5-27b-claude-4.6-opus-reasoning-distilled-v2",
                       task_type="reasoning", target_tier="shared")
