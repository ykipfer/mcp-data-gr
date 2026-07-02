# Code Review MCP-DATA-GR

Audit vom 2026-07-02, revidiert nach Nachlieferung der v2.1-Spezifikation. Geprüft: `main.py` (Stand Commit f793ca6), `pyproject.toml`, `Dockerfile`, `.env`, `README.md`, `skills/ogd-graubuenden.skill` (SKILL.md), OpenAPI-Spezifikationen der Explore API in v2.0 und v2.1 (inkl. der in v2.1 eingebetteten vollständigen ODSQL-Referenz), Live-Verhalten des produktiven Servers via MCP-Connector.

## Nicht einsehbare Artefakte (explizite Lücken)

- systemd Unit-File: nicht im Repo. Restart-Policy, Ressourcenlimits, User-Isolation nicht prüfbar.
- ngrok-Konfiguration: nicht im Repo. Ob auf ngrok-Ebene Auth (Basic Auth, OAuth, IP-Restriktion) aktiv ist, ist nicht prüfbar.
- Die ODSQL-Dokumentationsseite (help.opendatasoft.com/apis/ods-explore-v2) ist aus der Audit-Umgebung nicht abrufbar (Proxy 403). Sie ist die gerenderte Darstellung der v2.1-Spezifikation; deren `info.description` enthält die vollständige ODSQL-Referenz (Language elements, Literale, Reserved Keywords, Prädikate, Funktionen) und wurde als Grundlage verwendet. Inhaltliche Abweichungen zwischen Webseite und eingebetteter Referenz sind nicht auszuschliessen, aber unwahrscheinlich.

## Tool-Inventar

| Tool | Endpoint | Parameter (Pflicht fett) | Zweck |
|---|---|---|---|
| `get_datasets` | GET /catalog/datasets | limit=10, offset=0, search, search_mode="semantic", refine, exclude, order_by, timezone, include_app_metas=False, lang="de" | Katalogsuche (semantisch via `vector_similarity` oder lexikalisch via `search()`) |
| `get_dataset` | GET /catalog/datasets/{id} | **dataset_id**, lang="de" | Metadaten und Feldschema inkl. `odsql_name` |
| `get_records` | GET /catalog/datasets/{id}/records | **dataset_id**, select, where, group_by, order_by, limit=10 (1..20000), offset>=0, refine, exclude, lang, timezone, include_links=False | ODSQL-Abfrage, max. 100 Zeilen ohne group_by |
| `get_facets` | GET /catalog/facets | facet | Katalog-Facetten (publisher, theme, ...) |
| `get_dataset_facets` | GET /catalog/datasets/{id}/facets | **dataset_id**, facet, lang="de" | Feldwerte (Dimensionsmitglieder) eines Datensatzes |
| `export_dataset_url` | (URL-Bau auf) /catalog/datasets/{id}/exports/{format} | **dataset_id**, format="json" (csv/json/geojson/xlsx/shp/parquet), select, where, group_by, order_by, limit, lang="de" | Download-URL generieren |
| `get_export` | GET /catalog/datasets/{id}/exports/json | **dataset_id**, select, where, group_by, order_by, limit, lang="de" | Export serverseitig holen, inline zurückgeben, kein Zeilenlimit |

Positiv vorab (bestätigt): ODS-Fehlertexte werden an den Client durchgereicht (main.py:44-52), `odsql_name` im Schema ist ein guter Mechanismus, `search`-Input wird escaped (main.py:79-80), keine Secrets im Repo (`.env` enthält nur die Domain).

---

# Teil A: Priorisierte Befundliste

## A1. MCP-Endpoint ohne Authentifizierung, Bind auf 0.0.0.0

- Severity: kritisch
- Kategorie: Sicherheit
- Fundstelle: main.py:38 und main.py:431-432
- Status: bestätigt (Code); ngrok-seitige Absicherung nicht prüfbar (Konfiguration fehlt im Repo)
- Problem: `mcp = FastMCP(DOMAIN, host="0.0.0.0", port=8000)` und `mcp.run(transport="streamable-http")` starten einen HTTP-Server ohne jegliche Auth-Schicht, gebunden an alle Interfaces. Via ngrok ist der Endpoint öffentlich erreichbar; zusätzlich ist er im lokalen Netz des Pi offen.
- Auswirkung: Jeder, der die ngrok-URL kennt oder errät, kann alle Tools aufrufen. Die Daten sind zwar öffentlich, aber: (a) der Pi wird als offener Proxy auf data.gr.ch missbrauchbar, (b) das ODS-Domain-Quota (Spec: errorcode 10002, «call_limit: 10000/day») kann durch Dritte aufgebraucht werden, was den legitimen Betrieb lahmlegt, (c) `get_export` ohne Limit ist ein triviales DoS auf den Pi (siehe A2).
- Fix:
  1. Bind auf Loopback, da ngrok lokal tunnelt: `FastMCP(DOMAIN, host="127.0.0.1", port=8000)`.
  2. Auth auf ngrok-Ebene erzwingen, z.B. `ngrok http 8000 --basic-auth "mcp:<starkes-passwort>"` oder eine Traffic Policy mit Header-Prüfung; im MCP-Client den Authorization-Header konfigurieren.
  3. Alternativ oder zusätzlich im Server einen statischen Bearer-Token prüfen (Starlette-Middleware um die FastMCP-App), Token via Umgebungsvariable, nicht in `.env` im Repo.

