"""
rotrend.py — Client Python pour l'API rotrends.com (api.rotrends.com)

Toutes les données en temps réel, format JSON propre.

L'API est désormais entièrement publique : aucun token, aucun compte, aucune
authentification. Tout ce qui était réservé aux comptes (earning_rank, visits,
like_ratio, durées de session, revenus estimés, top/trending, métriques
horaires, genres, groupes, avatar items) est accessible sans restriction.

Points d'attention de l'API :
  - un `sort` doit exister dans la liste des `fields` demandés
    (ex: sort=-rank_change_day exige rank_change_day dans fields)
  - POST /games/platform_stats attend start_datetime / end_datetime en QUERY
    STRING, avec un corps JSON vide
  - les datasets de métriques sont "1d" (jour) et "1h" (heure)
"""

import base64
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

BASE_URL = "https://api.rotrends.com"

# ─── Headers de base ──────────────────────────────────────────────────────────
BASE_HEADERS = {
    "accept": "*/*",
    "accept-language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "content-type": "application/json",
    "origin": "https://rotrends.com",
    "referer": "https://rotrends.com/",
    "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "cross-site",
}

# Champs réellement acceptés par /explore/games/*
GAME_FIELDS = (
    "game_id,place_id,game_name,icon_url,genre,creator_name,"
    "rank,rank_change_day,playing,rap_14d,earning_rank,visits,like_ratio"
)


class ApiError(RuntimeError):
    """Erreur renvoyée par l'API rotrends (enveloppe success/message)."""


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _unwrap(data: dict) -> dict:
    """Lève une ApiError si l'enveloppe success/message signale une erreur."""
    if isinstance(data, dict) and data.get("success") is False:
        msg = data.get("message") or ""
        errs = (data.get("data") or {}).get("error_messages")
        if errs:
            msg = "; ".join(errs)
        raise ApiError(msg or json.dumps(data)[:300])
    return data


def _get(path: str, params: dict = None) -> dict:
    """GET sur l'API rotrends avec décodage base64 auto."""
    url = BASE_URL + path
    resp = requests.get(url, params=params, headers=BASE_HEADERS, impersonate="chrome")
    if resp.status_code != 200:
        return {"error": resp.status_code, "detail": resp.text}
    text = resp.text.strip()
    try:
        return _unwrap(resp.json())
    except ApiError:
        raise
    except Exception:
        try:
            return _unwrap(json.loads(base64.b64decode(text).decode("utf-8")))
        except ApiError:
            raise
        except Exception:
            return {"raw": text}


