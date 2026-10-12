import logging

import httpx
import pytest
import respx

KEY = "s3cr3t-portal-key"


def _route(module):
    return respx.get(f"{module.BASE_URL}/catalog/datasets")


@respx.mock
async def test_header_sent_when_key_set(load_main):
    module = load_main(KEY)
    route = _route(module).mock(return_value=httpx.Response(200, json={"results": []}))
    await module.fetch("/catalog/datasets")
    assert route.calls.last.request.headers["Authorization"] == f"Apikey {KEY}"
    assert "apikey" not in str(route.calls.last.request.url).lower()


@respx.mock
async def test_header_absent_when_key_unset(load_main):
    module = load_main(None)
    route = _route(module).mock(return_value=httpx.Response(200, json={}))
    await module.fetch("/catalog/datasets")
    assert "Authorization" not in route.calls.last.request.headers


@respx.mock
@pytest.mark.parametrize("value", ["", "   "])
async def test_empty_env_var_is_no_key(load_main, value):
    module = load_main(value)
    route = _route(module).mock(return_value=httpx.Response(200, json={}))
    await module.fetch("/catalog/datasets")
    assert "Authorization" not in route.calls.last.request.headers


@pytest.mark.parametrize("transport", ["streamable-http", "sse"])
def test_startup_refused_for_non_stdio_with_key(load_main, monkeypatch, transport):
    module = load_main(KEY)
    monkeypatch.setenv("MCP_TRANSPORT", transport)
    monkeypatch.setattr(module.mcp, "run", lambda **kw: pytest.fail("server started"))
    with pytest.raises(RuntimeError) as exc:
        module.main()
    assert "DATA_PORTAL_API_KEY" in str(exc.value)
    assert KEY not in str(exc.value)


@pytest.mark.parametrize("transport", [None, "", "stdio"])
def test_startup_allowed_for_stdio_with_key(load_main, monkeypatch, transport):
    module = load_main(KEY)
    if transport is None:
        monkeypatch.delenv("MCP_TRANSPORT", raising=False)
    else:
        monkeypatch.setenv("MCP_TRANSPORT", transport)
    started = []
    monkeypatch.setattr(module.mcp, "run", lambda **kw: started.append(kw))
    module.main()
    assert started == [{"transport": "stdio"}]


def test_startup_allowed_for_http_without_key(load_main, monkeypatch):
    module = load_main(None)
    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
    started = []
    monkeypatch.setattr(module.mcp, "run", lambda **kw: started.append(kw))
    module.main()
    assert started == [{"transport": "streamable-http"}]


@respx.mock
async def test_key_never_in_errors_or_logs(load_main, caplog):
    module = load_main(KEY)
    _route(module).mock(
        return_value=httpx.Response(404, json={"error_code": "NotFoundResource", "message": "nope"})
    )
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(RuntimeError) as exc:
            await module.fetch("/catalog/datasets")
    assert KEY not in str(exc.value)
    assert KEY not in caplog.text