## A2. get_export ohne Default-Limit: Speicher- und Kontext-Blowup

- Severity: kritisch
- Kategorie: Betrieb / Code
- Fundstelle: `get_export`, main.py:399-428, insb. main.py:427 `data = await fetch(...)` und main.py:41-53 (fetch lädt Response komplett via `response.json()`)
- Status: bestätigt (Code); Grössenordnung live verifiziert: `dvs_awt_soci_20250507` hat 344'085 Zeilen
- Problem: `limit` ist optional und wird ohne Angabe nicht gesetzt; der Export-Endpoint liefert dann den kompletten Datensatz (v2.1-Spec, Parameter `limit_export`: Default `-1`, «Use -1 (default) to retrieve all records»). Die gesamte Antwort wird in den RAM des Pi geladen (`response.json()`) und inline über MCP zurückgegeben. SKILL.md deklariert `get_export` als Standardweg für >100 Zeilen, ein Aufruf ohne `where`/`group_by` auf einem grossen Datensatz ist also ein realistischer Agenten-Fehltritt, kein Randfall.
- Auswirkung: Out-of-Memory oder Minutenblockade auf dem Pi (Betriebsausfall), gesprengtes Kontextfenster beim Client, 30s-Timeout-Abbrüche mitten im Download.
- Fix (Default-Deckel mit explizitem Opt-out):

```python
EXPORT_MAX_ROWS = 20000

async def get_export(..., limit: int | None = None, ...) -> dict:
    params = {...}
    params["limit"] = limit if limit is not None else EXPORT_MAX_ROWS
    data = await fetch(f"/catalog/datasets/{dataset_id}/exports/json", params)
    n = len(data) if isinstance(data, list) else None
    return {
        "count": n,
        "truncated": limit is None and n == EXPORT_MAX_ROWS,
        "results": data,
    }
```

  Zusätzlich im Docstring: bei `truncated: true` mit `where`/`group_by` einschränken oder `export_dataset_url` verwenden. Optional Response-Grösse via `Content-Length` vorab prüfen.

## A3. records_count in get_datasets immer null (falsches Metadaten-Resultat)

- Severity: mittel (an der Grenze zu kritisch: irreführendes Resultat an den Nutzer, aber null statt falscher Zahl)
- Kategorie: Fachlich / Code
- Fundstelle: `_simplify_dataset`, main.py:75: `"records_count": explore.get("records_count")`
- Status: bestätigt (live verifiziert: `get_datasets` liefert für alle Treffer `"records_count": null`, `get_dataset` liefert für denselben Datensatz korrekt 344085)
- Problem: Die API liefert `records_count` unter `metas.default.records_count` (so auch die Beispiele in der OpenAPI-Spezifikation), der Code liest aber `metas.explore`. Commit ad9f2f1 («fixed records_count selection in get_dataset») hat nur `get_dataset` korrigiert, `_simplify_dataset` wurde vergessen.
- Auswirkung: Ein Agent kann die Datensatzgrösse im Suchergebnis nicht einschätzen und die Weiche get_records vs. get_export nicht früh stellen; das Feld ist toter Ballast.
- Fix:

```python
-        "records_count": explore.get("records_count"),
+        "records_count": default.get("records_count") or explore.get("records_count"),
```

## A4. Kein Handling von Netzwerkfehlern, Timeouts und Rate Limits in fetch()

- Severity: mittel
- Kategorie: Code / Betrieb
- Fundstelle: `fetch`, main.py:41-53
- Status: bestätigt
- Problem: `fetch()` behandelt nur HTTP-Status >= 400. `httpx.ConnectError`, `httpx.ReadTimeout` etc. (Netzunterbruch, DNS, ngrok-Reconnect-Phasen) propagieren als rohe Exceptions; es gibt keinen Retry und keine Sonderbehandlung von 429 (Spec: errorcode 10002 mit `reset_time`).
- Auswirkung: Bei transienten Fehlern erhält der Agent kryptische Tracebacks statt einer handlungsleitenden Meldung; jeder kurze Netzwackler schlägt sofort durch.
- Fix (Kern):

```python
import asyncio

async def fetch(endpoint, params=None):
    for attempt in range(3):
        try:
            response = await _client.get(endpoint, params=params)
            break
        except httpx.TransportError as exc:
            if attempt == 2:
                raise RuntimeError(f"Netzwerkfehler nach 3 Versuchen: {exc!r}") from exc
            await asyncio.sleep(2 ** attempt)
    if response.status_code == 429:
        raise RuntimeError("ODS 429: Domain-Quota erschöpft, später erneut versuchen "
                           f"(Retry-After: {response.headers.get('Retry-After', 'unbekannt')})")
    ...
```

