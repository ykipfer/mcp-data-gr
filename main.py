from difflib import SequenceMatcher

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("data-bs.ch")

BASE_URL = "https://data.bs.ch/api/explore/v2.1"


async def fetch(endpoint: str, params: dict[str, str | int] | None = None) -> dict:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        response = await client.get(endpoint, params=params)
        response.raise_for_status()
        return response.json()


def _to_str(value) -> str:
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    return str(value) if value else ""


def _simplify_dataset(data: dict) -> dict:
    metas = data.get("metas", {})
    default = metas.get("default", {})
    explore = metas.get("explore", {})
    return {
        "dataset_id": data.get("dataset_id"),
        "title": _to_str(default.get("title")),
        "description": _to_str(default.get("description")),
        "theme": _to_str(default.get("theme")),
        "keyword": default.get("keyword", []) or [],
        "publisher": _to_str(default.get("publisher")),
        "modified": default.get("modified"),
        "language": default.get("language", []) or [],
        "records_count": explore.get("records_count"),
    }


def _tokenize(text: str) -> list[str]:
    return [
        t
        for t in text.lower().replace(".", " ").replace("-", " ").split()
        if len(t) > 1
    ]


def _match_score(text: str, query: str) -> float:
    if not text or not query:
        return 0.0
    text_lower = text.lower()
    query_lower = query.lower()
    if query_lower in text_lower:
        return 1.0
    text_tokens = _tokenize(text)
    query_tokens = _tokenize(query)
    if not query_tokens:
        return 0.0
    score = 0.0
    for qt in query_tokens:
        best = 0.0
        for tt in text_tokens:
            if qt == tt:
                best = 1.0
            elif len(qt) >= 3 and (qt in tt or tt in qt):
                best = max(best, 0.8)
            elif len(qt) >= 3 and len(tt) >= 3:
                ratio = SequenceMatcher(None, qt, tt).ratio()
                if ratio > 0.7:
                    best = max(best, ratio * 0.6)
        score += best
    return score / len(query_tokens)


def _score_dataset(dataset: dict, query: str) -> float:
    metas = dataset.get("metas", {})
    default = metas.get("default", {})
    score = 0.0
    title = _to_str(default.get("title"))
    description = _to_str(default.get("description"))
    theme = _to_str(default.get("theme"))
    keywords = default.get("keyword", []) or []
    publisher = _to_str(default.get("publisher"))
    score += _match_score(title, query) * 3.0
    score += _match_score(description, query) * 1.0
    score += _match_score(theme, query) * 2.0
    score += _match_score(publisher, query) * 1.5
    for kw in keywords:
        score += _match_score(str(kw), query) * 2.0
    return score


@mcp.tool(
    title="Search Datasets",
    description="Search and list available open datasets from data.bs.ch (Basel-Stadt open data portal). Use this to discover datasets by keyword, publisher, or theme.",
)
async def get_datasets(
    limit: int = 10,
    offset: int = 0,
    search: str | None = None,
    refine: str | None = None,
    exclude: str | None = None,
    order_by: str | None = None,
    timezone: str | None = None,
    include_app_metas: bool = False,
) -> dict:
    """
    List available datasets from data.bs.ch with optional filtering.

    Args:
        limit: Number of items to return (default: 10, max: 100)
        offset: Index of first item to return (default: 0)
        search: Fuzzy search string to filter datasets (searches title, description, theme, keywords, publisher)
        refine: Facet filter to limit results (e.g., "publisher:Statistisches Amt")
        exclude: Facet filter to exclude values (e.g., "modified:2019/12")
        order_by: Field to sort results (e.g., "modified desc", "title asc")
        timezone: Timezone for datetime fields (e.g., "Europe/Zurich")
        include_app_metas: Include application metadata in response

    Returns:
        Dictionary with total_count and results array containing dataset metadata
    """
    params: dict[str, str | int] = {"limit": 100, "offset": 0}
    if refine:
        params["refine"] = refine
    if exclude:
        params["exclude"] = exclude
    if timezone:
        params["timezone"] = timezone
    if include_app_metas:
        params["include_app_metas"] = "true"
    all_results = []
    page_offset = 0
    while True:
        params["offset"] = page_offset
        params["limit"] = 100
        data = await fetch("/catalog/datasets", params)
        results = data.get("results", [])
        all_results.extend(results)
        if len(results) < 100:
            break
        page_offset += 100
    results = all_results
    if search:
        scored = [(ds, _score_dataset(ds, search)) for ds in results]
        scored = [(ds, s) for ds, s in scored if s > 0.3]
        scored.sort(key=lambda x: x[1], reverse=True)
        results = [ds for ds, _ in scored]
    if order_by:
        reverse = False
        field = order_by
        if order_by.endswith(" desc"):
            field = order_by[:-5].strip()
            reverse = True
        elif order_by.endswith(" asc"):
            field = order_by[:-4].strip()
            reverse = False
        results.sort(
            key=lambda ds: _simplify_dataset(ds).get(field, "") or "",
            reverse=reverse,
        )
    total = len(results)
    paginated = results[offset : offset + limit]
    return {
        "total_count": total,
        "results": [_simplify_dataset(d) for d in paginated],
    }


