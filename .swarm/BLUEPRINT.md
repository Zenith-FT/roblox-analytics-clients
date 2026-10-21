# BLUEPRINT — `romonitorstats.py` + `rolimons.py`

**Epic:** Roblox Analytics Clients (see `.swarm/PLAN.md`)
**Reference implementation (authoritative for style):** `rotrend.py` (439 lines, proven)
**Audience:** worker B1 (`romonitorstats.py`), worker B2 (`rolimons.py`) — parallel, disjoint files
**Research inputs:** `.research/romonitorstats.md`, `.research/rolimons.md` (written by R1/R2 — may not exist yet)

**Rules for both workers**

1. Copy §1 of this blueprint **verbatim** into your file, then substitute the placeholders listed in §2.
2. Every public function returns a plain `dict` or `list[dict]`. No classes, no global state, no `argparse`.
3. Docstrings **in French**. Each function docstring names the **endpoint it hits**.
4. Only stdlib + `curl_cffi`. **Never** `import base64`. Never plain `requests` (Cloudflare blocks it).
5. Every CLI command prints a human-readable header line first, then JSON via `pp()`.
6. Do **not** edit `rotrend.py`, `PLAN.md`, or anything in `.research/`.

---

## 1. The shared skeleton

Copy this block as the *base* of your file. Placeholders are `UPPER_SNAKE` in `{braces}`.
Substitutions per site are listed in §2.1 (romonitorstats) and §2.2 (rolimons).

```python
"""
{SITE_NAME}.py — Client Python pour l'API {BASE_URL}

Données publiques en temps réel, format JSON propre.

{AUTH_NOTE}

Points d'attention de l'API (voir .research/{SITE_NAME}.md) :
  - <REMPLIR : quirks réels observés sur cet endpoint>
  - <REMPLIR : un quirk par ligne>
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from curl_cffi import requests

# La console Windows est souvent en cp1252 : les noms d'objets contiennent des emoji
# qui font planter print(). On force l'UTF-8 avec remplacement.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE_URL = "{BASE_URL}"

# ─── Headers de base ──────────────────────────────────────────────────────────
# ⚠ SUBSTITUTION PAR SITE (voir §2) :
#   - "origin" / "referer" → le SITE lui-même (pas un sous-domaine API)
#   - "sec-fetch-site"    → "same-origin" si l'API est sur le domaine du site,
#                          "cross-site" si l'API est sur un sous-domaine
#   - "accept"            → include "text/html" si certains endpoints renvoient du HTML
#   - "user-agent"        → laisser curl_cffi le gérer via impersonate="chrome"
#                          (recommandé) ou UA Chrome cohérent avec sec-ch-ua
BASE_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "content-type": "application/json",
    "origin": "{SITE_ORIGIN}",
    "referer": "{SITE_REFERER}",
    "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "{SAME_OR_CROSS_SITE}",
}


class ApiError(RuntimeError):
    """Erreur renvoyée par l'API {SITE_NAME} (enveloppe success/message)."""


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _unwrap(data):
    """Lève une ApiError si l'enveloppe signale une erreur."""
    if isinstance(data, dict):
        if data.get("success") is False:
            msg = data.get("message") or ""
            errs = (data.get("data") or {}).get("error_messages")
            if errs:
                msg = "; ".join(errs)
            raise ApiError(msg or json.dumps(data)[:300])
        if data.get("ok") is False:                       # variante d'enveloppe
            raise ApiError(data.get("message") or data.get("error") or json.dumps(data)[:300])
        if str(data.get("status", "")).lower() in ("error", "failed", "failure"):
            raise ApiError(data.get("message") or data.get("error") or json.dumps(data)[:300])
    return data


def _data(payload):
    """Déballe l'enveloppe {"data": ...} si elle est présente (sinon renvoie le payload)."""
    if isinstance(payload, dict) and "data" in payload:
        return payload.get("data")
    return payload


def _check(data):
    """Lève une ApiError si _get/_post a renvoyé une erreur HTTP ou un corps non-JSON."""
    if isinstance(data, dict) and "error" in data:
        raise ApiError(
            f"erreur HTTP/format : {data.get('error')} — {str(data.get('detail'))[:200]}"
        )
    return data


def _get(path: str, params: dict = None) -> dict:
    """GET sur l'API {SITE_NAME}. Retourne le JSON décodé, ou {"error": ..., "detail": ...}."""
    url = BASE_URL + path
    resp = requests.get(url, params=params, headers=BASE_HEADERS, impersonate="chrome")
    if resp.status_code != 200:
        return {"error": resp.status_code, "detail": resp.text[:500]}
    try:
        return _unwrap(resp.json())
    except ApiError:
        raise
    except Exception:
        return {"error": "decode", "detail": resp.text[:500]}


def _post(path: str, body: dict = None, params: dict = None) -> dict:
    """POST sur l'API {SITE_NAME}. `params` part en QUERY STRING, `body` en JSON."""
    url = BASE_URL + path
    resp = requests.post(url, json=body if body is not None else {}, params=params,
                         headers=BASE_HEADERS, impersonate="chrome")
    if resp.status_code != 200:
        return {"error": resp.status_code, "detail": resp.text[:500]}
    try:
        return _unwrap(resp.json())
    except ApiError:
        raise
    except Exception:
        return {"error": "decode", "detail": resp.text[:500]}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _days_ago_iso(days: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _today_iso() -> str:
    """Date du jour au format YYYY-MM-DD (certains endpoints n'acceptent pas l'horodatage complet)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ─── API {SITE_NAME} ──────────────────────────────────────────────────────────
#
# <REMPLIR : une fonction par endpoint confirmé dans .research/{SITE_NAME}.md>
#
# Règles :
#   * chaque appel HTTP passe par _check(_get(...)) / _check(_post(...))
#   * docstring = une ligne "Que fait la fonction." + une ligne "Endpoint : <METHOD> <path>"
#   * les filtres optionnels ne sont ajoutés au params que s'ils sont non-None


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    def pp(obj):
        print(json.dumps(obj, indent=2, ensure_ascii=False))

    def _int_arg(default):
        """sys.argv[2] en int, avec fallback silencieux sur une valeur illisible."""
        try:
            return int(sys.argv[2])
        except (IndexError, ValueError):
            return default

    def _text_arg(default):
        """sys.argv[2:] complet en texte (permet les espaces : "search dead rails")."""
        parts = sys.argv[2:]
        return " ".join(parts) if parts else default

    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"

    try:
        if cmd == "{COMMAND_1}":
            print("=== {HEADER_1} ===")
            pp({CALL_1})

        elif cmd == "{COMMAND_2}":
            print("=== {HEADER_2} ===")
            pp({CALL_2})

        # ... une branche par commande ...

        else:
            print("""
Usage : python {SCRIPT_NAME}.py <commande> [args]

Commandes disponibles :
{COMMAND_LIST}

Exemples :
{EXAMPLES}

{AUTH_NOTE}
""")

    except ApiError as e:
        pp({"error": str(e)})
        sys.exit(1)
```