## A5. Neuer AsyncClient pro Request (kein Connection Pooling)

- Severity: mittel
- Kategorie: Code / Betrieb
- Fundstelle: `fetch`, main.py:42: `async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:`
- Status: bestätigt
- Problem: Pro Tool-Aufruf wird ein neuer Client samt TCP- und TLS-Handshake aufgebaut und wieder abgerissen.
- Auswirkung: Unnötige Latenz pro Call (auf dem Pi spürbar), unnötige Last; bei parallelen Requests viele kurzlebige Sockets.
- Fix: Modulglobalen Client verwenden: `_client = httpx.AsyncClient(base_url=BASE_URL, timeout=httpx.Timeout(30.0, connect=10.0), limits=httpx.Limits(max_connections=10))`, in `fetch()` nutzen; kein `async with` pro Call. httpx handhabt Reconnects im Pool selbst.

## A6. Kein Logging

- Severity: mittel
- Kategorie: Code / Betrieb
- Fundstelle: main.py gesamt (kein `import logging`, keine Log-Aufrufe)
- Status: bestätigt
- Problem: Der Server loggt weder eingehende Tool-Aufrufe noch ausgehende ODS-Requests noch Fehler. Im systemd-Journal erscheint nur, was FastMCP/uvicorn selbst ausgibt.
- Auswirkung: Produktionsdebugging (welche Query hat den 400 ausgelöst, wer ruft den ungesicherten Endpoint auf) ist praktisch unmöglich; gerade in Kombination mit A1 fehlt jede Missbrauchs-Sichtbarkeit.
- Fix: `logging.basicConfig(level=logging.INFO)` und in `fetch()` einen INFO-Log pro Request (Endpoint plus Parameter, ohne Secrets) sowie WARNING bei Status >= 400 inkl. ODS-Fehlertext. Journald übernimmt Rotation.

## A7. Reservierte ODSQL-Keywords unvollständig in ODS_RESERVED

- Severity: mittel
- Kategorie: Fachlich
- Fundstelle: `ODS_RESERVED`, main.py:83-88
- Status: bestätigt (Abgleich mit der Keyword-Liste im Abschnitt «Reserved keywords in ODSQL clauses»; die Liste ist in v2.0 und v2.1 identisch, der Befund gilt also auch gegen die produktiv genutzte Version)
- Problem: Gegenüber der offiziellen Liste fehlen: `date_format`, `dayofweek`, `equi`, `ifnull`, `lower`, `upper`, `millisecond`, `quarter`, `search`. Die zusätzlichen Einträge im Code (`like`, `in`, `date`, `datetime`, `from`, `offset`) sind unschädlich (Über-Escaping ist erlaubt), die fehlenden aber nicht: ein Feld namens z.B. `search` oder `quarter` erhält einen falschen (ungebacktickten) `odsql_name`.
- Auswirkung: `get_dataset` liefert für betroffene Felder einen `odsql_name`, der in `where`/`select` einen 400 oder eine Fehlinterpretation auslöst; SKILL.md verweist Agenten explizit auf `odsql_name` als verlässliche Quelle.
- Fix: Liste mit der Spezifikation synchronisieren:

```python
ODS_RESERVED = {
    "and", "as", "asc", "avg", "by", "count", "date_format", "day", "dayofweek",
    "desc", "distinct", "equi", "false", "group", "hour", "ifnull", "or", "limit",
    "lower", "max", "millisecond", "min", "minute", "month", "not", "null",
    "quarter", "range", "search", "second", "select", "sum", "top", "true",
    "upper", "where", "year",
    # defensiv, nicht in der Spec-Liste, aber harmlos:
    "like", "in", "date", "datetime", "from", "offset",
}
```

## A8. search_mode ist freier String, Tippfehler fallen still auf semantic zurück

- Severity: mittel
- Kategorie: Code
- Fundstelle: `get_datasets`, main.py:111 und main.py:157-162
- Status: bestätigt
- Problem: `search_mode: str = "semantic"`; die Verzweigung prüft nur `if search_mode == "lexical"`, jeder andere Wert (z.B. "Lexical", "fulltext") läuft kommentarlos in den semantischen Zweig.
- Auswirkung: Ein Agent, der lexikalisch suchen will, erhält still ein semantisches Ranking; zudem wird `order_by` in diesem Fall still überschrieben (main.py:162).
- Fix: `search_mode: Literal["semantic", "lexical"] = "semantic"` (Literal ist bereits importiert). Pydantic validiert dann automatisch auf Schema-Ebene.

## A19. Semantische Suche ohne Relevanz-Schwelle: vector_similarity_threshold() ungenutzt

