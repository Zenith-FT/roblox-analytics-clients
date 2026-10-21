"""
romonitorstats.py — Client Python pour l'API romonitorstats.com (/api/v1)

Données publiques en temps réel, format JSON propre.

Aucune authentification n'est requise : tous les endpoints publics sont en lecture seule.
Seuls les endpoints POST exigent un jeton CSRF Laravel, généré automatiquement et
sans compte (handshake Sanctum).

Points d'attention de l'API (voir .research/romonitorstats.md) :
  - les réponses sont du JSON BARE : pas d'enveloppe {"success": ..., "data": ...}
    (certains endpoints renvoient même une chaîne ou un nombre seul)
  - les paramètres se passent en QUERY STRING (prioritaire) ou dans le corps JSON ;
    les noms de champs sont en camelCase : placeId, userId, communityId, analytic...
  - la borne haute de la fenêtre de dates est `ends` (et non `end`)
  - un utilisateur anonyme ne voit qu'une fenêtre de 14 jours maximum
    (au-delà : 403 "You must be logged in to view this chart.")
  - les POST exigent un handshake CSRF Laravel Sanctum : GET /sanctum/csrf-cookie/
    puis en-tête X-XSRF-TOKEN (valeur du cookie XSRF-TOKEN décodée)
  - les erreurs sont des {"message": "..."} ; 429 = "Too Many Attempts." (+ retry-after)
  - limite de débit : 80 requêtes/minute/IP (300 pour les graphiques)
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from curl_cffi import requests

# La console Windows est souvent en cp1252 : les noms de jeux contiennent des emoji
# qui font planter print(). On force l'UTF-8 avec remplacement.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SITE_URL = "https://romonitorstats.com"
BASE_URL = "https://romonitorstats.com/api/v1"
CSRF_URL = "https://romonitorstats.com/sanctum/csrf-cookie/"
SEARCH_URL = "https://search.romonitorstats.com"
# Clé publique (search-only) embarquée dans le bundle de la SPA RoMonitor.
SEARCH_KEY = "MEILISEARCH_KEY_REDACTED"

# ─── Headers de base ──────────────────────────────────────────────────────────
# L'API vit sous /api/v1 sur le même domaine que le site → sec-fetch-site: same-origin.
# Pas de user-agent : curl_cffi le gère via impersonate="chrome" (P16).
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
    "sec-fetch-site": "same-origin",
}

# Hôte de recherche séparé (Meilisearch) : requête cross-site.
SEARCH_HEADERS = {
    "accept": "application/json",
    "content-type": "application/json",
    "authorization": "Bearer " + SEARCH_KEY,
}

TIMEOUT = 30

# Fenêtre maximale d'un utilisateur anonyme (au-delà → 403).
MAX_DAYS = 14

# Expérience utilisée par défaut : « Steal An Egg », indexée par RoMonitor.
DEFAULT_PLACE_ID = 107778070777162
DEFAULT_USER_ID = 1
DEFAULT_COMMUNITY_ID = 1
DEFAULT_GENRE = "Simulation"

# Graphiques publics (les autres renvoient 403 « You must be logged in »).
CHART_NAMES = (
    "ccus", "visits", "session-length", "rating", "favourites", "likes-and-dislikes",
    "paying-users", "conversion-rate", "arp-dau", "server-stats", "server-memory",
    "client-memory", "client-memory-percentage", "compute-efficiency", "crash-rates",
    "genre-ccus", "genre-session-length", "genre-favourites", "genre-visits",
    "community-members", "daily-community-members", "user-experience-ccus",
    "user-experience-visits", "community-experience-ccus", "community-experience-visits",
    "ccu-platform-share", "platform-ccus", "top-earning-sort-position", "iap-revenue",
    "net-revenue-per-visitor", "new-users-by-source", "sessions-per-player-per-day",
    "experience-country-revenue-pie-chart", "usd-revenue-breakdown-pie-chart",
    "gender-pie-chart", "experience-update-flags",
)

# Tableaux publics (les autres renvoient 403 « You must be logged in »).
TABLE_NAMES = (
    "branded-deep-dive",
    "top-developers-deep-dive",
    "campaigns-deep-dive",
    "concerts-deep-dive",
)

# Analytiques du classement (valeur invalide → 422 « The selected analytic is invalid »).
LEADERBOARD_ANALYTICS = ("active", "visits", "favourites", "likes", "dislikes")

# Analytiques de /stats/generate-chart/get (vérifiées en direct).
GENERATE_ANALYTICS = ("visits", "playing", "favourites", "rating")

# Granularités acceptées par /charts/get.
TIMESLICES = ("day", "hourly", "half-hourly")


class ApiError(RuntimeError):
    """Erreur renvoyée par l'API romonitorstats (code HTTP + corps {"message": ...})."""


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _unquote(value: str) -> str:
    """Décode les séquences %XX (le cookie XSRF-TOKEN est URL-encodé par Laravel)."""
    out = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == "%" and i + 2 < len(value):
            try:
                out.append(chr(int(value[i + 1:i + 3], 16)))
                i += 3
                continue
            except ValueError:
                pass
        out.append(ch)
        i += 1
    return "".join(out)