### 1.1 Deviations from `rotrend.py` (deliberate, keep them)

| rotrend.py | Blueprint | Why |
|---|---|---|
| `import base64` + fallback `base64.b64decode(text)` | **removed** | the vestigial fallback in `rotrend.py` is dead code for JSON APIs *and* it silently swallows a Cloudflare HTML page into `{"raw": "<html>…"}` with exit code 0 |
| `return {"raw": text}` on decode failure | **`{"error": "decode", "detail": …}`** | a failed decode must be visible, not look like an empty success |
| no `_check()` | **`_check()` added**, called by every public function | `_get` returns an *error dict* instead of raising; without `_check` the CLI prints `{}` and exits 0 on a 403/404/429 |
| CLI dispatch not wrapped | **`try/except ApiError` → `pp({"error": …})` + `sys.exit(1)`** | the verification gate demands "no tracebacks" and a meaningful exit code |
| `_unwrap` only knows `success is False` | **also knows `ok is False` and `status in (error/failed/failure)`** | rolimons-family APIs use several envelope shapes; keep the rotrends branch first so behaviour is unchanged when `success` is present |
| — | **`_data()` added** | one-liner to unwrap `{"data": …}`; harmless if the endpoint returns a bare list |
| — | **`_today_iso()` added** | some endpoints only accept `YYYY-MM-DD` |
| `sys.argv[2]` inline `int(...)` | **`_int_arg()` / `_text_arg()` helpers** | `int(sys.argv[2])` raises `ValueError` → traceback on a bad argument |

**Do not change:** the UTF-8 guard, the `_now_iso` / `_days_ago_iso` bodies (copy verbatim), the `ApiError` class, the `pp()` printer, the `else:` usage block shape.

---

## 2. Per-site fill-in checklist

### 2.1 `romonitorstats.py`

**Path:** `C:\Users\Zenith\Tools\roblox-scripting\romonitorstats.py`

#### Header / constant substitutions

| Placeholder | Value | Note |
|---|---|---|
| `{SITE_NAME}` | `romonitorstats` | also the `.research` filename |
| `{BASE_URL}` | `https://romonitorstats.com` | **no trailing slash** — the skeleton concatenates `BASE_URL + path` |
| `{SITE_ORIGIN}` | `https://romonitorstats.com` | the site's own domain, **not** an api subdomain |
| `{SITE_REFERER}` | `https://romonitorstats.com/` | trailing slash |
| `{SAME_OR_CROSS_SITE}` | `same-origin` if the API lives under `/api/` on the same host — **confirm** from the research file; use `cross-site` only if the API is on another host |
| `accept` | keep `application/json, text/plain, */*`; add `text/html` **only** if an endpoint returns an HTML fragment | mixing is harmless; omitting `text/html` breaks HTML-ish endpoints |
| `user-agent` | **omit it** — `impersonate="chrome"` sets a coherent Chrome UA + sec-ch-ua | a hand-written UA that disagrees with `sec-ch-ua` is a Cloudflare tripwire |
| `{AUTH_NOTE}` | `Aucune authentification n'est requise : tous les endpoints publics sont en lecture seule.` | keep the same wording in the module docstring and the usage block |

