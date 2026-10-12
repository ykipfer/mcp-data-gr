import httpx
import pytest
import respx

QUOTA = {
    "errorcode": 10002,
    "reset_time": "2021-01-26T00:00:00Z",
    "limit_time_unit": "day",
    "call_limit": 10000,
    "error": "Too many requests on the domain. Please contact the domain administrator.",
}


@respx.mock
async def test_429_reports_reset_time_and_limit(load_main):
    module = load_main(None)
    respx.get(f"{module.BASE_URL}/catalog/datasets").mock(return_value=httpx.Response(429, json=QUOTA))
    with pytest.raises(RuntimeError) as exc:
        await module.fetch("/catalog/datasets")
    assert "2021-01-26T00:00:00Z" in str(exc.value)
    assert "10000/day" in str(exc.value)


@respx.mock
async def test_429_non_json_body_falls_back_to_unbekannt(load_main):
    module = load_main(None)
    respx.get(f"{module.BASE_URL}/catalog/datasets").mock(return_value=httpx.Response(429, text="slow down"))
    with pytest.raises(RuntimeError) as exc:
        await module.fetch("/catalog/datasets")
    assert str(exc.value).count("unbekannt") == 2


@respx.mock
async def test_429_uses_retry_after_as_fallback(load_main):
    module = load_main(None)
    respx.get(f"{module.BASE_URL}/catalog/datasets").mock(
        return_value=httpx.Response(429, text="x", headers={"Retry-After": "120"})
    )
    with pytest.raises(RuntimeError) as exc:
        await module.fetch("/catalog/datasets")
    assert "120" in str(exc.value)
