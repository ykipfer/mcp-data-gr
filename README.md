# mcp-data-gr

MCP server for a Huwise/Opendatasoft data portal, configured for data.gr.ch
(canton of Graubünden). Works against any Huwise/Opendatasoft portal via the
`.env` domain setting.

## Installation

```bash
uv sync
```

## Usage

```bash
uv run main.py
```

By default this starts a **stdio** MCP server (the MCP client spawns the
process and talks over stdin/stdout). To run it as a **Streamable HTTP**
server listening on `0.0.0.0:8000` (MCP endpoint `http://localhost:8000/mcp`)
set the `MCP_TRANSPORT` environment variable:

```bash
MCP_TRANSPORT=streamable-http uv run main.py
```

See [Configuration](#configuration) for the variable reference and client
setup for both transports.

## Debug

Start the server in HTTP mode, then point the MCP Inspector at the running
endpoint (choose the *Streamable HTTP* transport and enter
`http://localhost:8000/mcp`):

```bash
MCP_TRANSPORT=streamable-http uv run main.py   # in one terminal
npx @modelcontextprotocol/inspector            # in another, then connect to the URL
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

Run it, publishing the HTTP port:

```bash
docker run --rm -p 8000:8000 mcp-data-gr
```

The server is then reachable at `http://localhost:8000/mcp`. Point your MCP
client at that URL (see [Configuration](#configuration)). The image sets
`MCP_TRANSPORT=streamable-http`; override with `-e MCP_TRANSPORT=stdio` if
needed.

To change the data portal domain, edit `.env` and rebuild the image.

## Configuration

### Environment variables

- `MCP_TRANSPORT` — MCP transport to use: `stdio` or `streamable-http`.
  Default: `stdio` (used when the variable is missing or empty; any other
  value fails at startup). Set it in the process environment (systemd
  `Environment=`, `docker -e`, or the client config's `env` block) — entries
  in the `.env` file have no effect for this variable.

**stdio vs. streamable-http:** with `stdio` the MCP client starts the server
itself as a subprocess and talks over stdin/stdout — nothing listens on a
port. With `streamable-http` the server runs standalone on `0.0.0.0:8000` and
clients connect to the URL `http://localhost:8000/mcp`.

### Client setup

For the default stdio transport, let the client spawn the server:

```json
{
  "mcpServers": {
    "data-gr": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/mcp-data-gr", "main.py"]
    }
  }
}
```

For Streamable HTTP, start the server first (`MCP_TRANSPORT=streamable-http
uv run main.py` or via Docker), then point clients that support HTTP MCP
servers directly (e.g. Cursor `~/.cursor/mcp.json`, VS Code) at the URL:

```json
{
  "mcpServers": {
    "data-gr": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

For clients that only support stdio but need to reach a server running
elsewhere (e.g. the ngrok setup below), bridge to the URL with
[`mcp-remote`](https://github.com/geelen/mcp-remote):

```json
{
  "mcpServers": {
    "data-gr": {
      "command": "npx",
      "args": ["mcp-remote", "http://localhost:8000/mcp"]
    }
  }
}
```

### Production (Raspberry Pi + ngrok)

The server is intended to run as a background service on a host (e.g. a
Raspberry Pi) and be exposed with ngrok, which tunnels the local port 8000.
The service unit must set the transport, e.g. in systemd:
`Environment=MCP_TRANSPORT=streamable-http` — otherwise the server starts in
stdio mode and nothing listens on port 8000.

```bash
ngrok http 8000
```

Clients then use the public ngrok URL, e.g. `https://<your-subdomain>.ngrok.app/mcp`.
The server binds `0.0.0.0` and ships without authentication, so restrict access
at the ngrok layer (for example ngrok's basic-auth or a traffic policy).

## Tools

### `get_datasets`
Search and list available datasets. Each result includes `records_count` plus
the metadata-screening fields `license_url`, `update_frequency`,
`metadata_languages` and `description_length` (length of the full plain-text
description), so questions like "which datasets have incomplete metadata?" can
be answered without fetching each dataset individually.

Two search modes:
- `semantic` (default): filters and ranks the catalog by meaning using
  `vector_similarity_threshold`, which applies an automatic relevance cut-off
  and orders by relevance in one step (ODS rejects a separate
  `vector_similarity` order_by as "multiple score functions"). Best for
  natural-language / conceptual queries; matches synonyms and other languages.
  `total_count` is the number of relevant matches.
- `lexical`: classic full-text match on the exact terms.

```
# semantic (default): natural language, relevance-filtered and ranked
get_datasets(search="air quality measurements")

# lexical: exact full-text match
get_datasets(search="luft", search_mode="lexical")

# combine with facet filters
get_datasets(search="bevölkerung", refine="publisher:Amt für Wirtschaft und Tourismus")
```

### `get_dataset`
Get detailed metadata for a specific dataset (fields, types, `odsql_name`,
`records_count`). data.gr.ch dataset IDs are strings like `dvs_awt_soci_20250507`.

```
get_dataset(dataset_id="dvs_awt_soci_20250507")
```

### `get_records`
Query records from a dataset with ODSQL filtering. Without `group_by` the API caps
results at 100 rows; use `get_export` for more.

```
get_records(dataset_id="dvs_awt_soci_20250507", where="anzahl_personen > 1000", limit=100, refine="jahr:2024")
```

### `get_dataset_metadata`
Get the complete raw `metas` of a dataset: all templates (`default`, `dcat`,
`dcat_ap_ch`, `custom`) with every language variant (`*_de/_it/_en`) and the
untruncated description. Meant for metadata quality work (auditing
completeness — contact email, license, frequency, temporal/spatial coverage —
or loading context for metadata editing, e.g. with the Metadata-Wizard app);
use `get_dataset` for the compact summary.

```
get_dataset_metadata(dataset_id="dvs_awt_soci_20250507")
```

### `get_record`
Fetch a single record by its `_id` (as returned by `get_records`).

```
get_record(dataset_id="dvs_awt_soci_20250507", record_id="<_id from get_records>")
```

### `get_dataset_attachments`
List a dataset's attached files (methodology PDFs, code lists).

```
get_dataset_attachments(dataset_id="dvs_awt_soci_20250507")
```

### `get_dataset_facets`
List the facet values of a dataset's fields (dimension members). Optionally restrict
the counted records with `where` / `refine` / `exclude`.

```
get_dataset_facets(dataset_id="dvs_awt_soci_20250507", facet="kanton_region_gemeinde", refine="jahr:2024")
```

### `get_facets`
Get available catalog-level facet values for filtering.

```
get_facets(facet="publisher")  # Options: publisher, keyword, theme, features, modified, language
```

### `get_export`
Fetch filtered/aggregated records server-side, inline, beyond the 100-row `get_records`
cap. When `limit` is omitted it defaults to at most 20000 rows and sets `truncated: true`
in the response if there were more; narrow with `where`/`group_by` or pass a higher `limit`.

```
get_export(dataset_id="dvs_awt_soci_20250507", group_by="kanton_region_gemeinde", select="kanton_region_gemeinde, sum(anzahl_personen) as total")
```

### `list_export_formats`
List the export formats a specific dataset actually supports.

```
list_export_formats(dataset_id="dvs_awt_soci_20250507")
```

### `export_dataset_url`
Get download URL for dataset export. Optional `use_labels`, `epsg` (e.g. `2056` for
Swiss LV95, for geo datasets) and `compressed`.

```
export_dataset_url(dataset_id="dvs_awt_soci_20250507", format="csv", where="jahr=2024")
```

Formats: `csv`, `json`, `geojson`, `xlsx`, `shp`, `parquet`

### `export_catalog_url`
Get download URL for the whole dataset catalog (inventory) as `csv`, `json` or `xlsx`.

```
export_catalog_url(format="xlsx", where="publisher='Amt für Wirtschaft und Tourismus'")
```

## Agent skill

The repo bundles a Claude skill at `skills/ogd-graubuenden.skill` (a zip
containing `SKILL.md`). It guides an agent through the intended workflow against
these tools: searching the catalog, inspecting the field schema before building
ODSQL, verifying facet values, the 100-row / `get_export` threshold, backtick
escaping, and known data pitfalls (multi-dimensional total rows, geo BFS number
joins). Install it in a client that supports skills to have the agent use this
server correctly; it is written for the `MCP-DATA-GR` connector name.