**Endpoint base note:** if the research file shows the API on a separate host (e.g. `https://api.romonitorstats.com`), then `BASE_URL` = that host, `{SITE_ORIGIN}`/`{SITE_REFERER}` stay on `romonitorstats.com`, and `{SAME_OR_CROSS_SITE}` = `cross-site`.

#### Functions to expose

`endpoint` column: **← CONFIRM from `.research/romonitorstats.md`**. The candidate paths are probes, not facts — replace with the confirmed path.

| # | Function | One-line purpose | Endpoint (candidate) |
|---|---|---|---|
| 1 | `platform_stats(days: int = 14) -> dict` | Global counters (CCU-ish totals, game count, history) | `GET /api/platform/stats` |
| 2 | `top_games(sort: str = "-playing", limit: int = 10, genre: str = None) -> list[dict]` | Ranked games by a sort key | `GET /api/explore/games` |
| 3 | `trending_games(limit: int = 10) -> list[dict]` | Games rising fastest (rank delta) | `GET /api/explore/games` with `sort=-rank_change_day` |
| 4 | `new_games(limit: int = 10, days_old: int = 30) -> list[dict]` | Recently published games | `GET /api/explore/games` with a creation-date filter |
| 5 | `search_games(keyword: str, limit: int = 20) -> list[dict]` | Free-text game search | `GET /api/explore/games` with `keyword=` |
| 6 | `game_details(game_id: int) -> dict` | Single game: name, creator, visits, likes, current stats | `GET /api/game/{game_id}` |
| 7 | `game_visits(game_id: int, days: int = 14) -> list[dict]` | Visit/visitor time series for one game | `GET /api/game/{game_id}/visits` |
| 8 | `game_likes(game_id: int, days: int = 14) -> list[dict]` | Like time series for one game | `GET /api/game/{game_id}/likes` |
| 9 | `game_playtime(game_id: int, days: int = 14) -> list[dict]` | Playtime time series for one game | `GET /api/game/{game_id}/playtime` |
| 10 | `game_changelog(game_id: int, days: int = 14) -> list[dict]` | Name/icon/popularity change history | `GET /api/game/{game_id}/changelog` |
| 11 | `explore_genres(page: int = 1, page_size: int = 20) -> list[dict]` | Genre taxonomy + counts | `GET /api/explore/genres` |
| 12 | `explore_groups(page: int = 1, page_size: int = 20) -> list[dict]` | Roblox groups + stats | `GET /api/explore/groups` |
| 13 | `user_profile(username: str) -> dict` | One player's public stats | `GET /api/user/{username}` |

Minimum bar from PLAN.md: **≥ 6 public functions** — the table has 13, ship at least 9 that you could verify live.
**Keep** the function *names* as written (they are the agreed public API surface between B1/B2/B3); only the endpoints and bodies may change to match reality.

#### CLI command map

| Command | Arg | Function | Header line |
|---|---|---|---|
| `stats` | — | `platform_stats(days=7)` | `=== Stats globales romonitorstats ===` |
| `top` | `[n]` (def. 10) | `top_games(limit=n)` | `=== Top {n} jeux ===` |
| `trending` | `[n]` (def. 10) | `trending_games(limit=n)` | `=== {n} jeux en hausse ===` |
| `new` | `[n]` (def. 10) | `new_games(limit=n)` | `=== {n} nouveaux jeux ===` |
| `search` | `<mot-clé>` (joined argv) | `search_games(q)` | `=== Recherche : '{q}' ===` |
| `game` | `<game_id>` | `game_details(id)` | `=== Jeu {id} ===` |
| `visits` | `<game_id> [days]` | `game_visits(id, days)` | `=== Visites jeu {id} ===` |
| `likes` | `<game_id> [days]` | `game_likes(id, days)` | `=== Likes jeu {id} ===` |
| `playtime` | `<game_id> [days]` | `game_playtime(id, days)` | `=== Temps de jeu {id} ===` |
| `genres` | — | `explore_genres()` | `=== Genres ===` |
| `groups` | — | `explore_groups()` | `=== Groupes ===` |
| `user` | `<username>` | `user_profile(name)` | `=== Utilisateur {name} ===` |
| `changelog` | `<game_id> [days]` | `game_changelog(id, days)` | `=== Changelog jeu {id} ===` *(optional extra)* |

12 required + 1 optional = inside the 8–12 target once the optional is excluded.

Usage block text (adapt to the real command list):

