from datetime import datetime, timezone
from perpetua.discovery.backend import Backend, BackendKind, BackendHealth


def test_backend_holds_identity_and_health():
    b = Backend(
        name="lmstudio-win",
        base_url="http://192.168.254.103:1234/v1",
        kind=BackendKind.LMSTUDIO,
        models=("qwen3-coder-30b",),
        health=BackendHealth.UNKNOWN,
        last_seen=None,
    )
    assert b.is_targetable_by_ip("192.168.254.103")
    assert not b.is_targetable_by_ip("10.0.0.5")
    assert b.with_health(BackendHealth.ONLINE, now=datetime.now(timezone.utc)).health is BackendHealth.ONLINE
