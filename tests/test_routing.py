"""test_routing.py — Perpetua-Tools routing unit tests

Tests ModelRegistry.route_task() with routing.yml config.
Runs offline (no Ollama/ultrathink required).
"""
import os
import sys
import pytest
import yaml
from pathlib import Path

# Ensure repo root is on PYTHONPATH
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

ROUTING_YML = REPO_ROOT / "config" / "routing.yml"


@pytest.fixture(scope="module")
def routing_config():
    """Load routing.yml once per test module."""
    with open(ROUTING_YML) as f:
        return yaml.safe_load(f)


def test_routing_yml_exists():
    """routing.yml must exist and be non-empty."""
    assert ROUTING_YML.exists(), f"Missing: {ROUTING_YML}"
    assert ROUTING_YML.stat().st_size > 0


def test_routing_yml_has_routes_key(routing_config):
    """Top-level key must be 'routes'."""
    assert "routes" in routing_config


def test_required_routes_present(routing_config):
    """Core task types must all be defined."""
    required = ["default", "coding", "strategy", "research",
                "deep_reasoning", "code_analysis"]
    routes = routing_config["routes"]
    for route in required:
        assert route in routes, f"Missing route: {route}"


def test_ultrathink_routes_have_endpoint(routing_config):
    """deep_reasoning and code_analysis must reference ORAMA_ENDPOINT."""
    routes = routing_config["routes"]
    for route_name in ("deep_reasoning", "code_analysis"):
        route = routes[route_name]
        assert "endpoint" in route, f"{route_name} missing endpoint"
        assert "ORAMA_ENDPOINT" in route["endpoint"]


def test_ultrathink_routes_have_fallback(routing_config):
    """Ultrathink routes must define a fallback model."""
    routes = routing_config["routes"]
    for route_name in ("deep_reasoning", "code_analysis"):
        route = routes[route_name]
        assert "fallback" in route, f"{route_name} missing fallback"


def test_all_routes_have_roles(routing_config):
    """Every route must define a non-empty roles list."""
    routes = routing_config["routes"]
    for name, route in routes.items():
        assert "roles" in route, f"Route '{name}' missing roles"
        assert len(route["roles"]) > 0, f"Route '{name}' has empty roles"


def test_autoresearch_routes_present(routing_config):
    """autoresearch routes must be defined for GPU runner tasks."""
    routes = routing_config["routes"]
    for route in ("autoresearch", "autoresearch-coder", "ml-experiment"):
        assert route in routes, f"Missing autoresearch route: {route}"


def test_autoresearch_coder_affinity(routing_config):
    """autoresearch-coder must target win-rtx3080 (specific device, not normalized)."""
    route = routing_config["routes"]["autoresearch-coder"]
    assert route.get("affinity") == "win-rtx3080"


def test_ultrathink_comments_describe_current_task_type_contract():
    """Routing comments should describe current PT behavior, not stale request fields."""
    content = ROUTING_YML.read_text()
    assert "Called when reasoning_depth=ultra or privacy_critical=True." not in content
    assert "PT selects task_type=deep_reasoning or task_type=code_analysis" in content
    assert "`reasoning_depth` belongs to the optional HTTP backup path" in content
    assert "`privacy_critical` is not a live PT request field" in content
