# mcp-data-gr

MCP server for any Huwise/Opendatasoft data portal.

## Installation

```bash
uv sync
```

## Usage

```bash
uv run main.py
```

## Debug
```bash
npx @modelcontextprotocol/inspector uv run main.py
```

### Install with uvx
```bash
uvx --from git+https://github.com/ykipfer/mcp-data-gr mcp-data-gr
```

## Selecting a catalog

The catalog is chosen by whoever deploys the server via the `.env` file next to
`main.py`. All Huwise/Opendatasoft portals share the same API
path, so you only set the domain:

```
# .env
DATA_PORTAL_DOMAIN=data.gr.ch
```

The full API base URL is built as
`https://<domain>/api/explore/v2.1`.

The `.env` file is committed, so a fork carries its
catalog choice through `uvx` installs as well.

## Docker

Build the image:

```bash
docker build -t mcp-data-gr .
```

Then use it in any MCP client that supports stdio:

```json
{
  "mcpServers": {
    "data-gr": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "mcp-data-gr"]
    }
  }
}
```

To change the data portal domain, edit `.env` and rebuild the image.

## Configuration

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "data-gr": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "mcp-data-gr"]
    }
  }
}
```

### OpenCode

Add to your OpenCode config:

```json
{
  "mcpServers": {
    "data-gr": {
      "command": "uv",
      "args": [
        "--directory",
        "/ABSOLUTE/PATH/TO/mcp-data-gr",
        "run",
        "main.py"
      ]
    }
  }
}
```

### Cursor

Add to your Cursor config (`~/.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "data-gr": {
      "command": "uv",
      "args": [
        "--directory",
        "/ABSOLUTE/PATH/TO/mcp-data-gr",
        "run",
        "main.py"
      ]
    }
  }
}
```

## Tools

### `get_datasets`
Search and list available datasets.

Two search modes:
- `semantic` (default): ranks the catalog by meaning using the `vector_similarity` explore endpoint from Huwise. Best for natural-language / conceptual queries. Matches synonyms and other languages.
- `lexical`: classic full-text match on the exact terms.

```
# semantic (default) — natural language, ranked by relevance
get_datasets(search="air quality measurements")

# lexical — exact full-text match
get_datasets(search="luft", search_mode="lexical")

# combine with facet filters
get_datasets(search="bevölkerung", refine="publisher:Statistisches Amt")
```

### `get_dataset`
Get detailed metadata for a specific dataset.

```
get_dataset(dataset_id="100113")
```

### `get_records`
Query records from a dataset with ODSQL filtering. Without `group_by` the API caps
results at 100 rows; use `get_export` for more.

```
get_records(dataset_id="100113", where="pm25 > 10", limit=100, order_by="time DESC")
```

### `get_dataset_facets`
List the facet values of a dataset's fields (dimension members).

```
get_dataset_facets(dataset_id="100113", facet="gemeinde")
```

### `get_facets`
Get available catalog-level facet values for filtering.

```
get_facets(facet="publisher")  # Options: publisher, keyword, theme, features, modified, language
```

### `get_export`
Fetch filtered/aggregated records server-side, inline, no 100-row cap (defaults to a
capped maximum when `limit` is omitted).

```
get_export(dataset_id="100113", group_by="gemeinde", select="gemeinde, sum(`anzahl`) as total")
```

### `export_dataset_url`
Get download URL for dataset export.

```
export_dataset_url(dataset_id="100113", format="csv", where="sensornr=240")
```

Formats: `csv`, `json`, `geojson`, `xlsx`, `shp`, `parquet`
