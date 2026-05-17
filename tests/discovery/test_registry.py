import pytest, respx, httpx
from perpetua.discovery.backend import BackendKind, BackendHealth
from perpetua.discovery.registry import BackendRegistry
from perpetua.discovery.errors import BackendOfflineError


@pytest.mark.asyncio
@respx.mock
async def test_autodetect_keeps_only_responsive_seeds():
    respx.get("http://localhost:11434/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "qwen3.5:9b-nvfp4"}]}))
    respx.get("http://localhost:1234/v1/models").mock(return_value=httpx.Response(404))
    respx.get("http://192.168.254.103:1234/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "qwen3-coder-30b"}]}))

    reg = BackendRegistry()
    await reg.autodetect()
    online = [b.name for b in reg.online()]
    assert "ollama-local" in online
    assert "lmstudio-win" in online
    assert "lmstudio-mac" not in online


@pytest.mark.asyncio
@respx.mock
async def test_register_by_ip_admits_only_when_probe_succeeds():
    respx.get("http://192.168.254.103:1234/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "qwen3-coder-30b"}]}))
    reg = BackendRegistry()
    b = await reg.register_by_ip("192.168.254.103", 1234, BackendKind.LMSTUDIO, name="win-rig")
    assert b.health is BackendHealth.ONLINE
    assert reg.find("win-rig") is b


@pytest.mark.asyncio
@respx.mock
async def test_register_by_ip_raises_when_offline():
    respx.get("http://10.0.0.99:1234/v1/models").mock(side_effect=httpx.ConnectError("nope"))
    reg = BackendRegistry()
    with pytest.raises(BackendOfflineError):
        await reg.register_by_ip("10.0.0.99", 1234, BackendKind.LMSTUDIO)
