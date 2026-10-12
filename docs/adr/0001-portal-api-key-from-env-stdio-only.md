---
status: accepted
---

# Portal API key comes from the process environment and is accepted only on a Local instance

A person running a Local instance can supply their own Portal API key so the server sees their Restricted datasets and gets their extended quota. The key is read from the `DATA_PORTAL_API_KEY` process environment variable (normally the `env` block of the MCP client config), unlike the Data portal domain, which is read only from the committed `.env` precisely so a client cannot change it. The two rules are not in conflict: the domain is the deployer's choice and must not be overridable, while the key is the client owner's credential and must never be committed. The server refuses to start when a key is set and the transport is anything other than stdio, because Huwise keys carry their owner's full rights ("they grant the same rights (yours) to any person using them"), and on the streamable-http transport (Docker, the Pi + ngrok deployment) everyone who can reach the URL would act as the key owner.

The key is sent only as `Authorization: Apikey <key>` on the shared upstream client, never as the `apikey` query parameter, so request logging and the export URLs handed to clients cannot leak it. Consequently, export URLs for Restricted datasets do not work for the client; `export_dataset_url` refuses them and points to `get_export`, which fetches through the authenticated client.

## Considered Options

- **Key in `.env`**: rejected; `.env` is committed and shipped with `uvx` installs.
- **Key as a CLI argument**: rejected; visible in process listings.
- **Allow the key on streamable-http, or ignore it with a warning**: rejected; the first shares one person's portal access with every caller, the second lets users believe the key is in effect when it is not.
- **`apikey` query parameter**: rejected; the spec itself recommends the header because query strings end up in logs and history, and it would put the key into URLs returned to the AI client.
- **OAuth2** (supported by Huwise): rejected; it needs an application registered per Data portal, a browser redirect and token refresh, which is disproportionate for a process the user's own MCP client spawns.
