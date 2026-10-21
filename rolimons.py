"""
rolimons.py — Client Python pour l'API Rolimons (api.rolimons.com)

Données publiques en temps réel, format JSON propre.

Aucune authentification n'est requise : les endpoints consultés sont publics.

Trois hôtes sont utilisés :
  - https://api.rolimons.com        : l'API JSON (chemins /{namespace}/v{N}/{action})
  - https://thumbnails.rolimons.com : les avatars de joueurs (avatar / avatarbust)
  - https://www.rolimons.com        : les pages HTML qui embarquent du JSON inline

Points d'attention de l'API (voir .research/rolimons.md) :
  - il n'existe AUCUN namespace /api/ sur www.rolimons.com : tout y est du HTML
  - items/v3/itemdetails renvoie TOUT le catalogue (2415 assets + 160 bundles) et
    ignore silencieusement ?id= / ?ids= / ?gameid= / ?limit= : le filtrage se fait
    donc côté client
  - les objets sont des tableaux de 9 éléments (26 sur /catalog) : ils sont
    convertis en dictionnaires à clés nommées
  - les pages HTML servent leur JSON dans des variables JS inline
    (var item_details_data = {...}) : extraction par scan équilibré des accolades
  - limites de débit par endpoint (headers X-RateLimit-*) : groups/v1/groupsearch
    = 20 req / 60 s (la plus stricte), playersearch 1100, playerassets 1600,
    hôte HTML 900 ; un 429 peut dégénérer en blocage Cloudflare 1015 (~90 s)
"""

import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from curl_cffi import requests

# La console Windows est souvent en cp1252 : les noms d'objets contiennent des emoji
# qui font planter print(). On force l'UTF-8 avec remplacement.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

API_URL = "https://api.rolimons.com"
THUMBS_URL = "https://thumbnails.rolimons.com"
SITE_URL = "https://www.rolimons.com"

# ─── Headers de base ──────────────────────────────────────────────────────────
# L'API est sur un sous-domaine de rolimons.com : sec-fetch-site = cross-site.
BASE_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "content-type": "application/json",
    "origin": SITE_URL,
    "referer": SITE_URL + "/",
    "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "cross-site",
}

# Les pages HTML de www.rolimons.com doivent ressembler à une navigation réelle,
# sinon Cloudflare renvoie un interstitiel "Just a moment..." (HTTP 403).
HTML_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "accept-language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "upgrade-insecure-requests": "1",
    "referer": SITE_URL + "/",
}

# Cache HTTP local (TTL 60 s) : les endpoints statiques sont déjà mis en cache par
# Cloudflare (`cache-control: public, max-age=60`), inutile de les redemander.
_CACHE_TTL = 60.0
_CACHE = {}

# Intervalle minimal entre deux appels d'un même endpoint de recherche.
# groupsearch = 20 req / 60 s et playersearch ~ 1100 req / 31 h : on espace.
_SEARCH_MIN_INTERVAL = 3.5
_LAST_CALL = {}

# Libellés des codes de demande et de tendance (research §2.1).
DEMAND_LABELS = {
    -1: "Unassigned", 0: "Terrible", 1: "Poor", 2: "Fair", 3: "Good", 4: "Amazing",
}
TREND_LABELS = {
    -1: "Unassigned", 0: "Lowering", 1: "Unstable", 2: "Stable", 3: "Raising", 4: "Fluctuating",
}

# Tableau de 9 éléments de items/v3/itemdetails (research §2.1).
ITEM_FIELDS = (
    "name", "acronym", "rap", "value", "default_value",
    "demand", "trend", "projected", "rare",
)

# Tableau de 26 éléments de /catalog (research §2.2).
CATALOG_FIELDS = (
    "name", "type", "original_price", "created", "first_timestamp", "best_price",
    "favorited", "num_sellers", "rap", "owners", "bc_owners", "copies",
    "deleted_copies", "bc_copies", "hoarded_copies", "acronym", "value",
    "demand", "trend", "projected", "hyped", "rare", "default_value",
    "thumbnail_url_sm", "item_type_code", "id",
)

# Tris acceptés par top_limiteds (le catalogue n'expose que ces champs).
ITEM_SORTS = ("-value", "value", "-rap", "rap", "name", "-name")


class ApiError(RuntimeError):
    """Erreur renvoyée par l'API Rolimons (enveloppe success/code/message)."""


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _unwrap(data):
    """
    Lève une ApiError si l'enveloppe signale une erreur.
    Rolimons utilise `success: false` + `code` + `message` (research §5.3).
    Le heuristique `status in (error, failed, failure)` du blueprint est VOLONTAIREMENT
    absente : un payload réel peut porter un champ `status` qui veut dire autre chose.
    """
    if isinstance(data, dict):
        if data.get("success") is False:
            msg = data.get("message") or ""
            raise ApiError(msg or json.dumps(data, ensure_ascii=False)[:300])
        if data.get("ok") is False:
            raise ApiError(data.get("message") or json.dumps(data, ensure_ascii=False)[:300])
    return data


def _check(data):
    """
    Lève une ApiError si _get/_post a renvoyé une erreur HTTP ou un corps non-JSON.
    Le sentinelle `__http_error__` est utilisé (et non la clé "error") pour ne pas
    confondre un vrai champ `error` d'une réponse légitime.
    """
    if isinstance(data, dict) and "__http_error__" in data:
        raise ApiError(
            f"erreur HTTP/format : {data.get('__http_error__')} — {str(data.get('detail'))[:200]}"
        )
    return data


def _error_detail(resp) -> str:
    """Message d'erreur lisible à partir d'un corps JSON ou texte."""
    if "1015" in resp.text:
        return "blocage Cloudflare 1015 (trop de requêtes) — réessaie dans ~90 s"
    try:
        body = resp.json()
    except Exception:
        return " ".join(resp.text[:200].split())
    if isinstance(body, dict):
        msg = body.get("message") or body.get("title")
        if msg:
            code = body.get("code")
            return f"{msg} (code={code})" if code is not None else str(msg)
    return " ".join(str(body)[:200].split())