```
Usage : python romonitorstats.py <commande> [args]

Commandes disponibles :
  stats                Statistiques globales de la plateforme
  top [n]              Top N jeux par critère de tri
  trending [n]         Jeux qui montent le plus vite
  new [n]              Nouveaux jeux
  search <mot-clé>     Rechercher un jeu
  game <game_id>       Détails d'un jeu
  visits <game_id>     Historique des visites
  likes <game_id>      Historique des likes
  playtime <game_id>   Historique du temps de jeu
  genres               Genres
  groups               Groupes Roblox
  user <username>      Profil d'un joueur

Exemples :
  python romonitorstats.py stats
  python romonitorstats.py top 20
  python romonitorstats.py search adopt me
  python romonitorstats.py game 7018190066

Aucune authentification n'est requise : l'API est entièrement publique.
```

#### Quirk checks the worker MUST run before trusting a field

1. **`sort` ↔ `fields` coupling.** If the endpoint accepts both `sort` and `fields`, a sort key that is not in `fields` is silently ignored (rotrends: `sort=-rank_change_day` needs `rank_change_day` in `fields`). **Check:** request `sort=X` with and without `fields` and compare the order of the first row. If the order is identical → the sort is not applied. Only ship `top_games`/`trending_games` after this check passes.
2. **Pagination naming.** `page`/`page_size` vs `offset`/`limit`. **Check:** request page 1 and page 2 and confirm the ids differ. If page 2 == page 1 → the parameter name is wrong (silently returns page 1 twice, exit code 0).
3. **Time-range parameters.** `start`/`end` (ISO) vs `days`/`period` vs `range`. **Check:** compare the first and last timestamp of the returned series to the requested window. If the span is wrong (e.g. always 30 days), the parameter was ignored.
4. **Enum route segments.** If a path segment is an enum (`/api/explore/games/{group}`, chart `?tab=visits|likes|playtime`), a wrong value usually returns **200 with an empty list**, not a 404. **Check:** every enum value used is copied verbatim from the research file; add a whitelist constant (e.g. `GAME_SORTS = (...)`) and validate before the request.
5. **Unknown/renamed fields are silently dropped.** Asking for a field the API does not know → the key is absent → `.get()` returns `None` → the CLI prints `null` and looks like "no data". **Check:** after one live call, assert that the expected key set is a subset of the returned keys (`assert "game_name" in row`), and that at least one numeric field is non-`None`.
6. **Accepted-but-always-null fields.** Some metrics only exist for games above a size/genre threshold (rotrends: `earning_rank`, `like_ratio` are `null` for most games). **Check:** compute `sum(1 for r in rows if r.get(FIELD) is not None)` — if it is 0, either drop that field from the `fields` list or document it as null. Never build a "top by FIELD" on a field that is null everywhere (the order is then arbitrary).
7. **`game_id` vs `place_id`.** Roblox universe ids and place ids are different numbers and some endpoints accept only one. **Check:** the id echoed back in the response equals the id you sent, and `place_id` (if present) is not `null` for the row you expect.
8. **POST body vs query string.** If any POST endpoint exists: send the payload in the query string with `body={}` first; if it 500s, retry with the payload in the JSON body. Record which one works in the docstring.
9. **Timezone.** Confirm whether timestamps come back UTC or local; `_days_ago_iso()` emits UTC `...Z`.

### 2.2 `rolimons.py`

**Path:** `C:\Users\Zenith\Tools\roblox-scripting\rolimons.py`

#### Header / constant substitutions

| Placeholder | Value | Note |
|---|---|---|
| `{SITE_NAME}` | `rolimons` | also the `.research` filename |
| `{BASE_URL}` | `https://www.rolimons.com` | **`www.` is part of the host** — `https://rolimons.com` redirects and may lose the JSON content-type; **no trailing slash** |
| `{SITE_ORIGIN}` | `https://www.rolimons.com` | the site's own domain |
| `{SITE_REFERER}` | `https://www.rolimons.com/` | for item endpoints the referer is often the item page (`https://www.rolimons.com/item/{id}`) — set it per-call with `headers={**BASE_HEADERS, "referer": ...}` if the research file says so |
| `{SAME_OR_CROSS_SITE}` | `same-origin` when the API is `/api/...` on `www.rolimons.com`; `cross-site` if it is on another host | confirm from the research file |
| `accept` | `application/json, text/plain, */*` — **add `text/html`** if any endpoint/profile returns HTML | rolimons serves both |
| `user-agent` | **omit** — `impersonate="chrome"` handles it | rolimons is behind Cloudflare; a hand-written UA is the fastest way to get a "Just a moment…" challenge |
| `{AUTH_NOTE}` | `Aucune authentification n'est requise : les endpoints consultés sont publics.` | keep the same wording in the module docstring and the usage block |

**Cloudflare note:** rolimons is Cloudflare-protected. If a call returns a 403 with a challenge page, retry once with `impersonate="chrome"` + a `sec-fetch-site` matching the real page, and lower the request rate. Do not add cookie/auth handling — out of scope per PLAN.md.

#### Functions to expose

Endpoint column: **← CONFIRM from `.research/rolimons.md`**.