@mcp.tool(
    title="Get Dataset Metadata",
    description="Get detailed metadata for a specific dataset including field definitions, schema, publisher info, and record count. Use this to understand a dataset's structure before querying records.",
)
async def get_dataset(dataset_id: str) -> dict:
    """
    Get detailed metadata for a specific dataset.

    Args:
        dataset_id: The dataset identifier (e.g., "100113")

    Returns:
        Dataset metadata including title, description, theme, keywords, etc.
    """
    data = await fetch(f"/catalog/datasets/{dataset_id}")
    metas = data.get("metas", {})
    return {
        "dataset_id": data.get("dataset_id"),
        "title": metas.get("default", {}).get("title"),
        "description": metas.get("default", {}).get("description"),
        "theme": metas.get("default", {}).get("theme"),
        "keyword": metas.get("default", {}).get("keyword", []),
        "publisher": metas.get("default", {}).get("publisher"),
        "modified": metas.get("default", {}).get("modified"),
        "language": metas.get("default", {}).get("language", []),
        "records_count": data.get("metas", {}).get("explore", {}).get("records_count"),
        "fields": [
            {"name": f.get("name"), "type": f.get("type")}
            for f in data.get("fields", [])
        ],
    }


@mcp.tool(
    title="Query Dataset Records",
    description="Query and filter records from a dataset using ODSQL syntax. Use this to retrieve actual data from a dataset with optional WHERE clauses, ordering, and pagination.",
)
async def get_records(
    dataset_id: str,
    select: str | None = None,
    where: str | None = None,
    group_by: str | None = None,
    order_by: str | None = None,
    limit: int = 10,
    offset: int = 0,
    refine: str | None = None,
    exclude: str | None = None,
    lang: str | None = None,
    timezone: str | None = None,
    include_links: bool = False,
) -> dict:
    """
    Query records from a dataset with ODSQL filtering.

    Args:
        dataset_id: The dataset identifier (e.g., "100113")
        select: Select expression to add/remove/change fields (e.g., "size", "size * 2 as bigger_size", "*")
        where: ODSQL WHERE clause (e.g., "pm25 > 10", "time >= '2020-01-01'")
        group_by: Grouping expression for aggregations (e.g., "city_field as city")
        order_by: Field to order results by (e.g., "time DESC", "pm25 ASC")
        limit: Number of items to return (default: 10, max: 100, or 20000 with group_by)
        offset: Index of first item to return (default: 0)
        refine: Facet filter to limit results (e.g., "city:Paris")
        exclude: Facet filter to exclude values (e.g., "modified:2019/12")
        lang: Language for formatting (e.g., "en", "de", "fr")
        timezone: Timezone for datetime fields (e.g., "Europe/Zurich")
        include_links: Include HATEOAS links in response

    Returns:
        Dictionary with total_count and results array containing record data
    """
    params: dict[str, str | int] = {"limit": min(limit, 20000), "offset": offset}
    if select:
        params["select"] = select
    if where:
        params["where"] = where
    if group_by:
        params["group_by"] = group_by
    if order_by:
        params["order_by"] = order_by
    if refine:
        params["refine"] = refine
    if exclude:
        params["exclude"] = exclude
    if lang:
        params["lang"] = lang
    if timezone:
        params["timezone"] = timezone
    if include_links:
        params["include_links"] = "true"
    return await fetch(f"/catalog/datasets/{dataset_id}/records", params)


@mcp.tool(
    title="Get Facet Values",
    description="Get available filter values for categorizing datasets. Useful for discovering publishers, keywords, themes, or other facets to refine dataset searches.",
)
async def get_facets(facet: str | None = None) -> dict:
    """
    Get available facet values for filtering datasets.

    Args:
        facet: Specific facet to retrieve: "publisher", "keyword", "theme", "features", "modified", "language"
               If None, returns all facets

    Returns:
        Dictionary with facet name and array of values with counts
    """
    params: dict[str, str | int] = {}
    if facet:
        params["facet"] = facet
    data = await fetch("/catalog/facets", params)
    if facet and "facets" in data:
        for f in data["facets"]:
            if f["name"] == facet:
                return {"facet": facet, "values": f.get("facets", [])}
    return data


@mcp.tool(
    title="Get Export URL",
    description="Generate a download URL for exporting a dataset in various formats (CSV, JSON, GeoJSON, XLSX, Shapefile, Parquet, etc.). Use this when you need to download or share dataset exports.",
)
async def export_dataset_url(
    dataset_id: str,
    format: str = "json",
    where: str | None = None,
) -> str:
    """
    Get the export URL for downloading a dataset in various formats.

    Args:
        dataset_id: The dataset identifier (e.g., "100113")
        format: Export format: csv, json, geojson, xlsx, shp, parquet, gpx, kml, rdfxml, jsonld, turtle
        where: Optional ODSQL WHERE clause to filter exported records

    Returns:
        Full URL to download the exported dataset
    """
    url = f"{BASE_URL}/catalog/datasets/{dataset_id}/exports/{format}"
    if where:
        url += f"?where={where}"
    return url


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