def _error(resp) -> dict:
    """Construit le dictionnaire d'erreur interne à partir d'une réponse HTTP."""
    message = ""
    try:
        payload = resp.json()
        if isinstance(payload, dict):
            message = payload.get("message") or ""
    except Exception:
        pass
    text = resp.text or ""
    if not message:
        message = text[:200]
    # "__http_error__" est un sentinelle : la clé "error" d'une donnée légitime
    # ne doit jamais être confondue avec une erreur HTTP.
    return {
        "__http_error__": resp.status_code,
        "message": message,
        "detail": text[:400],
    }


def _decode(resp):
    """Décode une réponse : JSON brut (dict/list/str/number) ou dictionnaire d'erreur."""
    if resp.status_code != 200:
        return _error(resp)
    try:
        return resp.json()
    except Exception:
        return {
            "__http_error__": "decode",
            "message": "réponse non JSON (page Cloudflare ?)",
            "detail": (resp.text or "")[:400],
        }


def _check(data):
    """Lève une ApiError si _get/_post a renvoyé une erreur HTTP ou un corps non-JSON."""
    if isinstance(data, dict) and "__http_error__" in data:
        status = data.get("__http_error__")
        message = data.get("message") or data.get("detail") or ""
        raise ApiError(f"HTTP {status} : {str(message)[:200]}")
    return data


def _get(path: str, params: dict = None, base: str = None, headers: dict = None):
    """GET sur l'API romonitorstats. Retourne le JSON décodé ou un dict d'erreur."""
    url = (base or BASE_URL) + path
    resp = requests.get(url, params=params, headers=headers or BASE_HEADERS,
                        impersonate="chrome", timeout=TIMEOUT)
    return _decode(resp)


def _csrf(session) -> str:
    """
    Handshake CSRF Laravel Sanctum : GET /sanctum/csrf-cookie/ (204) puis lecture
    du cookie XSRF-TOKEN. Retourne sa valeur décodée (en-tête X-XSRF-TOKEN).
    """
    session.get(CSRF_URL, headers=BASE_HEADERS, impersonate="chrome", timeout=TIMEOUT)
    token = session.cookies.get("XSRF-TOKEN") or ""
    return _unquote(token)