| # | Function | One-line purpose | Endpoint (candidate) |
|---|---|---|---|
| 1 | `item_search(query: str, limit: int = 20) -> list[dict]` | Search items by name (UGC objects) | `GET /api/search/items?q=` or `GET /api/item/search` |
| 2 | `item_details(item_id: int) -> dict` | One item: name, creator, value, rarity, limits | `GET /api/item/{item_id}` |
| 3 | `item_value(item_id: int) -> dict` | Estimated value / rarity / trade value of one item | `GET /api/item/{item_id}/value` or the value block of #2 |
| 4 | `item_history(item_id: int, days: int = 30) -> list[dict]` | Value history of a limited item | `GET /api/item/{item_id}/history` |
| 5 | `top_limiteds(sort: str = "-value", limit: int = 20) -> list[dict]` | Most valuable limiteds | `GET /api/limited/top` or `GET /api/explore/limiteds` |
| 6 | `value_rates() -> dict` | Rarity/fair-value rates table | `GET /api/rates` |
| 7 | `user_profile(username: str) -> dict` | Public profile: robux, value, rank | `GET /api/user/{username}` |
| 8 | `user_inventory(username: str, limit: int = 50) -> list[dict]` | A user's items | `GET /api/user/{username}/inventory` |
| 9 | `search_users(query: str, limit: int = 20) -> list[dict]` | Search players by name | `GET /api/usersearch?q=` |
| 10 | `trade_values(limit: int = 20) -> list[dict]` | Items with an active trade offer | `GET /api/trade` or `GET /api/trades` |
| 11 | `new_items(limit: int = 20) -> list[dict]` | Recently added catalogue items | `GET /api/explore/new` |
| 12 | `categories() -> list[dict]` | Catalogue categories/brands | `GET /api/categories` |

Minimum bar: **≥ 6 public functions**, **≥ 8 CLI commands** verified live. **Keep** the function names.

#### CLI command map

| Command | Arg | Function | Header line |
|---|---|---|---|
| `search` | `<mot-clé>` (joined argv) | `item_search(q)` | `=== Recherche objet : '{q}' ===` |
| `item` | `<item_id>` | `item_details(id)` | `=== Objet {id} ===` |
| `value` | `<item_id>` | `item_value(id)` | `=== Valeur objet {id} ===` |
| `history` | `<item_id> [days]` | `item_history(id, days)` | `=== Historique valeur {id} ===` |
| `limiteds` | `[n]` (def. 20) | `top_limiteds(limit=n)` | `=== Top {n} limiteds ===` |
| `rates` | — | `value_rates()` | `=== Barèmes de valeur ===` |
| `user` | `<username>` | `user_profile(name)` | `=== Utilisateur {name} ===` |
| `inventory` | `<username> [n]` | `user_inventory(name, limit=n)` | `=== Inventaire de {name} ===` |
| `usersearch` | `<mot-clé>` | `search_users(q)` | `=== Utilisateurs : '{q}' ===` |
| `trades` | `[n]` | `trade_values(limit=n)` | `=== {n} objets en échange ===` |
| `new` | `[n]` | `new_items(limit=n)` | `=== {n} nouveaux objets ===` |
| `categories` | — | `categories()` | `=== Catégories ===` |

Usage block:

```
Usage : python rolimons.py <commande> [args]

Commandes disponibles :
  search <mot-clé>     Rechercher un objet
  item <item_id>       Détails d'un objet
  value <item_id>      Valeur estimée d'un objet
  history <item_id>    Historique de valeur
  limiteds [n]         Top N limiteds
  rates                Barèmes de valeur / rareté
  user <username>      Profil d'un joueur
  inventory <username> Inventaire d'un joueur
  usersearch <mot-clé> Rechercher un joueur
  trades [n]           Objets proposés en échange
  new [n]              Nouveaux objets
  categories           Catégories du catalogue

Exemples :
  python rolimons.py search limited sword
  python rolimons.py item 10000000
  python rolimons.py user builderman

Aucune authentification n'est requise : les endpoints consultés sont publics.
```

#### Quirk checks the worker MUST run before trusting a field