- Severity: mittel
- Kategorie: Fachlich
- Fundstelle: `get_datasets`, main.py:162: `params["order_by"] = f'vector_similarity("{query}") desc'`
- Status: bestätigt (v2.1-Spec dokumentiert beide Funktionen; Live-Verhalten konsistent: `total_count` entspricht der ungefilterten Grundmenge). Verfügbarkeit von `vector_similarity_threshold()` auf data.gr.ch selbst: vermutet, aus der Audit-Umgebung nicht direkt testbar (plausibel, da `vector_similarity()` auf dem Portal nachweislich funktioniert und dieselbe Embedding-Infrastruktur voraussetzt); vor dem Deployment mit einem Testaufruf verifizieren.
- Problem: Der semantische Modus sortiert nur (`vector_similarity()` ist laut v2.1-Referenz ausschliesslich in `order_by` erlaubt und «returns all catalog results»). Die v2.1-Referenz bietet dafür `vector_similarity_threshold()` als `where`-Prädikat für die Katalogsuche an, das über einen automatischen Score-Cutoff (Kneedle-Algorithmus) irrelevante Datensätze aus dem Resultat entfernt.
- Auswirkung: `total_count` ist im semantischen Modus bedeutungslos (gesamter Katalog statt Treffermenge), und die Resultatliste enthält am Ende garantiert irrelevante Einträge, die der Agent selbst aussortieren muss. Kombination mit `refine`/`exclude` liefert gefilterte, aber weiterhin ungewichtete Zählwerte.
- Fix: Im semantischen Zweig zusätzlich das Threshold-Prädikat setzen, Sortierung beibehalten:

```python
        else:
-            params["order_by"] = f'vector_similarity("{query}") desc'
+            params["where"] = f'vector_similarity_threshold("{query}")'
+            params["order_by"] = f'vector_similarity("{query}") desc'
```

  Danach ist `total_count` die tatsächliche Treffermenge; Docstring (main.py:139-141) und SKILL.md entsprechend anpassen. Hinweis der Referenz beachten: die Threshold-Methode kann in Randfällen relevante Treffer abschneiden; falls 0 Treffer, als Fallback ohne `where` wiederholen.

## A9. HTML-Descriptions ungefiltert (Token-Ballast)

- Severity: mittel
- Kategorie: Code
- Fundstelle: `_simplify_dataset`, main.py:69 und `get_dataset`, main.py:192
- Status: bestätigt (live: einzelne Beschreibungen >5 KB rohes HTML inkl. Inline-Styles)
- Problem: `description` wird 1:1 durchgereicht, inklusive `style="..."`-Attributen von mehreren Kilobytes pro Datensatz.
- Auswirkung: Eine Suche mit `limit=10` kann zehntausende Tokens Kontext verbrennen, der Informationsgehalt steckt in einem Bruchteil davon.
- Fix: Tags strippen und kürzen, z.B.

```python
import re
def _strip_html(text: str, max_len: int = 800) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = " ".join(text.split())
    return text[:max_len] + ("…" if len(text) > max_len else "")
```

  In `_simplify_dataset` kurz strippen; in `get_dataset` allenfalls voller (gestrippter) Text.

## A10. systemd- und ngrok-Konfiguration nicht versioniert

- Severity: mittel
- Kategorie: Betrieb / Struktur
- Fundstelle: Repo-Root (keine `*.service`-, keine ngrok-Datei vorhanden)
- Status: bestätigt (Absenz); Verhalten der Live-Deployment-Konfiguration vermutet
- Problem: Der produktive Betrieb (systemd Unit, ngrok-Tunnel-Definition) ist nirgends im Repo dokumentiert oder versioniert. Restart-Policy, `MemoryMax`, ngrok-Authtoken-Handling und Reconnect-Verhalten sind nicht auditierbar und bei einem SD-Karten-Defekt nicht reproduzierbar.
- Auswirkung: Kein definiertes Verhalten bei Absturz oder Netzunterbruch nachweisbar; Wiederaufbau des Pi ist Handarbeit.
- Fix: `deploy/mcp-gr.service` und `deploy/ngrok.yml` (ohne Authtoken, dieser via `EnvironmentFile`) einchecken. Empfehlung für die Unit:

```ini
[Service]
ExecStart=/usr/local/bin/uv run --directory /opt/mcp-data-gr main.py
Restart=on-failure
RestartSec=5
MemoryMax=512M
User=mcp
[Install]
WantedBy=multi-user.target
```

## A11. Keine Tests, kein CI

- Severity: mittel
- Kategorie: Struktur
- Fundstelle: Repo gesamt (keine `tests/`, keine CI-Workflows)
- Status: bestätigt
- Problem: Null Testabdeckung. Der Bug A3 (records_count) ist genau die Klasse Fehler, die ein Unit-Test mit einer festen Beispiel-Response sofort gefangen hätte; er wurde in Commit ad9f2f1 schon einmal halb gefixt.
- Auswirkung: Regressionsrisiko bei jedem Refactoring; Response-Mapping-Fehler fallen erst in Produktion auf.
- Fix: pytest plus `respx` (httpx-Mocking). Prioritäre Fälle: `_simplify_dataset` (records_count, HTML-Strip), `_odsql_safe` (Ziffern, Keywords, Normalfall), `_escape_odsql`, `get_datasets` Query-Bau (lexical vs. semantic), `fetch` Fehlerpfade (400 mit ODS-Body, 429, Timeout).

## A12. Stille Limit-Kappung auf 100 im Client

