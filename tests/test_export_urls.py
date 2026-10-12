import httpx
import pytest
import respx

KEY = "s3cr3t-portal-key"


def _detail(module, dataset_id="ds1"):
    return respx.get(f"{module.BASE_URL}/catalog/datasets/{dataset_id}")


@respx.mock
async def test_restricted_dataset_with_key_errors_pointing_to_get_export(load_main):
    module = load_main(KEY)
    _detail(module).mock(return_value=httpx.Response(200, json={"visibility": "restricted"}))
    with pytest.raises(RuntimeError) as exc:
        await module.export_dataset_url("ds1")
    assert "get_export" in str(exc.value)
    assert KEY not in str(exc.value)


@respx.mock
async def test_domain_dataset_with_key_returns_plain_url(load_main):
    module = load_main(KEY)
    _detail(module).mock(return_value=httpx.Response(200, json={"visibility": "domain"}))
    url = await module.export_dataset_url("ds1", format="csv")
    assert url == f"{module.BASE_URL}/catalog/datasets/ds1/exports/csv?lang=de"


@respx.mock
@pytest.mark.parametrize("body", [{}, {"visibility": None}])
async def test_unknown_visibility_with_key_returns_url_and_auth_note(load_main, body):
    module = load_main(KEY)
    _detail(module).mock(return_value=httpx.Response(200, json=body))
    out = await module.export_dataset_url("ds1", format="csv")
    assert f"{module.BASE_URL}/catalog/datasets/ds1/exports/csv" in out
    assert "get_export" in out
    assert "Authentifizierung" in out


@respx.mock
async def test_no_key_does_no_lookup_and_returns_bare_url(load_main):
    module = load_main(None)
    route = _detail(module).mock(return_value=httpx.Response(200, json={"visibility": "restricted"}))
    url = await module.export_dataset_url("ds1", format="csv")
    assert url == f"{module.BASE_URL}/catalog/datasets/ds1/exports/csv?lang=de"
    assert not route.called


async def test_catalog_url_notes_public_only_when_key_set(load_main):
    module = load_main(KEY)
    out = await module.export_catalog_url(format="csv")
    assert out.startswith(f"{module.BASE_URL}/catalog/exports/csv")
    assert "Public datasets" in out


async def test_catalog_url_unchanged_without_key(load_main):
    module = load_main(None)
    out = await module.export_catalog_url(format="csv")
    assert out == f"{module.BASE_URL}/catalog/exports/csv"