1. **Item id vs. "unique item id" vs. asset id.** Roblox items have several identifiers (item id, asset id, limited/unique id). Some rolimons endpoints expect one specific one. **Check:** take an id from the site's own item page, send it, and assert the returned name matches the page title. If it does not, you are querying a different item family.
2. **Item type gating.** Only *limited* items have a value/fair-value; normal items return `null` or 0. **Check:** call `item_value` on a known limited and on a known non-limited. Document the null case — do **not** print `0`.
3. **Name casing / encoding.** Item names contain emoji, apostrophes and non-ASCII. **Check:** the UTF-8 guard is present *and* `ensure_ascii=False` is used in `pp()` — otherwise the console dies on `print()`. Test with a name known to carry an emoji.
4. **Search endpoint shape.** RoLimons search may be `?q=`, `?query=`, `?search=`, or a path segment. **Check:** the result count for a very common word (e.g. "hat") is > 0 and the result for a nonsense string is 0 — if a nonsense string returns everything, the parameter name is wrong.
5. **Search needs URL encoding.** Names with spaces/&/é must go through `params=` (curl_cffi encodes them). Never build the query string by hand. **Check:** `search "limited sword"` returns a non-empty list that differs from `search "sword"`.
6. **Pagination naming** (`page`/`page_size` vs `offset`/`limit`) — same check as §2.1 #2: page 2 must differ from page 1.
7. **Sort/filter enums.** Sort keys for limiteds (value / percent change / rarity) are an enum; an invalid key returns 200 with an arbitrary or empty order. **Check:** `sort=-value` vs `sort=-percent_change` yield two *different* orders; otherwise the sort is ignored.
8. **User endpoints may return HTML.** If a profile endpoint returns HTML (content-type `text/html`), do not `json.loads` it — either find the JSON variant (`/api/...`) or drop the function. **Check:** `resp.headers["content-type"]` starts with `application/json` before trusting `resp.json()`.
9. **Cloudflare challenge ≠ API error.** A 403 with `Just a moment` in the body is a challenge, not a 404. **Check:** the `detail` field of an error dict contains "Just a moment" → back off and re-run with a fresh `impersonate` profile; do not ship a function that returns challenges.
10. **Values are volatile.** Item values change daily. **Check:** the timestamp/date field returned alongside a value is present and recent — a value without a timestamp is stale cached data.

---

## 3. Endpoint discovery fallback (only if the research file is incomplete)

Do **not** guess endpoints. Probe them once, record the HTTP status + content type, and pin the confirmed ones. Probe snippet (drop it in a scratch file, not in the shipped module):

```python
# scratch/probe.py — à lancer puis à supprimer
import json
from curl_cffi import requests

BASE = "https://romonitorstats.com"   # ou https://www.rolimons.com
HEADERS = {
    "accept": "application/json, text/plain, */*",
    "origin": "https://romonitorstats.com",
    "referer": "https://romonitorstats.com/",
    "sec-fetch-site": "same-origin",
}

CANDIDATES = [
    "/api/explore/games?limit=3",
    "/api/explore/genres",
    "/api/explore/groups",
    "/api/game/7018190066",
    "/api/game/7018190066/visits",
    "/api/game/7018190066/likes",
    "/api/game/7018190066/playtime",
    "/api/game/7018190066/changelog",
    "/api/platform/stats",
    "/api/user/builderman",
]

for path in CANDIDATES:
    try:
        r = requests.get(BASE + path, headers=HEADERS, impersonate="chrome", timeout=20)
        ct = r.headers.get("content-type", "?")
        preview = r.text[:120].replace("\n", " ")
        print(f"{r.status_code:>3} {ct:<28} {path}\n     {preview}")
    except Exception as e:
        print(f"ERR {path} {e}")
```

(The candidate list for rolimons: `/api/search/items?q=hat`, `/api/item/search?q=hat`, `/api/item/10000000`, `/api/item/10000000/history`, `/api/limited/top`, `/api/rates`, `/api/usersearch?q=builder`, `/api/user/builderman`, `/api/user/builderman/inventory`, `/api/trade`, `/api/explore/new`, `/api/categories`.)

**Acceptance rule for a probed endpoint:** HTTP 200 **and** `content-type` starts with `application/json` **and** the body is not `[]`/`{}`/`null`. Anything else is rejected and the function is dropped from the module.

---

## 4. Verification checklist

Run from `C:\Users\Zenith\Tools\roblox-scripting`. PowerShell. `py` = Python 3.14 with `curl_cffi` 0.15.0 (confirmed present).

### 4.0 Environment prep (once per shell)