- Severity: niedrig
- Kategorie: Code
- Fundstelle: `get_records`, main.py:262-263: `max_limit = 20000 if group_by else 100` / `min(limit, max_limit)`
- Status: bestätigt
- Problem: Ein `limit=500` ohne `group_by` wird kommentarlos auf 100 reduziert; die Antwort enthält keinen Hinweis auf die Kappung (nur indirekt via `total_count`).
- Auswirkung: Gering, da Docstring und SKILL.md das Verhalten beschreiben; dennoch stilles Abweichen vom angefragten Parameter.
- Fix: Bei Kappung ein Feld `"note": "limit auf 100 gekappt (ohne group_by); get_export verwenden"` in die Antwort mergen, oder alternativ einen Fehler werfen.

## A13. offset+limit-Grenze der API nicht validiert

- Severity: niedrig
- Kategorie: Fachlich
- Fundstelle: `get_records`, main.py:230-231
- Status: bestätigt (v2.0 und v2.1 identisch: ohne group_by muss offset+limit < 10000 sein, mit group_by < 20000)
- Problem: Der Server validiert `limit` (le=20000) und `offset` (ge=0) einzeln, nicht die Summe. Der ODS-400 wird zwar durchgereicht (gut), aber vermeidbar.
- Auswirkung: Vermeidbarer Fehlversuch bei tiefer Pagination; SKILL.md rät ohnehin von Pagination ab.
- Fix: Vorab-Check mit sprechender Meldung («offset+limit >= 10000: get_export verwenden») oder Hinweis im Docstring ergänzen.

## A14. _to_str verschluckt falsy Werte (0, False)

- Severity: niedrig
- Kategorie: Code
- Fundstelle: `_to_str`, main.py:59: `return str(value) if value else ""`
- Status: bestätigt
- Problem: `0` oder `False` werden zu `""` statt `"0"`/`"False"`.
- Auswirkung: Bei den aktuell gemappten Feldern (title, theme, publisher) praktisch irrelevant, aber eine Falle bei Wiederverwendung.
- Fix: `return "" if value is None else str(value)`.

## A15. language: Docstring verspricht Liste, API liefert String

- Severity: niedrig
- Kategorie: Code
- Fundstelle: `_simplify_dataset`, main.py:74 und `get_dataset`, main.py:197
- Status: bestätigt (live: `"language": "de"` als String)
- Problem: `default.get("language", []) or []` reicht einen String unverändert durch; der deklarierte Rückgabetyp (Liste) stimmt nicht immer.
- Auswirkung: Typinkonsistenz für Konsumenten; harmlos für LLM-Agenten.
- Fix: normalisieren: `lang_val = default.get("language"); "language": lang_val if isinstance(lang_val, list) else ([lang_val] if lang_val else [])`.

## A16. get_facets: unbekannte Facette liefert stillschweigend die Rohantwort

- Severity: niedrig
- Kategorie: Code
- Fundstelle: `get_facets`, main.py:308-313
- Status: bestätigt
- Problem: Wird `facet` übergeben, aber im Response nicht gefunden, fällt die Funktion still auf `return data` (alle Facetten) zurück statt einen Hinweis zu geben.
- Auswirkung: Agent bemerkt Tippfehler im Facettennamen möglicherweise nicht.
- Fix: `return {"facet": facet, "values": [], "note": f"Facette '{facet}' existiert nicht. Verfügbar: {[f['name'] for f in data.get('facets', [])]}"}`.

## A17. Namens- und Doku-Altlasten aus dem data.bs-Fork

- Severity: niedrig
- Kategorie: Struktur
- Fundstelle: pyproject.toml:2-4 (`name = "data-bs-mcp"`, `description = "MCP server for data.bs.ch..."`), README.md:1, README.md:24 (`uvx --from git+https://github.com/DCC-BS/mcp-data-bs ...`)
- Status: bestätigt
- Problem: Projektname, Beschreibung und Installationsanleitung referenzieren das Ursprungsprojekt. Die uvx-Zeile installiert ein fremdes Repo (DCC-BS/mcp-data-bs), das auf data.bl.ch/data.bs.ch zeigen kann.
- Auswirkung: Verwirrung und potenziell falsches Deployment beim Wiederaufsetzen.
- Fix: Umbenennen auf `mcp-data-gr`, README-Beispiele auf data.gr.ch und das eigene Repo umstellen.

## A18. README-Formatliste weicht vom Tool ab

- Severity: niedrig
- Kategorie: Struktur
- Fundstelle: README.md:172 («Formats: csv, json, geojson, xlsx, shp, parquet, gpx, kml, rdfxml, jsonld, turtle») vs. main.py:358 (`Literal["csv", "json", "geojson", "xlsx", "shp", "parquet"]`)
- Status: bestätigt
- Problem: README verspricht fünf Formate mehr, als das Tool-Schema zulässt.
- Auswirkung: Doku-Drift, Fehlversuche.
- Fix: README angleichen oder das Literal erweitern (gpx/kml sind laut Spec nur für Geo-Datensätze sinnvoll).

## Spec-Abgleich (v2.1), weitere Feststellungen (ohne eigene Severity)

