from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlencode

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import Field


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


# Read directly from the .env file next to this
# module. The process environment is intentionally not consulted so an MCP
# client cannot override the catalog via its config's env block.
_env_path = Path(__file__).parent / ".env"
if not _env_path.is_file():
    raise RuntimeError(f"Missing .env file at {_env_path}")

_config = _read_env_file(_env_path)
DOMAIN = _config.get("DATA_PORTAL_DOMAIN", "").strip()

if not DOMAIN:
    raise RuntimeError(f"DATA_PORTAL_DOMAIN is not set in {_env_path}")

DOMAIN = DOMAIN.removeprefix("https://").removeprefix("http://").strip("/")
BASE_URL = f"https://{DOMAIN}/api/explore/v2.1"

mcp = FastMCP(DOMAIN, host="0.0.0.0", port=8000)


async def fetch(endpoint: str, params: dict[str, str | int] | None = None) -> dict | list:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        response = await client.get(endpoint, params=params)
        if response.status_code >= 400:
            try:
                err = response.json()
            except Exception:
                err = {"message": response.text}
            raise RuntimeError(
                f"ODS {response.status_code} {err.get('error_code', 'Error')}: "
                f"{err.get('message', response.text)}"
            )
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


def _escape_odsql(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


ODS_RESERVED = {
    "year", "month", "day", "hour", "minute", "second", "count", "sum",
    "avg", "min", "max", "range", "top", "distinct", "group", "select",
    "where", "not", "and", "or", "as", "by", "asc", "desc", "null",
    "true", "false", "like", "in", "date", "datetime", "from", "limit", "offset",
}


def _odsql_safe(name: str) -> str:
    if name and (name[0].isdigit() or name.lower() in ODS_RESERVED):
        return f"`{name}`"
    return name


@mcp.tool(
    title="Search Datasets",
    description=(
        f"Search and list available open datasets from {DOMAIN}. Two modes: 'semantic' "
        "(default) ranks the catalog by meaning using natural-language queries "
        "(handles synonyms and other languages); 'lexical' does a classic full-text "
        "match on the exact terms. Use semantic for conceptual discovery, lexical for "
        "precise term/name lookups."
    ),
)
async def get_datasets(
    limit: int = 10,
    offset: int = 0,
    search: str | None = None,
    search_mode: str = "semantic",
    refine: str | None = None,
    exclude: str | None = None,
    order_by: str | None = None,
    timezone: str | None = None,
    include_app_metas: bool = False,
    lang: str = "de",
) -> dict:
    """
    List available datasets from the configured catalog with optional filtering.

    Args:
        limit: Number of items to return (default: 10, max: 100)
        offset: Index of first item to return (default: 0)
        search: Search string. Interpreted according to search_mode.
        search_mode: "semantic" (default) ranks the whole catalog by meaning via
            vector_similarity (best for natural-language/conceptual queries, also
            matches synonyms and other languages); "lexical" filters by exact
            full-text match. Ignored when search is empty.
        refine: Facet filter to limit results (e.g., "publisher:Statistisches Amt")
        exclude: Facet filter to exclude values (e.g., "modified:2019/12")
        order_by: Field to sort results (e.g., "modified desc", "title asc").
            Ignored in semantic mode, where results are ordered by relevance.
        timezone: Timezone for datetime fields (e.g., "Europe/Zurich")
        include_app_metas: Include application metadata in response

    Returns:
        Dictionary with total_count and results array containing dataset metadata.
        Note: in semantic mode the catalog is ranked rather than filtered, so
        total_count reflects the whole catalog and the top results are the most
        relevant.
    """
    params: dict[str, str | int] = {"limit": min(limit, 100), "offset": offset}
    if refine:
        params["refine"] = refine
    if exclude:
        params["exclude"] = exclude
    if timezone:
        params["timezone"] = timezone
    if lang:
        params["lang"] = lang
    if include_app_metas:
        params["include_app_metas"] = "true"
    normalized_search = " ".join(search.split()) if search else ""
    if normalized_search:
        query = _escape_odsql(normalized_search)
        if search_mode == "lexical":
            params["where"] = f'search("{query}")'
            if order_by:
                params["order_by"] = order_by
        else:
            params["order_by"] = f'vector_similarity("{query}") desc'
    elif order_by:
        params["order_by"] = order_by
    data = await fetch("/catalog/datasets", params)
    return {
        "total_count": data.get("total_count"),
        "results": [_simplify_dataset(d) for d in data.get("results", [])],
    }


@mcp.tool(
    title="Get Dataset Metadata",
    description="Get detailed metadata for a specific dataset including field definitions, schema, publisher info, and record count. Use this to understand a dataset's structure before querying records.",
)
async def get_dataset(dataset_id: str, lang: str = "de") -> dict:
    """
    Get detailed metadata for a specific dataset.

    Args:
        dataset_id: The dataset identifier (e.g., "100113")
        lang: The language of the dataset metadata (default: "de")

    Returns:
        Dataset metadata including title, description, theme, keywords, etc.
    """
    data = await fetch(f"/catalog/datasets/{dataset_id}", params={"lang": lang})
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
            {
                "name": f.get("name"),
                "odsql_name": _odsql_safe(f.get("name", "")),
                "type": f.get("type"),
                "description": f.get("description"),
            }
            for f in data.get("fields", [])
        ],
    }