def _post(path: str, body: dict = None, params: dict = None) -> dict:
    """POST sur l'API rotrends."""
    url = BASE_URL + path
    resp = requests.post(url, json=body if body is not None else {}, params=params,
                         headers=BASE_HEADERS, impersonate="chrome")
    if resp.status_code != 200:
        return {"error": resp.status_code, "detail": resp.text}
    return _unwrap(resp.json())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _days_ago_iso(days: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


# ─── 1. Statistiques plateforme Roblox (CCU) ─────────────────────────────────

def platform_stats(days: int = 14) -> dict:
    """
    CCU en temps réel + historique (public, sans token).

    start_datetime / end_datetime doivent être passés en QUERY STRING et non
    dans le corps JSON, et le corps doit être un objet JSON vide.
    """
    start = _days_ago_iso(days)
    end = _now_iso()
    data = _post(
        "/games/platform_stats",
        body={},
        params={"start_datetime": start, "end_datetime": end},
    )
    raw = data.get("data", data)
    return {
        "latest_ccu": raw.get("latest_ccu"),
        "latest_ccu_timestamp": raw.get("latest_ccu_timestamp"),
        "peak_ccu": raw.get("peak_ccu"),
        "peak_ccu_timestamp": raw.get("peak_ccu_timestamp"),
        "ccu_history": raw.get("ccu_history", []),
        "known_game_count": raw.get("known_game_count"),
    }


# ─── 2. Exploration des jeux ──────────────────────────────────────────────────

def explore_games(
    group: str = "all",
    page: int = 1,
    page_size: int = 20,
    sort: str = "-playing",
    keyword: str = None,
    creator: str = None,
    genre: str = None,
    sub_genre: str = None,
    playing_min: int = None,
    rank_max: int = None,
    created_min_days: int = None,
    fields: str = GAME_FIELDS,
) -> dict:
    """
    Route générique d'exploration des jeux.

    group : "all" | "TopTrending" | "UpAndComing"
            (le site utilise aussi des groupes de la forme "genre:primary:Action")
    sort  : -playing | -visits | -like_ratio | -earning_rank | -rap_14d
            | -est_avg_session_duration_naive | -rank_change_day
            (un sort doit être présent dans `fields`)
    """
    params = {"page": page, "page_size": page_size, "sort": sort, "fields": fields}
    if keyword:
        params["keyword"] = keyword
    if creator:
        params["creator"] = creator
    if genre:
        params["genre"] = genre
    if sub_genre:
        params["sub_genre"] = sub_genre
    if playing_min is not None:
        params["playing_min"] = playing_min
    if rank_max is not None:
        params["rank_max"] = rank_max
    if created_min_days is not None:
        params["created_min"] = _days_ago_iso(created_min_days)

    data = _get(f"/explore/games/{group}", params)
    payload = data.get("data", {})
    return {
        "games": payload.get("games", []),
        "aggregate": payload.get("aggregate", {}),
        "total_count": payload.get("total_count", 0),
    }


def search_games(
    keyword: str,
    page: int = 1,
    page_size: int = 20,
    sort: str = "-playing",
    playing_min: int = None,
    fields: str = GAME_FIELDS,
) -> list[dict]:
    """Recherche un jeu par mot-clé."""
    params = {
        "page": page,
        "page_size": page_size,
        "sort": sort,
        "fields": fields,
        "keyword": keyword,
    }
    if playing_min is not None:
        params["playing_min"] = playing_min

    data = _get("/explore/games/all", params)
    return data.get("data", {}).get("games", [])


def top_games(
    sort: str = "-playing",
    page_size: int = 10,
    page: int = 1,
    playing_min: int = None,
    rank_max: int = None,
    created_min_days: int = None,
    fields: str = GAME_FIELDS,
) -> list[dict]:
    """Top jeux selon un critère de tri (voir explore_games pour les tris)."""
    params = {"page": page, "page_size": page_size, "sort": sort, "fields": fields}
    if playing_min is not None:
        params["playing_min"] = playing_min
    if rank_max is not None:
        params["rank_max"] = rank_max
    if created_min_days is not None:
        params["created_min"] = _days_ago_iso(created_min_days)

    data = _get("/explore/games/all", params)
    return data.get("data", {}).get("games", [])


# ─── 3. Classements ───────────────────────────────────────────────────────────

def trending_games(limit: int = 10, playing_min: int = 500) -> list[dict]:
    """Jeux qui montent le plus vite en rang (parmi ceux avec assez de joueurs)."""
    return top_games(
        sort="-rank_change_day",
        page_size=limit,
        playing_min=playing_min,
        fields="game_id,game_name,creator_name,icon_url,rank,rank_change_day,playing",
    )


def new_trending_games(limit: int = 10, days_old: int = 30) -> list[dict]:
    """Nouveaux jeux (créés récemment) qui trending le plus fort."""
    return top_games(
        sort="-rank_change_day",
        page_size=limit,
        created_min_days=days_old,
        fields="game_id,game_name,creator_name,icon_url,rank,rank_change_day,playing",
    )


def top_group_games(group: str = "TopTrending", limit: int = 10) -> list[dict]:
    """Classement fourni par le site : TopTrending / UpAndComing."""
    return explore_games(
        group=group,
        page_size=limit,
        sort="-rank_change_day",
        fields="game_id,game_name,creator_name,icon_url,rank,rank_change_day,playing",
    )["games"]


def longest_session_games(limit: int = 10, playing_min: int = 100) -> list[dict]:
    """Jeux avec les sessions les plus longues (retention maximale)."""
    return top_games(
        sort="-est_avg_session_duration_naive",
        page_size=limit,
        playing_min=playing_min,
    )


def top_earning_games(limit: int = 10) -> list[dict]:
    """Jeux avec les meilleurs revenus estimés (earning_rank)."""
    return top_games(sort="-earning_rank", page_size=limit)


def top_visited_games(limit: int = 10) -> list[dict]:
    """Jeux les plus visités (visits cumulés)."""
    return top_games(sort="-visits", page_size=limit)


def top_liked_games(limit: int = 10) -> list[dict]:
    """Jeux les mieux notés (like_ratio)."""
    return top_games(sort="-like_ratio", page_size=limit)


# ─── 4. Analyse détaillée d'un jeu ───────────────────────────────────────────

def game_details(game_id: int) -> dict:
    """Collections, classements et datasets disponibles d'un jeu."""
    data = _get(f"/explore/games/{game_id}/details", {"fields": "collections"})
    return data.get("data", data)


def game_metrics(
    game_id: int,
    fields: str = "playing,like_ratio,earning_rank,visits",
    days: int = 14,
    dataset: str = "1d",
) -> dict:
    """
    Métriques historiques d'un jeu.

    fields  : playing, like_ratio, earning_rank, visits (séparés par virgule)
    dataset : "1d" (journalier) ou "1h" (horaire)
    """
    start = _days_ago_iso(days)
    end = _now_iso()
    results = {}
    for field in fields.split(","):
        field = field.strip()
        params = {
            "fields": field,
            "start": start,
            "end": end,
            "include_previous_period": "true",
            "dataset": dataset,
        }
        # L'API accepte un field à la fois pour les métriques
        data = _get(f"/explore/games/{game_id}/metrics/{dataset}", params)
        results[field] = data.get("data", {}).get("metrics", [])
    return results


def game_changelog(game_id: int, days: int = 14) -> list[dict]:
    """Historique des changements d'un jeu (nom, icône, prix, produits…)."""
    params = {
        "start": _days_ago_iso(days),
        "end": _now_iso(),
        "dataset": "1d",
    }
    data = _get(f"/explore/games/{game_id}/changelog", params)
    return data.get("data", [])


def analyze_game(game_id: int, days: int = 14) -> dict:
    """Analyse complète d'un jeu : détails + métriques + changelog."""
    details = game_details(game_id)
    metrics = game_metrics(game_id, days=days)
    changelog = game_changelog(game_id, days=days)

    game_info = details.get("game", {})
    ranks = details.get("rank_metrics", [])

    return {
        "game_id": game_id,
        "collections": game_info.get("collections", []),
        "available_datasets": details.get("available_datasets", []),
        "rank_metrics": [
            {
                "id": r["id"],
                "name": r["name"],
                "latest_rank": r.get("latest_rank"),
                "rank_delta": r.get("rank_delta"),
                "best_rank": r.get("best_rank"),
                "first_seen": r.get("first_seen"),
                "last_seen": r.get("last_seen"),
            }
            for r in ranks
        ],
        "metrics": {
            field: {
                "latest": vals[-1] if vals else None,
                "history": vals,
            }
            for field, vals in metrics.items()
        },
        "changelog": changelog,
    }


# ─── 5. Genres, groupes, avatar items ────────────────────────────────────────

def explore_genres(page: int = 1, page_size: int = 20, sort: str = "-game_count") -> list[dict]:
    """Genres et sous-genres, avec le nombre de jeux et leurs icônes."""
    data = _get("/explore/genres/all", {
        "page": page, "page_size": page_size, "sort": sort,
    })
    return data.get("data", {}).get("genres", [])


def explore_groups(page: int = 1, page_size: int = 20, sort: str = "-member_count") -> list[dict]:
    """Groupes Roblox (membres, jeux, avatar items, visites, ventes)."""
    data = _get("/explore/groups/all", {
        "page": page, "page_size": page_size, "sort": sort,
    })
    return data.get("data", {}).get("groups", [])


def explore_avatar_items(
    page: int = 1,
    page_size: int = 20,
    sort: str = "-favorites",
    keyword: str = None,
) -> list[dict]:
    """Avatar items (vêtements, UGC) avec leurs statistiques."""
    params = {"page": page, "page_size": page_size, "sort": sort}
    if keyword:
        params["keyword"] = keyword
    data = _get("/explore/avatar-items/all", params)
    return data.get("data", {}).get("items", [])


# ─── 6. Limites des paliers ───────────────────────────────────────────────────

def tier_limits() -> dict:
    """Limites par palier (free / creator) — donnée publique."""
    data = _get("/rotrends/game-collections/limits")
    return data.get("data", data)


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    def pp(obj):
        print(json.dumps(obj, indent=2, ensure_ascii=False))

    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"

    if cmd == "ccu":
        print("=== CCU Roblox en temps réel ===")
        stats = platform_stats(days=7)
        print(f"CCU actuel : {stats['latest_ccu']:,}" if stats.get("latest_ccu") is not None
              else "CCU actuel : n/d")
        print(f"CCU record : {stats['peak_ccu']:,}  ({stats.get('peak_ccu_timestamp')})"
              if stats.get("peak_ccu") is not None else "CCU record : n/d")
        print(f"Mesuré le : {stats.get('latest_ccu_timestamp')}")
        print(f"Jeux connus : {stats.get('known_game_count')}")
        print(f"Points d'historique : {len(stats.get('ccu_history') or [])}")

    elif cmd == "top":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        print(f"=== Top {n} jeux par CCU ===")
        pp(top_games(page_size=n))

    elif cmd == "trending":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        print(f"=== {n} jeux en tendance ===")
        pp(trending_games(limit=n))

    elif cmd == "new_trending":
        print("=== Nouveaux jeux trending ===")
        pp(new_trending_games())

    elif cmd == "earning":
        print("=== Top jeux revenus ===")
        pp(top_earning_games())

    elif cmd == "visits":
        print("=== Top jeux les plus visités ===")
        pp(top_visited_games())

    elif cmd == "liked":
        print("=== Top jeux les mieux notés ===")
        pp(top_liked_games())

    elif cmd == "session":
        print("=== Jeux sessions les plus longues ===")
        pp(longest_session_games())

    elif cmd == "group":
        g = sys.argv[2] if len(sys.argv) > 2 else "TopTrending"
        print(f"=== Classement {g} ===")
        pp(top_group_games(group=g))

    elif cmd == "search":
        q = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "brookhaven"
        print(f"=== Recherche : '{q}' ===")
        pp(search_games(q))

    elif cmd == "analyze":
        gid = int(sys.argv[2]) if len(sys.argv) > 2 else 7018190066
        print(f"=== Analyse jeu {gid} ===")
        pp(analyze_game(gid))

    elif cmd == "changelog":
        gid = int(sys.argv[2]) if len(sys.argv) > 2 else 7018190066
        print(f"=== Changelog jeu {gid} ===")
        pp(game_changelog(gid))

    elif cmd == "hourly":
        gid = int(sys.argv[2]) if len(sys.argv) > 2 else 7018190066
        print(f"=== Métriques horaires jeu {gid} ===")
        pp(game_metrics(gid, fields="playing,visits", days=2, dataset="1h"))

    elif cmd == "genres":
        print("=== Genres ===")
        pp(explore_genres())

    elif cmd == "groups":
        print("=== Groupes Roblox ===")
        pp(explore_groups())

    elif cmd == "avatar":
        print("=== Avatar items ===")
        pp(explore_avatar_items())

    elif cmd == "limits":
        print("=== Limites par palier ===")
        pp(tier_limits())

    else:
        print("""
Usage : python rotrend.py <commande> [args]

Commandes disponibles :
  ccu                      CCU Roblox en temps réel + historique
  top [n]                  Top N jeux par joueurs actifs
  trending [n]             Jeux qui montent le plus vite
  new_trending             Nouveaux jeux trending
  group [TopTrending|UpAndComing]   Classement du site
  earning                  Top jeux par revenus estimés
  visits                   Top jeux les plus visités
  liked                    Top jeux les mieux notés
  session                  Jeux avec sessions les plus longues
  search <mot-clé>         Rechercher un jeu
  analyze <game_id>        Analyse complète d'un jeu
  changelog <game_id>      Historique des changements d'un jeu
  hourly [game_id]         Métriques horaires (dataset 1h)
  genres                   Genres et sous-genres
  groups                   Groupes Roblox
  avatar                   Avatar items (UGC)
  limits                   Limites par palier

Exemples :
  python rotrend.py ccu
  python rotrend.py top 20
  python rotrend.py search dead rails
  python rotrend.py analyze 7018190066
  python rotrend.py trending 15

Aucune authentification n'est requise : l'API est entièrement publique.
""")