def _get(url: str, params: dict = None, headers: dict = None, want_json: bool = True,
        retried: bool = False) -> dict:
    """GET HTTP (30 s de timeout) ; retourne le JSON décodé ou un dict d'erreur."""
    resp = requests.get(url, params=params, headers=headers or BASE_HEADERS,
                        impersonate="chrome", timeout=30)
    if resp.status_code == 429:
        # Limite applicative (code 6) ou blocage Cloudflare : on retente une fois
        # si le Retry-After est court, sinon on remonte une erreur explicite.
        if "1015" in resp.text:
            return {"__http_error__": 429,
                    "detail": "blocage Cloudflare 1015 (trop de requêtes) — réessaie dans ~90 s"}
        wait = resp.headers.get("Retry-After")
        try:
            wait = int(wait) if wait else 0
        except ValueError:
            wait = 0
        if not retried and 0 < wait <= 30:
            time.sleep(wait + 0.5)
            return _get(url, params=params, headers=headers, want_json=want_json, retried=True)
        return {"__http_error__": 429, "detail": _error_detail(resp)}
    if resp.status_code != 200:
        return {"__http_error__": resp.status_code, "detail": _error_detail(resp)}
    if not want_json:
        return {"__html__": resp.text}
    try:
        return _unwrap(resp.json())
    except ApiError:
        raise
    except Exception:
        return {"__http_error__": "decode", "detail": " ".join(resp.text[:200].split())}


