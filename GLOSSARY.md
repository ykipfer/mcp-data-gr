# mcp-data-gr

An MCP server that lets AI assistants search and query the open data of a Huwise/Opendatasoft data portal, configured for the canton of Graubünden (data.gr.ch).

## Language

### Portal and access

**Data portal**:
The Huwise/Opendatasoft site whose catalog this server exposes, identified by its domain (e.g. data.gr.ch).
_Avoid_: Catalog (when meaning the site), API, backend

**Portal API key**:
A Huwise/Opendatasoft credential belonging to one person, which the server presents to the Data portal on that person's behalf.
_Avoid_: API key (unqualified), token, server key

**Public dataset**:
A dataset on the Data portal that anyone can see without a Portal API key.
_Avoid_: Open dataset (when meaning visibility rather than licence), domain dataset

**Restricted dataset**:
A dataset on the Data portal that only accounts granted access can see; it is not open data, even when listed next to Public datasets.
_Avoid_: Private dataset, non-public dataset

**Local instance**:
A server process that one person's own MCP client spawns on their machine and talks to over stdio; nobody else can reach it.
_Avoid_: Local deployment, self-hosted instance