```powershell
cd C:\Users\Zenith\Tools\roblox-scripting
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

### 4.1 Syntax / import check

```powershell
py -m py_compile .\romonitorstats.py
py -c "import romonitorstats as m; print(m.BASE_URL); print(sorted(n for n in dir(m) if not n.startswith('_')))"
```

Expected: prints the base URL and the public function names — **no traceback**.

Forbidden-import check (the vestigial `base64` must be gone):

```powershell
py -c "import ast; t=ast.parse(open('romonitorstats.py',encoding='utf-8').read()); print(sorted({a.name.split('.')[0] for n in ast.walk(t) if isinstance(n,ast.Import) for a in n.names} | {n.module.split('.')[0] for n in ast.walk(t) if isinstance(n,ast.ImportFrom) and n.module}))"
```

Expected import set: `curl_cffi, datetime, json, sys` — `base64` **must not** appear.

### 4.2 Usage block + unknown command

```powershell
py .\romonitorstats.py
py .\romonitorstats.py __bogus__
```

Expected: the usage block listing every command, exit code 0, no traceback.

```powershell
$LASTEXITCODE
```

### 4.3 Every command, exit-code + payload check

```powershell
$cmds = @('stats','top 5','trending 5','new 5','search adopt me','game 7018190066','visits 7018190066','likes 7018190066','playtime 7018190066','genres','groups','user builderman')
foreach ($c in $cmds) {
    $parts = $c -split '\s+'
    $out = & py .\romonitorstats.py @parts 2>&1
    $code = $LASTEXITCODE
    $text = ($out | Out-String)
    $status = if ($code -eq 0 -and $text.Length -gt 40 -and $text -notmatch 'Traceback' -and $text -notmatch '"error"') { 'OK' } else { 'FAIL' }
    "{0,-28} exit={1} len={2,-7} {3}" -f $c, $code, $text.Length, $status
}
```

Every line must read `OK`. A `FAIL` with `exit=0` means the command silently returned an empty/error payload (see pitfalls §5 P5/P6).

### 4.4 JSON validity

```powershell
py .\romonitorstats.py top 5 | Out-File -Encoding utf8 .\_top.json
(Get-Content .\_top.json -Raw | ConvertFrom-Json).Count
```

Expected: a positive integer (the number of returned rows).

### 4.5 Error path (must be non-zero, no traceback)

```powershell
py .\romonitorstats.py game 1
$LASTEXITCODE
```

Expected: `{"error": "…"}` on stdout, exit code **1**, **no** traceback.

### 4.6 "Does it return real data" spot-check

```powershell
py -c "import romonitorstats as m, json; rows = m.top_games(limit=5); print(json.dumps(rows[:2], indent=2, ensure_ascii=False)[:1200])"
```

Then open the site in a browser and confirm the **#1 game name and its player/visit count match the live page**. One manual comparison is enough; note the date in the PR/commit message.

The same four checks (4.1–4.6) are run for `rolimons.py`, with its own command list:

```powershell
$cmds = @('search limited sword','item 10000000','value 10000000','history 10000000','limiteds 10','rates','user builderman','inventory builderman','usersearch builder','trades 10','new 10','categories')
foreach ($c in $cmds) {
    $parts = $c -split '\s+'
    $out = & py .\rolimons.py @parts 2>&1
    $code = $LASTEXITCODE
    $text = ($out | Out-String)
    $status = if ($code -eq 0 -and $text.Length -gt 40 -and $text -notmatch 'Traceback' -and $text -notmatch '"error"') { 'OK' } else { 'FAIL' }
    "{0,-28} exit={1} len={2,-7} {3}" -f $c, $code, $text.Length, $status
}
```

### 4.7 Definition of done (per file)

- [ ] Skeleton copied verbatim, all placeholders substituted, no `{...}` left in the file
- [ ] No `import base64`; imports limited to `json`, `sys`, `datetime`, `curl_cffi`
- [ ] UTF-8 stdout/stderr guard at the top of the file, before any `print`
- [ ] `Origin`/`Referer` point at the site's **own** domain
- [ ] ≥ 6 public functions, each with a French docstring naming its endpoint
- [ ] ≥ 8 CLI commands, all verified live with exit code 0 and non-empty JSON
- [ ] Every public function calls `_check(...)` → errors raise `ApiError` → CLI prints `{"error": …}` and exits 1
- [ ] `search`-style commands join `sys.argv[2:]` (multi-word queries work)
- [ ] `rotrend.py`, `PLAN.md`, `.research/` untouched

---

## 5. Pitfalls

Read `rotrend.py` line by line before writing. These are the traps that produced a broken script the last time.

| # | Pitfall | Symptom | Rule |
|---|---|---|---|
| **P1** | **cp1252 console + emoji** | `UnicodeEncodeError` crash on the first game/item whose name contains an emoji — `print()` in a cp1252 console cannot encode it | The UTF-8 guard must be **the first thing** in the file, covering `stdout` **and** `stderr`. `pp()` uses `ensure_ascii=False` → emoji really do reach the console → the guard is load-bearing, not decorative |
| **P2** | **`sort` must be present in `fields`** | the endpoint returns 200 with rows in the *default* order; the sort is silently ignored | If the endpoint has both params, always pass the sort key inside `fields`. Test: same result with/without `sort` ⇒ not applied |
| **P3** | **`rank_change_day`-style sorts need the field** | a specific sort silently degrades to a default sort | Same rule as P2, per sort key. Ship a whitelist of valid `(sort, fields)` pairs |
| **P4** | **POST: query string vs JSON body** | rotrends `/games/platform_stats` returns **500** if `start_datetime`/`end_datetime` are in the body | Always try `params=` + `body={}` first; only fall back to a JSON body if the query string fails. Document which one works |
| **P5** | **Non-200 returns an error dict, not an exception** | the CLI prints `{}` and exits **0** — a 403/404/429 looks like a successful empty result | Every public function wraps the call in `_check(...)`; the CLI catches `ApiError` and exits 1 |
| **P6** | **Decode failures were swallowed** | `{"raw": "<html>Just a moment…"}` with exit 0 — a Cloudflare challenge or an HTML error page disguised as data | The base64 fallback is removed; a non-JSON body returns `{"error": "decode", "detail": …}` and therefore raises through `_check` |
| **P7** | **Unknown fields are silently dropped** | you request `rank_change_day`, it is absent, `.get()` → `None`, the CLI prints `null` and looks like "no data" | After one live call, assert the expected keys are present in a returned row and that at least one numeric value is non-`None` |
| **P8** | **Accepted-but-always-null fields** | `earning_rank` / `like_ratio` are `null` for most games → "top by earnings" returns an arbitrary order | Count non-null values before shipping a ranking on that field; document the null case, never coerce `None` to `0` |
| **P9** | **Enum route segments** | `/explore/games/{group}` with `group ∈ {all, TopTrending, UpAndComing}` is **case-sensitive**; a wrong value returns 200 + empty list (not 404) | Validate against a whitelist constant before the request |
| **P10** | **`place_id` / absent optional keys** | `data["place_id"]` raises `KeyError` because the key was never returned | Always `.get()` — never `[...]` — on API payload fields |
| **P11** | **Pagination naming mismatch** | page 2 returns page 1 again (silently) | Verify page 1 vs page 2 differ before shipping pagination params |
| **P12** | **`sys.argv[2]` only takes one token** | `search dead rails` searches only `"dead"` | Free-text commands use `" ".join(sys.argv[2:])` (`_text_arg()`) |
| **P13** | **`int(sys.argv[2])` raises `ValueError`** | traceback on `python script.py top abc` | Use `_int_arg(default)` |
| **P14** | **`f"{value:,}"` on `None`** | `TypeError: unsupported format string` | Guard every formatted number: `if x is not None else "n/d"` |
| **P15** | **Unwrapped `data.get("data", …)` on a `None` payload** | `{"data": null}` → `None.get(...)` → `AttributeError` | Use `_data(payload) or {}` / `or []` |
| **P16** | **Hand-written `user-agent` + `impersonate="chrome"`** | curl_cffi sets its own UA and sec-ch-ua; a mismatching manual UA is a Cloudflare tripwire | Do **not** send `user-agent`; let `impersonate="chrome"` handle it |
| **P17** | **Wrong `sec-fetch-site`** | `cross-site` for a same-origin API is a fingerprint inconsistency → challenge page | `same-origin` when the API is `/api/...` on the same host; `cross-site` only for another host |
| **P18** | **`BASE_URL` trailing slash + path leading slash** | `https://host//api/...` → 404 on some routers | `BASE_URL` without trailing slash, paths always with a leading `/` |
| **P19** | **Wrong host (`rolimons.com` vs `www.rolimons.com`)** | redirect drops the JSON content-type, or the JSON endpoint 404s | Pin `https://www.rolimons.com` (with `www.`) |
| **P20** | **`content-type: application/json` on a form-encoded POST** | the server rejects the body | Match the content type to the endpoint; `application/json` is right for JSON APIs only |
| **P21** | **`accept` without `text/html`** | HTML-returning endpoints fail to render/parse | Add `text/html` when the research file shows an HTML endpoint |
| **P22** | **Cloudflare rate limit (429)** during the verification loop | every command after the first returns `{"error": 429}` → silent empties | Sleep ~1 s between commands in the loop; treat a 429 as a failure, not as "no data" |
| **P23** | **PowerShell mangles UTF-8 on stdout** | `py script.py \| ConvertFrom-Json` fails to parse because the console decodes with the OEM code page | `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8` first, or redirect to a file with `Out-File -Encoding utf8` |
| **P24** | **Hardcoded default id/name copied from rotrend** | `7018190066` / `"brookhaven"` are rotrends-specific; the target site may not index them → empty output | Pick a default the **target** site indexes, verify it live, or require the argument |
| **P25** | **Timestamp format mismatch** | `_days_ago_iso()` emits `2026-10-21T19:32:05.123Z`; an endpoint expecting `YYYY-MM-DD` silently ignores the range | Provide `_today_iso()` for date-only endpoints; verify the returned series span matches the request |
| **P26** | **Accepting `[]` / `{}` / `null` as a "confirmed endpoint"** | a wrong URL that returns an empty JSON array gets pinned as the implementation | §3 acceptance rule: 200 **and** JSON content-type **and** non-empty payload |
| **P27** | **`success`/`ok`/`status` envelope variants** | `{"status":"error"}` is not detected by the rotrends-only `_unwrap` | The blueprint's `_unwrap` handles `success is False`, `ok is False` and `status ∈ {error, failed, failure}` |
| **P28** | **`CLAUDE.md` / `README` claims without a live run** | the README says "12 commands" while 3 of them are broken | Never claim a command works before running it; the coordinator's §4.3 loop is the gate |

---

## 6. Definition of done (global)

| Item | Where |
|---|---|
| `romonitorstats.py` exists, self-contained, ≥ 6 functions, ≥ 8 commands | B1 |
| `rolimons.py` exists, self-contained, ≥ 6 functions, ≥ 8 commands | B2 |
| Both import cleanly, no tracebacks, every command exits 0 with non-empty JSON | §4.1–4.4 |
| Error path exits 1 with a JSON `{"error": …}` | §4.5 |
| One spot-check value matches the live site | §4.6 |
| `rotrend.py`, `.swarm/PLAN.md`, `.research/*` unmodified | — |
| `README.md` + `verify_clients.py` (bead B3) | coordinator, after B1+B2 |