def _post(url: str, body: dict = None, params: dict = None, headers: dict = None) -> dict:
    """POST HTTP (30 s de timeout) ; `params` part en query string, `body` en JSON."""
    resp = requests.post(url, json=body if body is not None else {}, params=params,
                          headers=headers or BASE_HEADERS, impersonate="chrome",
                          timeout=30)
    if resp.status_code != 200:
        return {"__http_error__": resp.status_code, "detail": _error_detail(resp)}
    try:
        return _unwrap(resp.json())
    except ApiError:
        raise
    except Exception:
        return {"__http_error__": "decode", "detail": " ".join(resp.text[:200].split())}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _days_ago_iso(days: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _today_iso() -> str:
    """Date du jour au format YYYY-MM-DD (certains endpoints n'acceptent pas l'horodatage complet)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _unix_to_iso(ts):
    """Timestamp unix → chaîne ISO-8601 UTC (None si la valeur n'est pas exploitable)."""
    if not isinstance(ts, (int, float)) or isinstance(ts, bool) or ts <= 0:
        return None
    try:
        return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return None


def _cached(key: str, loader, ttl: float = _CACHE_TTL):
    """Renvoie la valeur cachée (TTL 60 s par défaut) ou la recalcule via `loader`."""
    now = time.monotonic()
    hit = _CACHE.get(key)
    if hit is not None and hit[1] > now:
        return hit[0]
    value = loader()
    _CACHE[key] = (value, now + ttl)
    return value


def _pace(key: str, min_interval: float = _SEARCH_MIN_INTERVAL) -> None:
    """Espace deux appels d'un endpoint de recherche (groupsearch : 20 req / 60 s)."""
    now = time.monotonic()
    last = _LAST_CALL.get(key)
    if last is not None:
        wait = min_interval - (now - last)
        if wait > 0:
            time.sleep(wait)
    _LAST_CALL[key] = time.monotonic()


def _extract_json_var(html: str, name: str):
    """
    Extrait le JSON d'une variable JS inline `var <name> = <json>;` (research §3.3).
    Scan équilibré des accolades/crochets : indispensable, un regex gourmand
    sur-capture sur /itemtable et /gametable.
    """
    if not html:
        return None
    m = re.search(r"var\s+" + re.escape(name) + r"\s*=\s*", html)
    if not m:
        return None
    s = m.end()
    while s < len(html) and html[s].isspace():
        s += 1
    if s >= len(html):
        return None
    open_ch = html[s]
    if open_ch not in "{[":
        # Valeur scalaire (null, nombre, chaîne) : on lit jusqu'au prochain ';'
        end = html.find(";", s)
        raw = html[s:end if end > 0 else len(html)].strip()
        try:
            return json.loads(raw)
        except Exception:
            return None
    close_ch = "}" if open_ch == "{" else "]"
    depth = 0
    in_str = False
    esc = False
    for i in range(s, len(html)):
        c = html[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
            continue
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[s:i + 1])
                except Exception:
                    return None
    return None


def _extract_script_json(html: str, script_id: str):
    """Extrait le JSON d'un bloc <script id="..." type="application/json"> (page /game)."""
    if not html:
        return None
    m = re.search(
        r'<script id="' + re.escape(script_id) + r'"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


def _get_html(path: str) -> str:
    """GET d'une page www.rolimons.com et retourne le HTML brut (ou lève une ApiError)."""
    data = _check(_get(SITE_URL + path, headers=HTML_HEADERS, want_json=False))
    html = data.get("__html__")
    if not html:
        raise ApiError(f"page vide : {path}")
    return html


def _get_json(path: str, params: dict = None) -> dict:
    """GET d'un endpoint JSON de api.rolimons.com."""
    return _check(_get(API_URL + path, params=params))


def _int_id(value):
    """Normalise un identifiant (int ou chaîne) en int, ou lève une ApiError lisible."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        raise ApiError(f"identifiant invalide : {value!r}")


def _item_from_tuple(row, item_type: str, item_id) -> dict:
    """Convertit le tableau de 9 éléments de items/v3/itemdetails en dict à clés nommées."""
    row = list(row) + [None] * max(0, len(ITEM_FIELDS) - len(row))
    out = {key: row[i] for i, key in enumerate(ITEM_FIELDS)}
    out["id"] = item_id
    out["item_type"] = item_type
    out["demand_label"] = DEMAND_LABELS.get(out["demand"], "Unknown")
    out["trend_label"] = TREND_LABELS.get(out["trend"], "Unknown")
    out["value_assigned"] = isinstance(out["value"], (int, float)) and out["value"] >= 0
    return out


def _catalog_from_tuple(row) -> dict:
    """Convertit le tableau de 26 éléments de /catalog en dict à clés nommées."""
    row = list(row) + [None] * max(0, len(CATALOG_FIELDS) - len(row))
    out = {key: row[i] for i, key in enumerate(CATALOG_FIELDS)}
    code = out.get("item_type_code")
    out["item_type"] = {1: "asset", 2: "bundle"}.get(code)
    out["demand_label"] = DEMAND_LABELS.get(out["demand"], "Unknown")
    out["trend_label"] = TREND_LABELS.get(out["trend"], "Unknown")
    out["value_assigned"] = isinstance(out["value"], (int, float)) and out["value"] >= 0
    out["created_iso"] = _unix_to_iso(out.get("created"))
    return out


def _raw_catalogue() -> dict:
    """Charge (et met en cache 60 s) le catalogue brut : items/v3/itemdetails."""
    def _loader():
        return _get_json("/items/v3/itemdetails")
    return _cached("itemdetails", _loader)


def _raw_gamelist() -> dict:
    """Charge (et met en cache 60 s) la liste brute des jeux : games/v1/gamelist."""
    def _loader():
        return _get_json("/games/v1/gamelist")
    return _cached("gamelist", _loader)


def _raw_thumbs() -> dict:
    """Charge (et met en cache 60 s) les miniatures d'objets : itemthumbs/v2/thumbssm."""
    def _loader():
        return _get_json("/itemthumbs/v2/thumbssm")
    return _cached("thumbssm", _loader)


def _raw_catalog_page() -> dict:
    """Charge (et met en cache 60 s) le catalogue complet de la page /catalog."""
    def _loader():
        html = _get_html("/catalog")
        return _extract_json_var(html, "item_details") or {}
    return _cached("catalog_page", _loader)


def _item_path(item_id: int, item_type: str) -> str:
    """Chemin de la page HTML d'un objet : /item/<assetId> ou /bundle/<bundleId>."""
    return f"/bundle/{item_id}" if item_type == "bundle" else f"/item/{item_id}"


# ─── 1. Catalogue d'objets ───────────────────────────────────────────────────

def item_catalogue(include_items: bool = True) -> dict:
    """
    Catalogue complet : 2415 assets + 160 bundles, avec stats et objets nommés.
    Endpoint : GET https://api.rolimons.com/items/v3/itemdetails
    """
    data = _raw_catalogue()
    assets = data.get("assets") or {}
    bundles = data.get("bundles") or {}
    out = {
        "source": API_URL + "/items/v3/itemdetails",
        "asset_count": data.get("asset_count"),
        "bundle_count": data.get("bundle_count"),
        "item_count": data.get("item_count"),
    }
    if include_items:
        out["assets"] = {
            k: _item_from_tuple(v, "asset", _safe_int(k)) for k, v in assets.items()
        }
        out["bundles"] = {
            k: _item_from_tuple(v, "bundle", _safe_int(k)) for k, v in bundles.items()
        }
    return out


def _safe_int(value):
    """Convertit en int si possible, sinon renvoie la valeur brute."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def item_search(query: str, limit: int = 20, item_type: str = "all") -> list[dict]:
    """
    Recherche d'objets par nom (filtrage CLIENT du catalogue complet).
    Endpoint : GET https://api.rolimons.com/items/v3/itemdetails
    L'API n'a pas d'endpoint de recherche et ignore ?id= : on filtre en Python.
    """
    if item_type not in ("all", "asset", "bundle"):
        raise ApiError(f"item_type invalide : {item_type!r} (all|asset|bundle)")
    cat = item_catalogue()
    q = (query or "").strip().lower()
    tokens = [t for t in q.split() if t]
    found = []
    for kind, bucket in (("asset", cat.get("assets")), ("bundle", cat.get("bundles"))):
        if not bucket:
            continue
        if item_type not in ("all", kind):
            continue
        for item in bucket.values():
            name = (item.get("name") or "").lower()
            acronym = (item.get("acronym") or "").lower()
            # correspondance par jetons (comme la recherche du site) ou par acronyme exact
            if not tokens or all(tok in name for tok in tokens) or (q and q == acronym):
                found.append(item)
    found.sort(key=lambda it: (
        0 if it.get("value_assigned") else 1,
        -(it.get("value") if isinstance(it.get("value"), (int, float)) else 0),
        -(it.get("rap") if isinstance(it.get("rap"), (int, float)) else 0),
    ))
    return found[:max(0, limit)] if limit else found


def item_details(item_id: int, with_page: bool = True) -> dict:
    """
    Détail d'un objet (asset ou bundle) : valeur, RAP, demande, tendance + page HTML.
    Endpoints : GET https://api.rolimons.com/items/v3/itemdetails
                GET https://www.rolimons.com/item/<id> (ou /bundle/<id>)
    """
    iid = _int_id(item_id)
    cat = item_catalogue()
    assets = cat.get("assets") or {}
    bundles = cat.get("bundles") or {}
    if str(iid) in assets:
        base, kind = dict(assets[str(iid)]), "asset"
    elif str(iid) in bundles:
        base, kind = dict(bundles[str(iid)]), "bundle"
    else:
        raise ApiError(
            f"objet {iid} introuvable dans le catalogue Rolimons "
            f"({len(assets)} assets, {len(bundles)} bundles)"
        )
    base["item_type"] = kind
    if with_page:
        page = _item_page_data(iid, kind)
        for key, val in page.items():
            # on n'écrase pas une valeur connue (ex. projected=-1) par un null de la page
            if val is not None or key not in base:
                base[key] = val
    return base


def _item_page_data(item_id: int, item_type: str) -> dict:
    """Extrais item_details_data / bundle_details_data de la page HTML d'un objet."""
    html = _get_html(_item_path(item_id, item_type))
    var = "bundle_details_data" if item_type == "bundle" else "item_details_data"
    data = _extract_json_var(html, var)
    if not isinstance(data, dict):
        return {}
    out = dict(data)
    out.setdefault("name", data.get("item_name") or data.get("bundle_name"))
    out.setdefault("id", data.get("item_id") or data.get("bundle_id"))
    out["page_url"] = SITE_URL + _item_path(item_id, item_type)
    return out


def item_value(item_id: int) -> dict:
    """
    Valeur estimée, RAP, demande et tendance d'un objet.
    Endpoint : GET https://api.rolimons.com/items/v3/itemdetails
    """
    item = item_details(item_id, with_page=False)
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "item_type": item.get("item_type"),
        "value": item.get("value"),
        "value_assigned": item.get("value_assigned"),
        "default_value": item.get("default_value"),
        "rap": item.get("rap"),
        "acronym": item.get("acronym"),
        "demand": item.get("demand"),
        "demand_label": item.get("demand_label"),
        "trend": item.get("trend"),
        "trend_label": item.get("trend_label"),
        "projected": item.get("projected"),
        "rare": item.get("rare"),
    }


def item_history(item_id: int, days: int = 30) -> list[dict]:
    """
    Historique de prix (RAP, meilleur prix, favoris, vendeurs) d'un objet.
    Endpoint : GET https://www.rolimons.com/item/<id> (ou /bundle/<id>) → history_data
    """
    iid = _int_id(item_id)
    kind = _item_kind(iid)
    html = _get_html(_item_path(iid, kind))
    data = _extract_json_var(html, "history_data")
    if not isinstance(data, dict):
        return []
    stamps = data.get("timestamp") or []
    rap = data.get("rap") or []
    best = data.get("best_price") or []
    fav = data.get("favorited") or []
    sellers = data.get("num_sellers") or []
    rows = []
    for i, ts in enumerate(stamps):
        rows.append({
            "timestamp": ts,
            "timestamp_iso": _unix_to_iso(ts),
            "rap": rap[i] if i < len(rap) else None,
            "best_price": best[i] if i < len(best) else None,
            "favorited": fav[i] if i < len(fav) else None,
            "num_sellers": sellers[i] if i < len(sellers) else None,
        })
    if days and days > 0:
        cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
        rows = [r for r in rows if isinstance(r["timestamp"], (int, float)) and r["timestamp"] >= cutoff]
    return rows


def _item_kind(item_id: int) -> str:
    """Détermine si un id est un asset (1) ou un bundle (2) d'après le catalogue."""
    cat = item_catalogue()
    if str(item_id) in (cat.get("assets") or {}):
        return "asset"
    if str(item_id) in (cat.get("bundles") or {}):
        return "bundle"
    raise ApiError(f"objet {item_id} introuvable dans le catalogue Rolimons")


def item_sales(item_id: int, limit: int = 50) -> list[dict]:
    """
    Historique des ventes d'un objet (prix, RAP et valeur au moment de la vente).
    Endpoint : GET https://www.rolimons.com/itemsales/<id> → item_sales
    """
    iid = _int_id(item_id)
    kind = _item_kind(iid)
    path = f"/bundlesales/{iid}" if kind == "bundle" else f"/itemsales/{iid}"
    html = _get_html(path)
    data = _extract_json_var(html, "item_sales")
    if not isinstance(data, dict):
        return []
    stamps = data.get("timestamp_list") or []
    ids = data.get("sale_id_list") or []
    prices = data.get("sale_price_list") or []
    raps = data.get("sale_rap_list") or []
    values = data.get("sale_value_list") or []
    rows = []
    for i, ts in enumerate(stamps):
        rows.append({
            "timestamp": ts,
            "timestamp_iso": _unix_to_iso(ts),
            "sale_id": ids[i] if i < len(ids) else None,
            "price": prices[i] if i < len(prices) else None,
            "rap": raps[i] if i < len(raps) else None,
            "value": values[i] if i < len(values) else None,
        })
    return rows[:max(0, limit)] if limit else rows


def item_thumbnails(item_ids=None, limit: int = 0) -> dict:
    """
    Miniatures d'objets (URL rbxcdn 110x110).
    Endpoint : GET https://api.rolimons.com/itemthumbs/v2/thumbssm
    """
    data = _raw_thumbs()
    assets = data.get("assets") or {}
    bundles = data.get("bundles") or {}
    if item_ids is None:
        out = dict(assets)
        out.update(bundles)
    else:
        if isinstance(item_ids, (int, str)):
            item_ids = [item_ids]
        wanted = {str(i) for i in item_ids}
        out = {k: v for k, v in assets.items() if k in wanted}
        out.update({k: v for k, v in bundles.items() if k in wanted})
    if limit and limit > 0:
        out = dict(list(out.items())[:limit])
    return out


def top_limiteds(sort: str = "-value", limit: int = 20) -> list[dict]:
    """
    Objets les plus valorisés du catalogue (valeur, RAP, demande).
    Endpoint : GET https://api.rolimons.com/items/v3/itemdetails
    Le catalogue ne distingue pas les limiteds : on classe les objets dont la
    valeur est assignée (value >= 0).
    """
    if sort not in ITEM_SORTS:
        raise ApiError(f"tri invalide : {sort!r} ({'|'.join(ITEM_SORTS)})")
    cat = item_catalogue()
    rows = []
    for kind, bucket in (("asset", cat.get("assets")), ("bundle", cat.get("bundles"))):
        for item in (bucket or {}).values():
            if item.get("value_assigned"):
                rows.append(item)
    key = sort[1:] if sort.startswith("-") else sort
    reverse = sort.startswith("-")
    def _key(item):
        val = item.get(key)
        if key == "name":
            return (val or "").lower()
        if not isinstance(val, (int, float)):
            val = -1 if key == "value" else 0
        return val
    rows.sort(key=_key, reverse=reverse)
    return rows[:max(0, limit)] if limit else rows


def new_items(limit: int = 20) -> list[dict]:
    """
    Objets les plus récemment ajoutés au catalogue (tri par date de création).
    Endpoint : GET https://www.rolimons.com/catalog → item_details (26 éléments)
    """
    raw = _raw_catalog_page()
    rows = [_catalog_from_tuple(v) for v in raw.values()]
    rows.sort(key=lambda r: r.get("created") or 0, reverse=True)
    return rows[:max(0, limit)] if limit else rows


def categories() -> list[dict]:
    """
    Catégories du catalogue (type d'objet + nombre d'exemplaires).
    Endpoint : GET https://www.rolimons.com/catalog → item_details (26 éléments)
    Le nom de la catégorie est déduit de l'URL de miniature rbxcdn (Hat, Face, …).
    """
    raw = _raw_catalog_page()
    buckets = {}
    for row in raw.values():
        item = _catalog_from_tuple(row)
        key = item.get("type") or "unknown"
        entry = buckets.setdefault(key, {
            "type": key,
            "category": _category_name(item.get("thumbnail_url_sm")),
            "count": 0,
            "example": item.get("name"),
        })
        entry["count"] += 1
    out = list(buckets.values())
    out.sort(key=lambda c: -c["count"])
    return out


def _category_name(thumbnail_url) -> str:
    """Déduit le nom de la catégorie Roblox depuis l'URL de miniature (…/110/110/<Type>/…)."""
    if not isinstance(thumbnail_url, str):
        return "Unknown"
    parts = [p for p in thumbnail_url.split("/") if p]
    if "Webp" in parts:
        idx = parts.index("Webp")
        if idx >= 1:
            return parts[idx - 1]
    return "Unknown"


def value_changes(limit: int = 50) -> list[dict]:
    """
    Journal global des changements de valeur (55 938 entrées, les plus récentes d'abord).
    Endpoint : GET https://www.rolimons.com/valuechanges → value_changes
    """
    html = _get_html("/valuechanges")
    rows = _extract_json_var(html, "value_changes")
    if not isinstance(rows, list):
        return []
    out = []
    for row in rows:
        row = list(row) + [None] * max(0, 6 - len(row))
        out.append({
            "timestamp": row[0],
            "timestamp_iso": _unix_to_iso(row[0]),
            "item_id": row[1],
            "item_type": {1: "asset", 2: "bundle"}.get(row[2], row[2]),
            "changed_field": row[3],
            "old_value": row[4],
            "new_value": row[5],
        })
    out.sort(key=lambda r: r["timestamp"] if isinstance(r["timestamp"], (int, float)) else 0,
             reverse=True)
    return out[:max(0, limit)] if limit else out


def value_rates() -> dict:
    """
    Barèmes de valeur : libellés de la demande / tendance + taux de promotion (CPI).
    Endpoint : GET https://www.rolimons.com/promotionrates → latest_promotion_rates
    """
    html = _get_html("/promotionrates")
    rates = _extract_json_var(html, "latest_promotion_rates")
    history = _extract_json_var(html, "promotion_rate_history_data")
    return {
        "demand_labels": DEMAND_LABELS,
        "trend_labels": TREND_LABELS,
        "promotion_rates": rates if isinstance(rates, dict) else {},
        "promotion_history_points": history.get("num_points") if isinstance(history, dict) else None,
    }


# ─── 2. Jeux ──────────────────────────────────────────────────────────────────

def game_catalogue(include_games: bool = True) -> dict:
    """
    Catalogue des jeux : 7 822 jeux (nom, joueurs, icône).
    Endpoint : GET https://api.rolimons.com/games/v1/gamelist
    """
    data = _raw_gamelist()
    out = {
        "source": API_URL + "/games/v1/gamelist",
        "game_count": data.get("game_count"),
    }
    if include_games:
        out["games"] = [
            _game_from_tuple(v, k) for k, v in (data.get("games") or {}).items()
        ]
    return out


def top_games(limit: int = 20) -> list[dict]:
    """
    Jeux les plus joués (7 822 jeux au total).
    Endpoint : GET https://api.rolimons.com/games/v1/gamelist
    """
    data = _raw_gamelist()
    games = [_game_from_tuple(v, k) for k, v in (data.get("games") or {}).items()]
    games.sort(key=lambda g: -(g.get("players") or 0))
    return games[:max(0, limit)] if limit else games


def _game_from_tuple(row, game_id) -> dict:
    """Convertit le tableau [nom, joueurs, icône] de games/v1/gamelist en dict nommé."""
    row = list(row) + [None] * max(0, 3 - len(row))
    return {
        "game_id": _safe_int(game_id),
        "name": row[0],
        "players": row[1],
        "icon_url": row[2],
    }


def game_search(query: str, limit: int = 20) -> list[dict]:
    """
    Recherche de jeu par nom (filtrage CLIENT de la liste complète).
    Endpoint : GET https://api.rolimons.com/games/v1/gamelist
    """
    q = (query or "").strip().lower()
    data = _raw_gamelist()
    games = [_game_from_tuple(v, k) for k, v in (data.get("games") or {}).items()]
    if q:
        games = [g for g in games if q in (g.get("name") or "").lower()]
    games.sort(key=lambda g: -(g.get("players") or 0))
    return games[:max(0, limit)] if limit else games


def game_details(game_id: int, points: int = 30) -> dict:
    """
    Statistiques d'un jeu : joueurs, temps de jeu, visites, votes, favoris (série).
    Endpoint : GET https://www.rolimons.com/game/<id> → <script id="game_history_json">
    """
    gid = _int_id(game_id)
    html = _get_html(f"/game/{gid}")
    data = _extract_script_json(html, "game_history_json")
    if not isinstance(data, dict):
        raise ApiError(f"historique introuvable pour le jeu {gid}")
    stamps = data.get("timestamps") or []
    series = []
    for i in range(len(stamps)):
        series.append({
            "timestamp": stamps[i],
            "timestamp_iso": _unix_to_iso(stamps[i]),
            "players": _at(data.get("players"), i),
            "avg_playtime": _at(data.get("avg_playtime"), i),
            "visits": _at(data.get("visits"), i),
            "upvotes": _at(data.get("upvotes"), i),
            "downvotes": _at(data.get("downvotes"), i),
            "favorites": _at(data.get("favorites"), i),
        })
    tail = series[-points:] if points and points > 0 else series
    last = series[-1] if series else {}
    return {
        "game_id": gid,
        "source": SITE_URL + f"/game/{gid}",
        "num_points": data.get("num_points", len(stamps)),
        "first_timestamp": stamps[0] if stamps else None,
        "last_timestamp": stamps[-1] if stamps else None,
        "current": {
            "players": last.get("players"),
            "visits": last.get("visits"),
            "upvotes": last.get("upvotes"),
            "downvotes": last.get("downvotes"),
            "favorites": last.get("favorites"),
            "avg_playtime": last.get("avg_playtime"),
        },
        "series": tail,
    }


def _at(values, index):
    """Valeur à l'index i d'une série, ou None si la série est plus courte."""
    if not isinstance(values, list) or index >= len(values):
        return None
    return values[index]


# ─── 3. Marché ────────────────────────────────────────────────────────────────

def sale_activity(limit: int = 50) -> list[dict]:
    """
    Flux des ventes récentes (timestamp, objet, ancien RAP, nouveau RAP, id de vente).
    Endpoint : GET https://api.rolimons.com/market/v2/saleactivity
    """
    data = _get_json("/market/v2/saleactivity")
    rows = data.get("activities") or []
    out = []
    for row in rows:
        row = list(row) + [None] * max(0, 6 - len(row))
        out.append({
            "timestamp": row[0],
            "timestamp_iso": _unix_to_iso(row[0]),
            "item_id": row[1],
            "item_type": {1: "asset", 2: "bundle"}.get(row[2], row[2]),
            "old_rap": row[3],
            "rap": row[4],
            "sale_id": row[5],
        })
    return out[:max(0, limit)] if limit else out


def deal_activity(limit: int = 50) -> list[dict]:
    """
    Flux des deals récents (timestamp, type d'activité, objet, prix).
    Endpoint : GET https://api.rolimons.com/market/v2/dealactivity
    """
    data = _get_json("/market/v2/dealactivity")
    rows = data.get("activities") or []
    out = []
    for row in rows:
        row = list(row) + [None] * max(0, 5 - len(row))
        out.append({
            "timestamp": row[0],
            "timestamp_iso": _unix_to_iso(row[0]),
            "activity_type": row[1],
            "item_id": row[2],
            "item_type": {1: "asset", 2: "bundle"}.get(row[3], row[3]),
            "price": row[4],
        })
    return out[:max(0, limit)] if limit else out


def trade_values(limit: int = 20) -> list[dict]:
    """
    Annonces d'échange récentes (ce que le propriétaire veut / ce qu'il donne).
    Endpoint : GET https://api.rolimons.com/tradeads/v1/getrecentads
    """
    data = _get_json("/tradeads/v1/getrecentads")
    rows = data.get("trade_ads") or []
    out = []
    for row in rows:
        row = list(row) + [None] * max(0, 6 - len(row))
        out.append({
            "ad_id": row[0],
            "timestamp": row[1],
            "timestamp_iso": _unix_to_iso(row[1]),
            "owner_id": row[2],
            "owner_name": row[3],
            "want_items": (row[4] or {}).get("items") if isinstance(row[4], dict) else None,
            "give_items": (row[5] or {}).get("items") if isinstance(row[5], dict) else None,
            "tags": (row[5] or {}).get("tags") if isinstance(row[5], dict) else None,
        })
    return out[:max(0, limit)] if limit else out


# ─── 4. Joueurs, groupes et avatars ──────────────────────────────────────────

def search_users(query: str, limit: int = 20) -> list[dict]:
    """
    Recherche de joueurs par nom.
    Endpoint : GET https://api.rolimons.com/players/v1/playersearch?searchstring=
    """
    if not (query or "").strip():
        raise ApiError("recherche vide : le paramètre 'searchstring' est obligatoire")
    _pace("playersearch")
    data = _get_json("/players/v1/playersearch", {"searchstring": query})
    rows = data.get("players") or []
    out = []
    for row in rows:
        row = list(row) + [None] * max(0, 2 - len(row))
        out.append({"user_id": _safe_int(row[0]), "username": row[1]})
    return out[:max(0, limit)] if limit else out


def user_profile(username: str) -> dict:
    """
    Profil public d'un joueur : statut, ancienneté, premium, valeur et RAP du stock.
    Endpoints : GET https://api.rolimons.com/players/v1/playersearch?searchstring=
                GET https://api.rolimons.com/players/v1/playerassets/<userId>
    """
    uid, uname = _resolve_user(username)
    data = _get_json(f"/players/v1/playerassets/{uid}")
    assets = data.get("playerAssets") or {}
    total_rap = 0
    total_copies = 0
    for row in assets.values():
        row = list(row) + [None] * max(0, 2 - len(row))
        copies = row[0] if isinstance(row[0], (int, float)) else 0
        rap = row[1] if isinstance(row[1], (int, float)) else 0
        total_copies += copies
        total_rap += copies * rap
    badges = data.get("badges")
    return {
        "user_id": uid,
        "username": uname,
        "is_online": data.get("isOnline"),
        "presence_type": data.get("presenceType"),
        "last_online": data.get("lastOnline"),
        "last_online_iso": _unix_to_iso(data.get("lastOnline")),
        "last_location": data.get("lastLocation"),
        "premium": data.get("premium"),
        "player_terminated": data.get("playerTerminated"),
        "player_privacy_enabled": data.get("playerPrivacyEnabled"),
        "player_verified": data.get("playerVerified"),
        "chart_nominal_scan_time": data.get("chartNominalScanTime"),
        "chart_nominal_scan_time_iso": _unix_to_iso(data.get("chartNominalScanTime")),
        "holdings_count": len(assets),
        "total_copies": total_copies,
        "total_rap": total_rap,
        "badges_count": len(badges) if isinstance(badges, dict) else None,
    }


def _resolve_user(username: str):
    """Trouve l'id Roblox d'un pseudo via playersearch (correspondance exacte prioritaire)."""
    name = (username or "").strip()
    if not name:
        raise ApiError("pseudo vide : le paramètre 'searchstring' est obligatoire")
    _pace("playersearch")
    data = _get_json("/players/v1/playersearch", {"searchstring": name})
    rows = data.get("players") or []
    if not rows:
        raise ApiError(f"aucun joueur trouvé pour '{name}'")
    exact = None
    for row in rows:
        row = list(row) + [None] * max(0, 2 - len(row))
        if (row[1] or "").lower() == name.lower():
            exact = (_safe_int(row[0]), row[1])
            break
    if exact is None:
        row = list(rows[0]) + [None] * max(0, 2 - len(rows[0]))
        exact = (_safe_int(row[0]), row[1])
    return exact


def user_inventory(username: str, limit: int = 50) -> list[dict]:
    """
    Inventaire d'un joueur : objets possédés, copies, RAP et valeur estimée.
    Endpoints : GET https://api.rolimons.com/players/v1/playersearch?searchstring=
                GET https://api.rolimons.com/players/v1/playerassets/<userId>
                GET https://api.rolimons.com/items/v3/itemdetails (noms)
    """
    uid, uname = _resolve_user(username)
    data = _get_json(f"/players/v1/playerassets/{uid}")
    assets = data.get("playerAssets") or {}
    cat = item_catalogue()
    names = dict(cat.get("assets") or {})
    names.update(cat.get("bundles") or {})
    rows = []
    for item_id, row in assets.items():
        row = list(row) + [None] * max(0, 2 - len(row))
        copies = row[0] if isinstance(row[0], (int, float)) else None
        rap = row[1] if isinstance(row[1], (int, float)) else None
        meta = names.get(str(item_id)) or {}
        value = meta.get("value") if isinstance(meta.get("value"), (int, float)) else None
        rows.append({
            "item_id": _safe_int(item_id),
            "name": meta.get("name"),
            "acronym": meta.get("acronym"),
            "item_type": meta.get("item_type"),
            "copies": copies,
            "rap": rap,
            "value": value,
            "estimated_value": (copies * value) if (copies is not None and value is not None) else None,
        })
    rows.sort(key=lambda r: -(r.get("estimated_value") or r.get("rap") or 0))
    out = rows[:max(0, limit)] if limit else rows
    return {
        "user_id": uid,
        "username": uname,
        "holdings_count": len(rows),
        "total_copies": sum(r.get("copies") or 0 for r in rows),
        "total_estimated_value": sum(r.get("estimated_value") or 0 for r in rows),
        "items": out,
    }


def player_assets(user_id: int, limit: int = 50) -> list[dict]:
    """
    Détail brut des objets d'un joueur (copies + RAP par objet).
    Endpoint : GET https://api.rolimons.com/players/v1/playerassets/<userId>
    """
    uid = _int_id(user_id)
    data = _get_json(f"/players/v1/playerassets/{uid}")
    assets = data.get("playerAssets") or {}
    rows = []
    for item_id, row in assets.items():
        row = list(row) + [None] * max(0, 2 - len(row))
        rows.append({
            "item_id": _safe_int(item_id),
            "copies": row[0],
            "rap": row[1],
        })
    rows.sort(key=lambda r: -(r.get("copies") or 0))
    return rows[:max(0, limit)] if limit else rows


def search_groups(query: str, limit: int = 30) -> list[dict]:
    """
    Recherche de groupes Roblox par nom (limite stricte : 20 requêtes / 60 s).
    Endpoint : GET https://api.rolimons.com/groups/v1/groupsearch?searchstring=
    """
    if not (query or "").strip():
        raise ApiError("recherche vide : le paramètre 'searchstring' est obligatoire")
    _pace("groupsearch")
    data = _get_json("/groups/v1/groupsearch", {"searchstring": query})
    rows = data.get("groups") or []
    out = []
    for row in rows:
        row = list(row) + [None] * max(0, 7 - len(row))
        out.append({
            "group_id": _safe_int(row[0]),
            "name": row[1],
            "created": row[2],
            "created_iso": _unix_to_iso(row[2]),
            "locked": row[3],
            "flag": row[4],
            "member_count": row[5],
            "icon_url": row[6],
        })
    return out[:max(0, limit)] if limit else out


def avatar_thumbnails(user_ids, size: str = "150x150", bust: bool = False) -> dict:
    """
    Miniatures d'avatars de joueurs (150x150 ou 420x420, version buste en option).
    Endpoint : GET https://thumbnails.rolimons.com/avatar (ou /avatarbust)
    """
    if isinstance(user_ids, (int, str)):
        user_ids = [user_ids]
    ids = [str(u).strip() for u in (user_ids or []) if str(u).strip()]
    if not ids:
        raise ApiError("aucun userId fourni (paramètre obligatoire 'userIds')")
    if len(ids) > 99:
        raise ApiError(f"{len(ids)} userIds : la limite de l'API est de 99 par requête")
    path = "/avatarbust" if bust else "/avatar"
    data = _check(_get(THUMBS_URL + path, params={"userIds": ",".join(ids), "size": size},
                        headers=BASE_HEADERS))
    thumbs = data.get("thumbnails") or {}
    out = {}
    for key, value in thumbs.items():
        if isinstance(value, dict):
            out[str(key)] = {"state": value.get("state"), "url": value.get("url")}
        else:
            out[str(key)] = {"state": None, "url": value}
    if not out:
        # l'API répond 200 {"success":true,"thumbnails":{}} pour des userIds inexistants :
        # on remonte une erreur explicite plutôt qu'un résultat vide silencieux.
        raise ApiError(f"aucune miniature trouvée pour les userIds {','.join(ids)}")
    return out


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    def pp(obj):
        print(json.dumps(obj, indent=2, ensure_ascii=False))

    def _int_arg(default, index=2):
        """sys.argv[index] en int, avec fallback silencieux sur une valeur illisible."""
        try:
            return int(sys.argv[index])
        except (IndexError, ValueError):
            return default

    def _text_arg(default, start=2):
        """sys.argv[start:] complet en texte (permet les espaces : "search fat cat")."""
        parts = sys.argv[start:]
        return " ".join(parts) if parts else default

    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"

    try:
        if cmd == "search":
            q = _text_arg("fedora")
            print(f"=== Recherche objet : '{q}' ===")
            pp(item_search(q))

        elif cmd == "item":
            iid = _int_arg(1029025)
            print(f"=== Objet {iid} ===")
            pp(item_details(iid))

        elif cmd == "value":
            iid = _int_arg(1029025)
            print(f"=== Valeur objet {iid} ===")
            pp(item_value(iid))

        elif cmd == "history":
            iid = _int_arg(1029025)
            days = _int_arg(30, 3)
            rows = item_history(iid, days=days)
            print(f"=== Historique valeur {iid} ({days} j) ===")
            pp({
                "item_id": iid,
                "days": days,
                "num_points": len(rows),
                "points": rows[-30:],
            })

        elif cmd == "itemsales":
            iid = _int_arg(1029025)
            n = _int_arg(50, 3)
            print(f"=== Ventes de l'objet {iid} ===")
            pp(item_sales(iid, limit=n))

        elif cmd == "limiteds":
            n = _int_arg(20)
            print(f"=== Top {n} objets valorisés ===")
            pp(top_limiteds(limit=n))

        elif cmd == "new":
            n = _int_arg(20)
            print(f"=== {n} nouveaux objets ===")
            pp(new_items(limit=n))

        elif cmd == "categories":
            print("=== Catégories du catalogue ===")
            pp(categories())

        elif cmd == "rates":
            print("=== Barèmes de valeur / demande / tendance ===")
            pp(value_rates())

        elif cmd == "changes":
            n = _int_arg(50)
            print(f"=== {n} derniers changements de valeur ===")
            pp(value_changes(limit=n))

        elif cmd == "catalogue":
            cat = item_catalogue(include_items=False)
            print("=== Catalogue Rolimons (résumé) ===")
            pp(cat)

        elif cmd == "thumbs":
            n = _int_arg(20)
            thumbs = item_thumbnails(limit=n)
            print(f"=== Miniatures d'objets ({len(thumbs)} disponibles) ===")
            pp(thumbs)

        elif cmd == "games":
            n = _int_arg(20)
            cat = game_catalogue(include_games=False)
            print(f"=== Top {n} jeux (catalogue : {cat.get('game_count')}) ===")
            pp({"game_count": cat.get("game_count"), "games": top_games(limit=n)})

        elif cmd == "gsearch":
            q = _text_arg("crossroads")
            print(f"=== Recherche jeu : '{q}' ===")
            pp(game_search(q))

        elif cmd == "game":
            gid = _int_arg(1537690962)
            pts = _int_arg(30, 3)
            print(f"=== Jeu {gid} ===")
            pp(game_details(gid, points=pts))

        elif cmd == "sales":
            n = _int_arg(50)
            print(f"=== {n} ventes récentes ===")
            pp(sale_activity(limit=n))

        elif cmd == "deals":
            n = _int_arg(50)
            print(f"=== {n} deals récents ===")
            pp(deal_activity(limit=n))

        elif cmd == "trades":
            n = _int_arg(20)
            print(f"=== {n} annonces d'échange ===")
            pp(trade_values(limit=n))

        elif cmd == "usersearch":
            q = _text_arg("builderman")
            print(f"=== Utilisateurs : '{q}' ===")
            pp(search_users(q))

        elif cmd == "user":
            name = _text_arg("builderman")
            print(f"=== Utilisateur {name} ===")
            pp(user_profile(name))

        elif cmd == "inventory":
            name = sys.argv[2] if len(sys.argv) > 2 else "builderman"
            n = _int_arg(50, 3)
            print(f"=== Inventaire de {name} ===")
            pp(user_inventory(name, limit=n))

        elif cmd == "assets":
            uid = _int_arg(1)
            n = _int_arg(50, 3)
            print(f"=== Objets du joueur {uid} ===")
            pp(player_assets(uid, limit=n))

        elif cmd == "avatar":
            ids = _text_arg("1,2,3")
            print(f"=== Avatars {ids} ===")
            pp(avatar_thumbnails(ids))

        elif cmd == "groups":
            q = _text_arg("admin")
            print(f"=== Groupes : '{q}' ===")
            pp(search_groups(q))

        else:
            print("""
Usage : python rolimons.py <commande> [args]

Commandes disponibles :
  search <mot-clé>      Rechercher un objet (catalogue filtré côté client)
  item <item_id>        Détails d'un objet (asset ou bundle)
  value <item_id>       Valeur estimée / demande / tendance d'un objet
  history <item_id>     Historique de prix (30 j par défaut)
  itemsales <item_id>   Historique des ventes d'un objet
  limiteds [n]          Top N objets valorisés
  new [n]               Nouveaux objets (créés récemment)
  categories            Catégories du catalogue
  rates                 Barèmes demande / tendance / promotion
  changes [n]           Derniers changements de valeur
  catalogue             Résumé du catalogue (compteurs)
  thumbs [n]            Miniatures d'objets
  games [n]             Top N jeux
  gsearch <mot-clé>     Rechercher un jeu
  game <game_id>        Statistiques d'un jeu (série)
  sales [n]             Ventes récentes
  deals [n]             Deals récents
  trades [n]            Annonces d'échange
  usersearch <mot-clé>  Rechercher un joueur
  user <username>       Profil d'un joueur
  inventory <username>  Inventaire d'un joueur
  assets <user_id>      Objets d'un joueur (brut)
  avatar <id1,id2,..>   Miniatures d'avatars
  groups <mot-clé>      Rechercher un groupe

Exemples :
  python rolimons.py search fedora
  python rolimons.py item 1029025
  python rolimons.py value 1029025
  python rolimons.py user builderman
  python rolimons.py groups admin abuse

Aucune authentification n'est requise : les endpoints consultés sont publics.
""")

    except ApiError as e:
        pp({"error": str(e)})
        sys.exit(1)
    except Exception as e:  # jamais de traceback : on sort proprement
        pp({"error": f"{type(e).__name__}: {e}"})
        sys.exit(1)
