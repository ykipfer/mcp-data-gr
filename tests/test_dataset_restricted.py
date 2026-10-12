import httpx
import pytest
import respx


def _dataset(**extra):
    return {"dataset_id": "ds1", "metas": {"default": {"title": "T"}}, "fields": [], **extra}


@pytest.mark.parametrize(
    "visibility, expected",
    [("restricted", True), ("domain", False), (None, None)],
)
@respx.mock
async def test_restricted_mapping_in_both_tools(load_main, visibility, expected):
    module = load_main(None)
    body = _dataset(data_visible=True)
    if visibility is not None:
        body["visibility"] = visibility
    respx.get(f"{module.BASE_URL}/catalog/datasets").mock(
        return_value=httpx.Response(200, json={"total_count": 1, "results": [body]})
    )
    respx.get(f"{module.BASE_URL}/catalog/datasets/ds1").mock(
        return_value=httpx.Response(200, json=body)
    )
    listed = (await module.get_datasets())["results"][0]
    detail = await module.get_dataset("ds1")
    for out in (listed, detail):
        assert out["restricted"] is expected
        assert out["data_visible"] is True


@pytest.mark.parametrize("value", [True, False, None])
@respx.mock
async def test_data_visible_passed_through(load_main, value):
    module = load_main(None)
    body = _dataset(visibility="domain")
    if value is not None:
        body["data_visible"] = value
    respx.get(f"{module.BASE_URL}/catalog/datasets/ds1").mock(
        return_value=httpx.Response(200, json=body)
    )
    assert (await module.get_dataset("ds1"))["data_visible"] is value