- `group_by` auf `/exports/{format}` ist in v2.1 offiziell dokumentiert (v2.1-Changelog: «the group_by clause is now available on export endpoints») und live verifiziert. In v2.0 existierte der Parameter nicht; die Tools sind hier v2.1-konform. Kein Handlungsbedarf.
- `include_app_metas` (main.py:116) und `vector_similarity` (main.py:162) sind in v2.1 dokumentiert (getDatasets-Parameter bzw. ODSQL-Funktionsreferenz). Beide Befunde damit von «vermutet» auf bestätigt hochgestuft.
- `get_records` könnte in v2.1 zusätzlich `include_app_metas` exponieren (Parameter existiert am Records-Endpoint); geringer Nutzen, optional.
- v2.1-Changelog bestätigt weitere im Code/Skill vorausgesetzte Verhalten: `year()`/`month()`/`day()` liefern Integer (vorher Strings), CSV-Exporte enthalten per Default ein BOM, XLSX ersetzt XLS, `distance()` heisst neu `within_distance()`.
- `lang` wird nicht gegen das Spec-Enum (en, fr, de, it, ...) validiert; ungültige Werte erzeugen einen durchgereichten API-Fehler. Akzeptabel.
- Injection-Risiko insgesamt gering: Die API ist read-only (nur GET), die Domain ist fest verdrahtet (main.py:36), `where`/`select`/`group_by` sind bewusste ODSQL-Passthroughs, und der einzige vom Server interpolierte Nutzerwert (`search`) wird escaped (main.py:79-80). Das Escaping ist durch die v2.1-Referenz gedeckt: String-Literale erlauben einfache oder doppelte Anführungszeichen, `\` dient als Escape-Zeichen; `_escape_odsql` escapt genau Backslash und doppelte Anführungszeichen für den doppelt-quotierten Kontext. `dataset_id` wird unverändert in den Pfad interpoliert (main.py:187 u.a.); httpx encodiert Sonderzeichen, ein Traversal über `../` gegen dieselbe Host-API bleibt theoretisch denkbar, ist aber ohne Schadpotenzial (gleiches, öffentliches API).
- Die Explore API unterstützt Authentifizierung via API-Key und OAuth2 (v2.1-Abschnitt «Authentication»). data.gr.ch ist öffentlich, `fetch()` hat keinerlei Key-Mechanismus; sollte das Portal je Quota-gebundene Keys einführen, wäre eine Erweiterung nötig (kein aktueller Handlungsbedarf).
- `dataset_uid`: Die Spezifikation führt `dataset_uid` als eigenes Feld im Dataset-Schema; weder die Tools noch SKILL.md exponieren oder erwähnen es. Alle Tools verwenden konsistent `dataset_id` als Pfadparameter, was der Spezifikation entspricht. Keine Inkonsistenz gefunden; die im Audit-Auftrag genannte Äquivalenz ist im Projekt schlicht nirgends dokumentiert (bestätigte Absenz).

---

# Teil B: Neue Tool-Vorschläge (Basis OpenAPI)

## B1. get_record

- Zweck: Einzelnen Record über seine ID holen (Detailansicht, Nachschlagen nach vorheriger Suche).
- Endpoint: GET /catalog/datasets/{dataset_id}/records/{record_id} (operationId getRecord)
- Parameter: dataset_id (string, Pflicht), record_id (string, Pflicht), select (string, optional), lang (string, optional)
- Anwendungsfall: Agent hat via get_records eine Trefferliste und will einen Datensatz vollständig, ohne die Query zu wiederholen.
- Aufwand: klein

## B2. get_dataset_attachments

- Zweck: Anhänge eines Datensatzes auflisten (Methodik-PDFs, Codelisten, Erläuterungen).
- Endpoint: GET /catalog/datasets/{dataset_id}/attachments (operationId getDatasetAttachments)
- Parameter: dataset_id (string, Pflicht)
- Anwendungsfall: Fragen zur Methodik («wie ist X definiert») lassen sich oft nur über die Begleitdokumente beantworten; heute für den Agenten unsichtbar.
- Aufwand: klein

## B3. list_export_formats

- Zweck: Tatsächlich verfügbare Exportformate pro Datensatz abfragen statt raten.
- Endpoint: GET /catalog/datasets/{dataset_id}/exports (operationId listDatasetExportFormats)
- Parameter: dataset_id (string, Pflicht)
- Anwendungsfall: Vor `export_dataset_url(format="shp")` prüfen, ob der Datensatz überhaupt Geodaten exportiert; behebt zugleich die Format-Drift aus A18.
- Aufwand: klein

## B4. export_catalog_url

- Zweck: Den gesamten Katalog als Datei exportieren (Inventar, Reporting).
- Endpoint: GET /catalog/exports/{format} (operationId exportDatasets; Formate u.a. csv, xls, json, dcat_ap_ch)
- Parameter: format (enum, Pflicht), select/where/order_by/limit (string/int, optional)
- Anwendungsfall: «Liste aller Datensätze des Kantons als Excel» ohne 100er-Pagination über get_datasets.
- Aufwand: klein

## B5. Erweiterung get_dataset_facets um where/refine

- Zweck: Facettenwerte im Kontext eines Filters zählen (z.B. Gemeinden, die 2024 Werte haben).
- Endpoint: GET /catalog/datasets/{dataset_id}/facets unterstützt laut Spec bereits where, refine, exclude, timezone; das Tool exponiert nur facet und lang (main.py:324-344).
- Parameter (neu): where (string, optional), refine (string, optional), exclude (string, optional)
- Anwendungsfall: Total-Zeilen-Erkennung und Wertelisten unter Vorfilter, ohne group_by-Umweg über get_records.
- Aufwand: klein

## B6. Erweiterung export_dataset_url um Format-Detailparameter

- Zweck: Praxistaugliche CSV/Geo-Exporte.
- Endpoint: GET .../exports/csv (delimiter, list_separator, quote_all, with_bom), GET .../exports/{format} (use_labels, epsg, compressed)
- Parameter (neu, alle optional): delimiter (enum ;,|\t), with_bom (bool), use_labels (bool), epsg (int), compressed (bool)
- Anwendungsfall: Excel-kompatible CSVs (Semikolon plus BOM), Geodaten in LV95 (epsg=2056) statt WGS84.
- Aufwand: mittel (Parameter-Validierung je Format)

---

# Teil C: SKILL.md Vorschläge

Zeilenangaben beziehen sich auf die SKILL.md aus `skills/ogd-graubuenden.skill` (identisch mit der hochgeladenen Version, MD5-verifiziert).

Gesamturteil: Die vier Kernpatterns sind abgedeckt und grösstenteils präzise. Facet Inspection (Z. 74-85, 201-221) und die get_export-Schwelle (Z. 100-116) sind klar und mit dem Tool-Verhalten konsistent. Backtick-Escaping (Z. 144-149) ist über den odsql_name-Mechanismus gut gelöst. Die dataset_uid-Äquivalenz fehlt vollständig.

Mehrere fachliche Aussagen des Skills sind durch die v2.1-ODSQL-Referenz nun wörtlich bestätigt: die `search()`-Semantik (Z. 178: Levenshtein-Distanz 2 ab Termlänge >5, Distanz 1 ab >2, Prefix-Match auf dem letzten Wort, case-insensitive), `year()` liefert Integer (Z. 156, v2.1-Changelog), das Aggregat-zuerst-Gebot im order_by (Z. 166, Referenz: «order_by = avg(age), gender works, but order_by = gender, avg(age) returns an error»), das BOM in CSV-Exporten (Z. 132, per Default aktiv) und die Datum-Literal-Syntax (Z. 155; zusätzlich erlaubt die Referenz auch `date'YYYY/MM/DD'`).

## C1. Falsche Kausalität bei der 100-Zeilen-Kappung

- Fundstelle: SKILL.md Z. 100 («der Server kappt auf 100») und Z. 172
- Problem: Faktisch kappt der Connector clientseitig (main.py:263 `min(limit, max_limit)`), nicht der ODS-Server; der Server würde limit>100 mit 400 ablehnen. Für das Agentenverhalten gleichwertig, aber beim Debugging irreführend (Agent sucht den Fehler serverseitig).
- Vorher: «auch wenn `limit` höher gesetzt wird (der Server kappt auf 100)»
- Nachher: «auch wenn `limit` höher gesetzt wird (der Connector kappt ohne `group_by` auf 100, die Antwort enthält keinen Hinweis darauf; deshalb `total_count` prüfen)»

## C2. records_count-Bug nicht erwähnt (bis Fix A3 deployed ist)

- Fundstelle: SKILL.md Z. 34-53 (Schritt 1)
- Problem: `get_datasets` liefert aktuell immer `records_count: null` (Befund A3). Ein Agent, der die Grösse aus dem Suchergebnis ablesen will, erhält keine Information und könnte fälschlich von einem kleinen Datensatz ausgehen.
- Ergänzung (nach dem Suchbeispiel): «`records_count` ist in den Suchresultaten aktuell nicht befüllt. Die verlässliche Zeilenzahl liefert `get_dataset` (Feld `records_count`). Vor jedem `get_export` ohne Filter die Grösse dort prüfen.» (Nach Deployment von Fix A3 anpassen.)

## C3. get_export ohne Filter auf grossen Datensätzen: Warnung fehlt

- Fundstelle: SKILL.md Z. 106-116 (Schritt 6)
- Problem: get_export wird als Standardweg ohne Zeilenlimit beworben, ohne Warnung vor ungefiltertem Volltabellen-Abruf (344k Zeilen bei STATPOP-Datensätzen). Das sprengt Kontextfenster und belastet den Pi (Befund A2).
- Vorher: «Holt die gefilterten oder aggregierten Daten serverseitig ... und gibt sie inline zurück, ohne Zeilenlimit.»
- Nachher: «Holt die gefilterten oder aggregierten Daten serverseitig und gibt sie inline zurück, ohne hartes Zeilenlimit. IMMER mit `where`, `group_by` oder `limit` einschränken. Vorher via `get_dataset` die `records_count` prüfen: über ~20'000 Zeilen nie ungefiltert abrufen, stattdessen aggregieren (`group_by`) oder `export_dataset_url` für den Download anbieten.»

## C4. Reservierte Wortliste unvollständig und leicht abweichend

- Fundstelle: SKILL.md Z. 148
- Problem: Die Auswahl-Liste spiegelt die (unvollständige) Code-Liste. Es fehlen u.a. `search`, `quarter`, `dayofweek`, `ifnull`, `lower`, `upper`; dafür ist `date` gelistet, das in der offiziellen Keyword-Liste (in v2.0 und v2.1 identisch) nicht vorkommt. Da der Skill primär auf `odsql_name` verweist, ist der Schaden begrenzt, aber Liste und Realität sollten übereinstimmen (zusammen mit Fix A7).
- Ergänzung: Liste durch die Spec-Liste ersetzen oder kürzen auf: «Reservierte Wörter siehe API-Doku; im Zweifel schaden Backticks nie: `` `feld` `` ist immer gültig.»

## C5. dataset_uid-Äquivalenz nirgends dokumentiert

- Fundstelle: SKILL.md gesamt (Absenz), betrifft auch main.py (Tools geben nur dataset_id zurück)
- Problem: Die API kennt `dataset_id` und `dataset_uid`. Tools und Skill arbeiten durchgängig und korrekt mit `dataset_id`; falls ein Nutzer oder eine externe Quelle eine `uid` (Format `da_...`) liefert, hat der Agent keine Anleitung.
- Ergänzung (Abschnitt Fallstricke): «Datensätze werden ausschliesslich über `dataset_id` angesprochen (z.B. `dvs_awt_soci_20250507`). Eine `dataset_uid` (Format `da_...`) aus externen Quellen zuerst via `get_datasets` (lexical) auf die `dataset_id` auflösen.»

## C6. Semantik von total_count im semantischen Modus fehlt

- Fundstelle: SKILL.md Z. 34-44 (Schritt 1)
- Problem: Im semantischen Modus wird der Katalog gerankt, nicht gefiltert; `total_count` entspricht dann nicht der Treffermenge (das Tool-Docstring in main.py:139-141 dokumentiert das, der Skill nicht). Die v2.1-Referenz bestätigt: `vector_similarity()` in `order_by` «returns all catalog results». Ein Agent könnte «47 Treffer» berichten, obwohl das die Katalog- bzw. Ranking-Grundmenge ist.
- Ergänzung: «Im `semantic`-Modus ist `total_count` NICHT die Zahl relevanter Treffer (der ganze Katalog wird gerankt). Relevanz selbst beurteilen, `total_count` nicht als Trefferzahl kommunizieren.»
- Nachhaltige Lösung ist serverseitig: Befund A19 (Umstellung auf `vector_similarity_threshold()` im `where`); danach ist `total_count` aussagekräftig und dieser Skill-Hinweis kann wieder entfallen.

## C7. Fallstricke, die der Skill abdeckt (bestätigt) und verbleibende Lücken

Ohne den Skill läuft ein Agent nachweislich in diese vom Skill abgedeckten Fallen: Doppelzählung durch Total-Zeilen (Z. 192-199, inkl. BEVNAT-Beispiel mit konkretem where), stille 10-Zeilen-Trunkierung durch das Default-Limit (Z. 171), 100-Zeilen-Grenze (Z. 172-173), Aggregat-Position im order_by (Z. 166), Backticks (Z. 144-149), Facetten-Verifikation vor exaktem `=` (Z. 201-221), BOM in CSV (Z. 132), Export-URL nicht im Container laden (Z. 131).

Verbleibende Lücken (im Skill ergänzen):
- offset+limit muss ohne group_by unter 10'000 bleiben (Spec); relevant, falls doch paginiert wird.
- Verhalten bei 429/Quota (errorcode 10002): warten und Aufrufe bündeln statt sofort neu versuchen.
- `exclude`-Parameter als Gegenstück zu `refine` wird nirgends erwähnt.
- Hinweis, dass `bfs_nummer` in mehreren Datensätzen als Text-Feld geführt wird (live verifiziert in `dvs_awt_soci_20250507`): Joins und Vergleiche als String, nicht als Zahl (`bfs_nummer = '3901'`).

## C8. Struktur (Auffindbarkeit)

- Fundstelle: SKILL.md gesamt
- Problem: Die Regeln (Z. 239-252) fassen gut zusammen, stehen aber ganz am Ende; die ODSQL-Syntax steht nach dem Workflow. Ein Agent, der mitten in der Tool-Nutzung einen 400 debuggt, muss weit scrollen.
- Vorschlag: Direkt nach dem Connector-Block eine kompakte Schnellreferenz (10 Zeilen) einfügen: odsql_name verwenden, limit explizit, total_count prüfen, refine für Gleichheit, get_export ab >100 Zeilen mit Filterpflicht, Aggregat zuerst im order_by, Total-Zeilen filtern. Details bleiben in den bestehenden Abschnitten.
