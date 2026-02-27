import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("data-bs.ch")

BASE_URL = "https://data.bs.ch/api/explore/v2.1"


async def fetch(endpoint: str, params: dict[str, str | int] | None = None) -> dict:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        response = await client.get(endpoint, params=params)
        response.raise_for_status()
        return response.json()


@mcp.tool(
    title="Search Datasets",
    description="Search and list available open datasets from data.bs.ch (Basel-Stadt open data portal). Use this to discover datasets by keyword, publisher, or theme.",
)
async def get_datasets(
    limit: int = 10,
    offset: int = 0,
    search: str | None = None,
    refine: str | None = None,
) -> dict:
    """
    List available datasets from data.bs.ch with optional filtering.

    Args:
        limit: Maximum number of datasets to return (default: 10, max: 100)
        offset: Number of datasets to skip for pagination (default: 0)
        search: Search string to filter datasets by title/description
        refine: ODSQL refine filter (e.g., "publisher:Statistisches Amt")

    Returns:
        Dictionary with total_count and results array containing dataset metadata
    """
    params: dict[str, str | int] = {"limit": min(limit, 100), "offset": offset}
    if search:
        params["search"] = search
    if refine:
        params["refine"] = refine
    return await fetch("/catalog/datasets", params)


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
        Dataset metadata including fields, metas, features, and record count
    """
    return await fetch(f"/catalog/datasets/{dataset_id}")


@mcp.tool(
    title="Query Dataset Records",
    description="Query and filter records from a dataset using ODSQL syntax. Use this to retrieve actual data from a dataset with optional WHERE clauses, ordering, and pagination.",
)
async def get_records(
    dataset_id: str,
    where: str | None = None,
    limit: int = 10,
    offset: int = 0,
    order_by: str | None = None,
) -> dict:
    """
    Query records from a dataset with ODSQL filtering.

    Args:
        dataset_id: The dataset identifier (e.g., "100113")
        where: ODSQL WHERE clause (e.g., "pm25 > 10", "time >= '2020-01-01'")
        limit: Maximum number of records to return (default: 10, max: 100)
        offset: Number of records to skip for pagination (default: 0)
        order_by: Field to order results by (e.g., "time DESC", "pm25 ASC")

    Returns:
        Dictionary with total_count and results array containing record data
    """
    params: dict[str, str | int] = {"limit": min(limit, 100), "offset": offset}
    if where:
        params["where"] = where
    if order_by:
        params["order_by"] = order_by
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
