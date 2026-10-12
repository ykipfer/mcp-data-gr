import logging

import httpx
import pytest
import respx

KEY = "s3cr3t-portal-key"
BODY = {"error": "API key is not valid", "message": "LEAKY-BODY-TEXT"}


def _route(module, status=401):
    return respx.get(f"{module.BASE_URL}/catalog/datasets").mock(
        return_value=httpx.Response(status, json=BODY)
    )


@respx.mock
async def test_401_with_key_says_invalid_or_expired(load_main, caplog):
    module = load_main(KEY)
    _route(module)
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(RuntimeError) as exc:
            await module.fetch("/catalog/datasets")
    assert str(exc.value) == "Portal API key ungültig oder abgelaufen"
    assert "LEAKY-BODY-TEXT" not in caplog.text
    assert KEY not in caplog.text


@respx.mock
async def test_401_without_key_says_login_required(load_main):
    module = load_main(None)
    _route(module)
    with pytest.raises(RuntimeError) as exc:
        await module.fetch("/catalog/datasets")
    assert str(exc.value) == "Portal erfordert Anmeldung: Portal API key setzen"


@respx.mock
async def test_404_keeps_generic_handling(load_main):
    module = load_main(KEY)
    respx.get(f"{module.BASE_URL}/catalog/datasets").mock(
        return_value=httpx.Response(404, json={"error_code": "NotFoundResource", "message": "nope"})
    )
    with pytest.raises(RuntimeError) as exc:
        await module.fetch("/catalog/datasets")
    assert str(exc.value) == "ODS 404 NotFoundResource: nope"