@mcp.tool(
    title="Query Dataset Records",
    description=(
        "Query and filter records from a dataset using ODSQL syntax. "
        "Limited to 100 rows without group_by (use get_export for larger result sets). "
        "ODSQL tips: use backtick-quoted field names for fields starting with a digit "
        "or matching reserved words (e.g. `25_29_jahre`, `year`). "
        "Date literals use date'YYYY-MM-DD' (not quoted strings). "
        "For date fields, prefer year(field)=2024 or refine:field:2024. "
        "Geo functions (within_distance, intersects, in_bbox) and text functions "
        "(search, startswith) are supported in WHERE clauses."
    ),
)
async def get_records(
    dataset_id: str,
    select: str | None = None,
    where: str | None = None,
    group_by: str | None = None,
    order_by: str | None = None,
    limit: Annotated[int, Field(ge=1, le=20000)] = 10,
    offset: Annotated[int, Field(ge=0)] = 0,
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
        select: Select expression (e.g., "sum(`25_29_jahre`)", "avg(wert) as mean")
        where: ODSQL WHERE clause (e.g., "pm25 > 10", "zeit >= date'2020-01-01'",
            "year(jahr) = 2024", "search(gemeinde, 'Brail')")
        group_by: Grouping expression for aggregations (e.g., "city_field as city")
        order_by: Sort expression. With aggregations, put the aggregate first
            (e.g., "avg(x) desc, gender" not "gender, avg(x) desc")
        limit: Number of items to return (default: 10, max: 100 without group_by,
            max: 20000 with group_by). Use get_export for larger result sets.
        offset: Index of first item to return (default: 0)
        refine: Facet filter to limit results (e.g., "city:Paris", "jahr:2024")
        exclude: Facet filter to exclude values (e.g., "modified:2019/12")
        lang: Language for formatting (e.g., "en", "de", "fr")
        timezone: Timezone for datetime fields (e.g., "Europe/Zurich")
        include_links: Include HATEOAS links in response

    Returns:
        Dictionary with total_count and results array containing record data.
        If total_count > len(results), consider using get_export instead.
    """
    max_limit = 20000 if group_by else 100
    params: dict[str, str | int] = {"limit": min(limit, max_limit), "offset": offset}
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
    description=(
        "Generate a download URL for exporting a dataset in various formats. "
        "Supports filtering, aggregation, and sorting via ODSQL — no row limit. "
        "Note: the URL is only useful if the client can fetch it directly. "
        "If network access is restricted, use get_export instead."
    ),
)
async def export_dataset_url(
    dataset_id: str,
    format: Literal["csv", "json", "geojson", "xlsx", "shp", "parquet"] = "json",
    select: str | None = None,
    where: str | None = None,
    group_by: str | None = None,
    order_by: str | None = None,
    limit: int | None = None,
    lang: str = "de",
) -> str:
    """
    Get the export URL for downloading a dataset in various formats.

    Args:
        dataset_id: The dataset identifier (e.g., "100113")
        format: Export format (csv, json, geojson, xlsx, shp, parquet)
        select: Select expression for fields/aggregations
        where: ODSQL WHERE clause to filter exported records
        group_by: Grouping expression for aggregations
        order_by: Sort expression
        limit: Max number of rows to export
        lang: Language for metadata (default: "de"). CSV exports use BOM;
            read with utf-8-sig encoding.

    Returns:
        Full URL to download the exported dataset
    """
    base = f"{BASE_URL}/catalog/datasets/{dataset_id}/exports/{format}"
    query = {k: v for k, v in {
        "select": select, "where": where, "group_by": group_by,
        "order_by": order_by, "limit": limit, "lang": lang,
    }.items() if v is not None}
    return f"{base}?{urlencode(query)}" if query else base


def main():
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