def _post(path: str, body: dict = None, params: dict = None, base: str = None,
          headers: dict = None, csrf: bool = False):
    """POST sur l'API romonitorstats. `params` part en QUERY STRING, `body` en JSON."""
    url = (base or BASE_URL) + path
    hdrs = dict(headers or BASE_HEADERS)
    session = None
    if csrf:
        session = requests.Session()
        token = _csrf(session)
        if token:
            hdrs["X-XSRF-TOKEN"] = token
    http = session if session is not None else requests
    resp = http.post(url, json=body if body is not None else {}, params=params,
                     headers=hdrs, impersonate="chrome", timeout=TIMEOUT)
    return _decode(resp)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _days_ago_iso(days: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _today_iso() -> str:
    """Date du jour au format YYYY-MM-DD (certains endpoints n'acceptent pas l'horodatage complet)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _window_span(days: int) -> int:
    """Amplitude en jours de la fenêtre, plafonnée à MAX_DAYS (accès anonyme)."""
    return max(1, min(int(days), MAX_DAYS) - 1)


def _window(days: int) -> tuple:
    """
    Fenêtre de dates (start, ends) au format ISO8601 Z, plafonnée à 14 jours.
    Un utilisateur anonyme reçoit 403 au-delà ; `days` = nombre de points journaliers.
    """
    return _days_ago_iso(_window_span(days)), _now_iso()


def _effective_days(days: int) -> int:
    """Nombre de jours réellement couverts par la fenêtre (points journaliers renvoyés)."""
    return _window_span(days) + 1


def _window_label(days: int) -> str:
    """
    Étiquette de fenêtre pour les bandeaux : jours RÉELLEMENT couverts, plus une
    note quand la demande a été plafonnée (MAX_DAYS = accès anonyme).
    """
    requested = int(days)
    eff = _effective_days(requested)
    if eff == requested:
        return f"{eff} j"
    if requested > MAX_DAYS:
        return f"{eff} j — {requested} j demandés, plafonné à {MAX_DAYS} j (accès anonyme)"
    return f"{eff} j (fenêtre effective, {requested} j demandés)"


def _enum(value: str, allowed: tuple, label: str) -> str:
    """Valide un paramètre enum : une valeur invalide ne doit jamais passer en silence."""
    if value not in allowed:
        raise ApiError(
            f"{label} invalide : '{value}' (valeurs acceptées : {', '.join(allowed)})"
        )
    return value


# ─── API romonitorstats ───────────────────────────────────────────────────────
#
# Règles :
#   * chaque appel HTTP passe par _check(_get(...)) / _check(_post(...))
#   * docstring = ce que fait la fonction + "Endpoint : <METHOD> <path>"
#   * les filtres optionnels ne sont ajoutés au params que s'ils sont non-None
#   * aucune déballage d'enveloppe : l'API répond en JSON brut

def homepage_data() -> dict:
    """
    Données de la page d'accueil : expériences les plus jouées, top des brands,
    concerts, développeurs Roblox, campagnes et métadonnées d'analyse.

    Endpoint : GET /api/v1/homepage-data/get/
    """
    return _check(_get("/homepage-data/get/"))


def leaderboard(page: int = 1, analytic: str = "active") -> dict:
    """
    Classement des expériences (10 par page) selon un critère : joueurs actifs,
    visites, favoris, likes ou dislikes.

    Endpoint : GET /api/v1/leaderboards/list
    """
    _enum(analytic, LEADERBOARD_ANALYTICS, "analytic")
    return _check(_get("/leaderboards/list", {"page": int(page), "analytic": analytic}))


def chart(
    name: str = "ccus",
    place_id: int = None,
    genre: str = None,
    community_id: int = None,
    user_id: int = None,
    badge_id: int = None,
    timeslice: str = "day",
    days: int = MAX_DAYS,
) -> list:
    """
    Série(s) d'un graphique public (CCU, visites, note, revenus…). La portée est
    choisie par un seul paramètre : placeId, genre, communityId, userId ou badgeId.
    Fenêtre limitée à 14 jours (403 au-delà en accès anonyme).

    Endpoint : GET /api/v1/charts/get
    """
    _enum(name, CHART_NAMES, "name")
    _enum(timeslice, TIMESLICES, "timeslice")
    start, ends = _window(days)
    params = {"name": name, "timeslice": timeslice, "start": start, "ends": ends}
    if place_id is not None:
        params["placeId"] = str(place_id)
    if genre is not None:
        params["genre"] = genre
    if community_id is not None:
        params["communityId"] = str(community_id)
    if user_id is not None:
        params["userId"] = str(user_id)
    if badge_id is not None:
        params["badgeId"] = str(badge_id)
    return _check(_get("/charts/get", params))


def table(name: str = "branded-deep-dive") -> dict:
    """
    Tableau public (marques, développeurs, campagnes, concerts) avec ses colonnes.

    Endpoint : GET /api/v1/tables/get
    """
    _enum(name, TABLE_NAMES, "name")
    return _check(_get("/tables/get", {"name": name}))


def game_charts(place_id: int = DEFAULT_PLACE_ID) -> list:
    """
    Les 26 graphiques disponibles pour une expérience (Top Earning, Top Playing Now,
    Most Popular…) avec l'expérience qui domine chaque classement.

    Endpoint : GET /api/v1/stats/charts/get/
    """
    return _check(_get("/stats/charts/get/", {"placeId": str(place_id)}))


def game_profile(place_id: int = DEFAULT_PLACE_ID) -> dict:
    """
    Fiche d'une expérience : nom, univers, icônes, créateur, genres, date de création.

    Endpoint : GET /api/v1/stats/game-profile/get/
    """
    return _check(_get("/stats/game-profile/get/", {"placeId": str(place_id)}))


def game_general(place_id: int = DEFAULT_PLACE_ID, period: str = "24h") -> dict:
    """
    Statistiques générales d'une expérience sur une période (24h, 14d…) :
    joueurs, visites, temps de jeu, interactions, jalons.

    Endpoint : GET /api/v1/stats/game-general/get/
    """
    return _check(_get("/stats/game-general/get/",
                       {"placeId": str(place_id), "period": period}))


def game_sort(place_id: int = DEFAULT_PLACE_ID, page: int = 1, code: str = "top-earning") -> dict:
    """
    Classement d'expériences pour un code de tri (top-earning, most-popular,
    up-and-coming…), utilisé par le jeu pour comparer ses concurrentes.

    Endpoint : GET /api/v1/stats/sort/get/
    """
    return _check(_get("/stats/sort/get/",
                       {"placeId": str(place_id), "page": int(page), "code": code}))


def sorts_list() -> dict:
    """
    Liste des codes de tri disponibles (top-earning, top-playing-now, most-popular,
    up-and-coming…) avec leur libellé.

    Endpoint : GET /api/v1/stats/roblox-sorts-list/get/
    """
    return _check(_get("/stats/roblox-sorts-list/get/"))


def peak_ccus(place_id: int = DEFAULT_PLACE_ID) -> str:
    """
    Pic de joueurs concurrents jamais atteint par l'expérience (chaîne JSON brute).

    Endpoint : GET /api/v1/stats/experience-peak-ccus/get/
    """
    return _check(_get("/stats/experience-peak-ccus/get/", {"placeId": str(place_id)}))


def milestones(place_id: int = DEFAULT_PLACE_ID, limit: int = 10) -> dict:
    """
    Jalons atteints par l'expérience (10 M, 25 M, 1 B visites ;likes ; joueurs).

    Endpoint : GET /api/v1/stats/milestones/get/
    """
    return _check(_get("/stats/milestones/get/",
                       {"placeId": str(place_id), "limit": int(limit), "gameId": str(place_id)}))


def genre_total_visits(genre: str = DEFAULT_GENRE) -> str:
    """
    Nombre total de visites pour un genre Roblox (chaîne JSON brute).

    Endpoint : GET /api/v1/stats/genre-total-visits/get/
    """
    return _check(_get("/stats/genre-total-visits/get/", {"genre": genre}))


def user_profile(user_id: int = DEFAULT_USER_ID) -> dict:
    """
    Profil public d'un joueur Roblox : compte, statistiques cumulées et ses expériences.

    Endpoint : GET /api/v1/stats/roblox-user/get/
    """
    return _check(_get("/stats/roblox-user/get/", {"userId": str(user_id)}))


def community_profile(community_id: int = DEFAULT_COMMUNITY_ID) -> dict:
    """
    Profil public d'un groupe Roblox : propriétaire, slogan et état des analyses.

    Endpoint : GET /api/v1/stats/roblox-community/get/
    """
    return _check(_get("/stats/roblox-community/get/", {"communityId": str(community_id)}))


def search_games(term: str, limit: int = 10) -> list:
    """
    Recherche plein texte d'expériences (index Meilisearch `games_index`).
    Renvoie les hits enrichis : joueurs, visites, note, likes, créateur.

    Endpoint : POST https://search.romonitorstats.com/indexes/games_index/search
    """
    data = _check(_post("/indexes/games_index/search",
                        body={"q": term, "limit": int(limit)},
                        base=SEARCH_URL, headers=SEARCH_HEADERS))
    return data.get("hits", []) if isinstance(data, dict) else []


def card_stats(place_id: int = DEFAULT_PLACE_ID) -> dict:
    """
    Carte de statistiques d'une expérience : joueurs, visites, durée de session, note.

    Endpoint : GET /api/v1/experience/{placeId}/card-stats/get/
    """
    return _check(_get(f"/experience/{place_id}/card-stats/get/"))


def generate_chart(analytic: str = "visits", place_id: int = DEFAULT_PLACE_ID,
                   timeframe: str = "14d") -> list:
    """
    Courbe générée à la volée pour une expérience et une analytique
    (visits, playing, favourites, rating) sur une période.

    Endpoint : GET /api/v1/stats/generate-chart/get
    """
    _enum(analytic, GENERATE_ANALYTICS, "analytic")
    return _check(_get("/stats/generate-chart/get",
                       {"analytic": analytic, "placeId": str(place_id), "timeframe": timeframe}))


def social_graph(place_id: int = DEFAULT_PLACE_ID) -> dict:
    """
    Réseau social d'une expérience : serveurs Discord, comptes Twitter / YouTube /
    Twitch, groupes Roblox, portée globale estimée.

    Endpoint : GET /api/v1/stats/game-social-graph/get/
    """
    return _check(_get("/stats/game-social-graph/get/", {"placeId": str(place_id)}))


def devex_rate() -> dict:
    """
    Taux DevEx Roblox en vigueur, taux précédent, seuils de Robux et infobulle.

    Endpoint : GET /api/v1/money/get-devex-rate/
    """
    return _check(_get("/money/get-devex-rate/"))


def exchange_rates() -> dict:
    """
    Taux de change des devises (USD, EUR, GBP…) utilisés par RoMonitor.

    Endpoint : GET /api/v1/money/list-exchange-rates/
    """
    return _check(_get("/money/list-exchange-rates/"))


def total_visits(place_id: int = DEFAULT_PLACE_ID, days: int = MAX_DAYS) -> int:
    """
    Total des visites de l'expérience sur la fenêtre demandée (nombre JSON brut).
    Endpoint POST : jeton CSRF requis, `range` = "start=…&ends=…".

    Endpoint : POST /api/v1/stats/total-visits/get/
    """
    start, ends = _window(days)
    body = {"placeId": str(place_id), "range": f"start={start}&ends={ends}"}
    return _check(_post("/stats/total-visits/get/", body=body, csrf=True))


def wallboard(place_id: int = DEFAULT_PLACE_ID) -> dict:
    """
    Cartes du « wallboard » d'une expérience : joueurs, visites, record de joueurs,
    likes, favoris. Endpoint POST : jeton CSRF requis.

    Endpoint : POST /api/v1/wallboard/data/
    """
    return _check(_post("/wallboard/data/", body={"placeId": str(place_id)}, csrf=True))


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    def pp(obj):
        print(json.dumps(obj, indent=2, ensure_ascii=False))

    def _arg(index: int, default: str = "") -> str:
        """sys.argv[index] en texte, avec valeur par défaut si l'argument manque."""
        return sys.argv[index] if len(sys.argv) > index else default

    def _int_arg(index: int, default: int) -> int:
        """sys.argv[index] en int, avec fallback silencieux sur une valeur illisible."""
        try:
            return int(sys.argv[index])
        except (IndexError, ValueError):
            return default

    def _text_arg(default: str) -> str:
        """sys.argv[2:] complet en texte (permet les espaces : "search dead rails")."""
        parts = sys.argv[2:]
        return " ".join(parts) if parts else default

    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"

    try:
        if cmd == "homepage":
            print("=== Accueil RoMonitor : expériences en tête ===")
            pp(homepage_data())

        elif cmd == "leaderboard":
            analytic = _arg(2, "active")
            page = _int_arg(3, 1)
            print(f"=== Classement RoMonitor : {analytic} (page {page}) ===")
            pp(leaderboard(page=page, analytic=analytic))

        elif cmd == "chart":
            name = _arg(2, "ccus")
            place_id = _int_arg(3, DEFAULT_PLACE_ID)
            days = _int_arg(4, MAX_DAYS)
            print(f"=== Graphique '{name}' — expérience {place_id} ({_window_label(days)}) ===")
            pp(chart(name=name, place_id=place_id, timeslice="day", days=days))

        elif cmd == "genre-chart":
            name = _arg(2, "genre-ccus")
            genre = _arg(3, DEFAULT_GENRE)
            days = _int_arg(4, MAX_DAYS)
            print(f"=== Graphique '{name}' — genre {genre} ({_window_label(days)}) ===")
            pp(chart(name=name, genre=genre, timeslice="day", days=days))

        elif cmd == "table":
            name = _arg(2, "branded-deep-dive")
            print(f"=== Tableau RoMonitor : {name} ===")
            pp(table(name=name))

        elif cmd == "game-charts":
            pid = _int_arg(2, DEFAULT_PLACE_ID)
            print(f"=== Graphiques disponibles pour l'expérience {pid} ===")
            pp(game_charts(place_id=pid))

        elif cmd == "game":
            pid = _int_arg(2, DEFAULT_PLACE_ID)
            print(f"=== Profil de l'expérience {pid} ===")
            pp(game_profile(place_id=pid))

        elif cmd == "general":
            pid = _int_arg(2, DEFAULT_PLACE_ID)
            period = _arg(3, "24h")
            print(f"=== Statistiques générales — expérience {pid} ({period}) ===")
            pp(game_general(place_id=pid, period=period))

        elif cmd == "sort":
            pid = _int_arg(2, DEFAULT_PLACE_ID)
            code = _arg(3, "top-earning")
            page = _int_arg(4, 1)
            print(f"=== Classement '{code}' (page {page}) ===")
            pp(game_sort(place_id=pid, page=page, code=code))

        elif cmd == "sorts":
            print("=== Codes de tri disponibles ===")
            pp(sorts_list())

        elif cmd == "peak":
            pid = _int_arg(2, DEFAULT_PLACE_ID)
            print(f"=== Pic de joueurs concurrents — expérience {pid} ===")
            pp(peak_ccus(place_id=pid))

        elif cmd == "milestones":
            pid = _int_arg(2, DEFAULT_PLACE_ID)
            limit = _int_arg(3, 10)
            print(f"=== Jalons de l'expérience {pid} ===")
            pp(milestones(place_id=pid, limit=limit))

        elif cmd == "genre":
            genre = _arg(2, DEFAULT_GENRE)
            print(f"=== Visites totales du genre {genre} ===")
            pp(genre_total_visits(genre=genre))

        elif cmd == "user":
            uid = _int_arg(2, DEFAULT_USER_ID)
            print(f"=== Profil joueur {uid} ===")
            pp(user_profile(user_id=uid))

        elif cmd == "community":
            cid = _int_arg(2, DEFAULT_COMMUNITY_ID)
            print(f"=== Profil groupe {cid} ===")
            pp(community_profile(community_id=cid))

        elif cmd == "search":
            term = _text_arg("steal an egg")
            print(f"=== Recherche d'expériences : '{term}' ===")
            pp(search_games(term))

        elif cmd == "card":
            pid = _int_arg(2, DEFAULT_PLACE_ID)
            print(f"=== Carte de statistiques — expérience {pid} ===")
            pp(card_stats(place_id=pid))

        elif cmd == "gen-chart":
            analytic = _arg(2, "visits")
            pid = _int_arg(3, DEFAULT_PLACE_ID)
            timeframe = _arg(4, "14d")
            print(f"=== Courbe '{analytic}' — expérience {pid} ({timeframe}) ===")
            pp(generate_chart(analytic=analytic, place_id=pid, timeframe=timeframe))

        elif cmd == "social":
            pid = _int_arg(2, DEFAULT_PLACE_ID)
            print(f"=== Réseau social de l'expérience {pid} ===")
            pp(social_graph(place_id=pid))

        elif cmd == "total-visits":
            pid = _int_arg(2, DEFAULT_PLACE_ID)
            days = _int_arg(3, MAX_DAYS)
            print(f"=== Visites totales — expérience {pid} ({_window_label(days)}) ===")
            pp(total_visits(place_id=pid, days=days))

        elif cmd == "wallboard":
            pid = _int_arg(2, DEFAULT_PLACE_ID)
            print(f"=== Wallboard — expérience {pid} ===")
            pp(wallboard(place_id=pid))

        elif cmd == "devex":
            print("=== Taux DevEx Roblox ===")
            pp(devex_rate())

        elif cmd == "rates":
            print("=== Taux de change ===")
            pp(exchange_rates())

        else:
            print("""
Usage : python romonitorstats.py <commande> [args]

Commandes disponibles :
  homepage                    Données de l'accueil (top expériences, marques, concerts)
  leaderboard [analytic] [p]  Classement (active|visits|favourites|likes|dislikes)
  chart <nom> [place_id] [j]  Graphique d'une expérience (fenêtre 14 j max)
  genre-chart <nom> <genre> [j]   Graphique au niveau d'un genre
  table <nom>                 Tableau public (branded|top-developers|campaigns|concerts)
  game-charts <place_id>      Les 26 graphiques disponibles pour une expérience
  game <place_id>             Profil d'une expérience
  general <place_id> [periode]  Statistiques générales (24h, 14d…)
  sort <place_id> [code] [p]  Classement concurrentiel (top-earning, most-popular…)
  sorts                       Codes de tri disponibles
  peak <place_id>             Pic de joueurs concurrents
  milestones <place_id> [n]   Jalons (visites, likes, joueurs)
  genre <genre>               Visites totales d'un genre
  user <user_id>              Profil d'un joueur
  community <community_id>    Profil d'un groupe Roblox
  search <terme>              Recherche d'expériences (Meilisearch)
  card <place_id>             Carte CCU / visites / session / note
  gen-chart <analytique> <place_id> [tf]  Courbe générée (visits|playing|favourites|rating)
  social <place_id>           Discord / Twitter / YouTube / Twitch d'une expérience
  total-visits <place_id> [j] Visites totales sur la fenêtre (POST + CSRF)
  wallboard <place_id>        Cartes du wallboard (POST + CSRF)
  devex                       Taux DevEx Roblox
  rates                       Taux de change

Exemples :
  python romonitorstats.py homepage
  python romonitorstats.py leaderboard visits 2
  python romonitorstats.py chart ccus 107778070777162 14
  python romonitorstats.py genre-chart genre-ccus Simulation 14
  python romonitorstats.py search steal an egg
  python romonitorstats.py game 107778070777162

Aucune authentification n'est requise : tous les endpoints publics sont en lecture seule.
Les endpoints POST utilisent automatiquement un jeton CSRF Laravel, sans compte.
""")

    except ApiError as e:
        pp({"error": str(e)})
        sys.exit(1)
    except Exception as e:
        pp({"error": f"{type(e).__name__} : {e}"})
        sys.exit(1)
