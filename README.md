# Clients Python — API publiques d'analyse Roblox

Trois clients Python, sans dépendance à un compte, qui interrogent des API
publiques de suivi Roblox et renvoient du JSON propre.

```
┌────────────────────────────────────────────────────────────────────────────────┐
│  rotrend.py          api.rotrends.com                                          │
│                      CCU de la plateforme + historique, classements            │
│                      top / trending / revenus, exploration par genre,          │
│                      groupe ou avatar item, métriques horaires et              │
│                      journalières, changelog d'un jeu.                         │
├────────────────────────────────────────────────────────────────────────────────┤
│  romonitorstats.py   https://romonitorstats.com/api/v1                         │
│                      Graphiques et tableaux publics (CCU, visites,             │
│                      note, session), fiche d'expérience / joueur /             │
│                      groupe, classements, jalons, recherche                    │
│                      Meilisearch, taux DevEx et taux de change.                │
├────────────────────────────────────────────────────────────────────────────────┤
│  rolimons.py         https://api.rolimons.com (+ www.rolimons.com)             │
│                      Valeur des objets Limited, RAP, demande et                │
│                      tendance, historique de prix et de ventes,                │
│                      flux du marché, annonces d'échange, profils et            │
│                      inventaires de joueurs, groupes, avatars.                 │
└────────────────────────────────────────────────────────────────────────────────┘
```

Fichiers du dépôt :

| Fichier | Rôle |
|---|---|
| `rotrend.py` | client rotrends (référence pré-existante) |
| `romonitorstats.py` | client RoMonitor Stats (`/api/v1`) |
| `rolimons.py` | client Rolimons (`api.rolimons.com` + HTML) |
| `verify_clients.py` | vérificateur croisé des deux clients |
| `README.md` | ce document |
| `.research/` | notes de reverse-engineering des deux API |

---

## 1. Ce que fait chaque script

### `rotrend.py` — l'API rotrends (référence existante)

Client de l'API publique **https://api.rotrends.com** : il donne le CCU
(joueurs connectés) de toute la plateforme Roblox et son historique, les
classements par joueurs actifs, visites, revenus estimés, ratio de likes ou
durée de session, l'exploration filtrée (genre, créateur, mot-clé, âge de
création) et l'analyse détaillée d'un jeu (séries de métriques, rang,
changelog). C'est le script de référence du projet : les deux clients
ci-dessous suivent la même convention (fonctions pures renvoyant des
`dict`, CLI `__main__` qui sort du JSON, `curl_cffi` avec
`impersonate="chrome"` par défaut).

### `romonitorstats.py` — l'API RoMonitor Stats

Client de l'API publique **https://romonitorstats.com/api/v1** (RoMonitor
Stats, Silicon Digital Group) : les endpoints publics de la SPA — page
d'accueil, classements, graphiques (`/charts/get`, 36 noms publics) et
tableaux publics (`/tables/get`, 4 noms), fiche et statistiques d'une
expérience, code de tri concurrentiel, jalons, profils joueur et groupe,
carte CCU/visites/session, réseau social d'un jeu, taux DevEx, taux de
change, recherche plein texte via Meilisearch, et deux appels POST
(`total-visits`, `wallboard`). 22 endpoints sont utilisés ici, tous vérifiés
en direct ; la phase de recherche en avait validé 33 au total.

### `rolimons.py` — l'API Rolimons

Client de l'API publique **https://api.rolimons.com** (et des pages HTML de
**https://www.rolimons.com**) : la valeur estimée, le RAP, la demande et la
tendance de chaque objet Limited ; le catalogue complet ; l'historique de prix
et de ventes ; le flux du marché (ventes, deals, annonces d'échange) ; les
profils, inventaires et avatars de joueurs ; la recherche de groupes ; les
miniatures d'objets et d'avatars.

### Point clé : aucune authentification

Les trois API sont **entièrement publiques et en lecture seule**. Aucun
compte, aucune clé d'API, aucun jeton n'est nécessaire :

* `rotrend.com` — « l'API est désormais entièrement publique : aucun token,
  aucun compte, aucune authentification ».
* `romonitorstats.com` — tous les endpoints publics sont accessibles sans
  compte ; seuls les deux appels POST exigent un **jeton CSRF Laravel
  Sanctum**, obtenu automatiquement (et sans compte) par un handshake
  `GET /sanctum/csrf-cookie/`.
* `rolimons.com` — aucun en-tête `Authorization`, aucune clé d'API, et
  **aucun challenge Cloudflare** sur les GET : les seuls points de friction
  sont le WAF (qui refuse une requête **sans `User-Agent`**) et la page
  `/player/<id>` (qui exige un `Referer` *quand* on imite un navigateur —
  voir § 4). Seuls deux POST (`addplayerbyname`, `removead`) exigent un
  cookie de vérification **impossible à obtenir anonymement** : ils ne sont
  donc pas implémentés.

---

## 2. Liste des commandes

Les blocs ci-dessous sont la sortie réelle de `py <script>` (sans argument).

### `rotrend.py`

```
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
```

### `romonitorstats.py`

```
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
```

### `rolimons.py`

```
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
```

---

## 3. Exemples d'utilisation

### `rotrend.py`

```bash
py rotrend.py ccu
```
→ CCU actuel + record + nombre de jeux connus (sortie texte, pas du JSON).

```bash
py rotrend.py top 20
```
→ liste JSON des 20 jeux les plus joués (`game_name`, `playing`, `visits`…).

```bash
py rotrend.py trending 15
```
→ 15 jeux qui montent le plus vite en rang.

```bash
py rotrend.py search dead rails
```
→ les jeux dont le nom contient « dead rails ».

```bash
py rotrend.py analyze 7018190066
```
→ détail + métriques (playing, like_ratio, earning_rank, visits) + changelog du jeu.

### `romonitorstats.py`

```bash
py romonitorstats.py homepage
```
→ `topExperiences`, `topFiveBrandedGames`, `topFiveConcerts`, `campaigns`…

```bash
py romonitorstats.py leaderboard visits 2
```
→ 10 expériences classées par visites, page 2.

```bash
py romonitorstats.py chart ccus 107778070777162 14
```
→ séries JSON du CCU moyen de « Steal An Egg » sur 14 jours (+ bloc `metadata`).

```bash
py romonitorstats.py search steal an egg
```
→ hits Meilisearch enrichis (joueurs, visites, note, créateur).

```bash
py romonitorstats.py game 107778070777162
```
→ nom, univers, icônes, créateur, genres, date de création de l'expérience.

### `rolimons.py`

```bash
py rolimons.py search fedora
```
→ objets du catalogue dont le nom contient « fedora », triés par valeur.

```bash
py rolimons.py value 1029025
```
→ valeur estimée, RAP, demande et tendance de « The Classic ROBLOX Fedora ».

```bash
py rolimons.py item 1029025
```
→ détail de l'objet + les données riches de sa page HTML.

```bash
py rolimons.py user builderman
```
→ statut, ancienneté, premium, nombre d'objets et RAP total du joueur.

```bash
py rolimons.py groups admin
```
→ groupes Roblox dont le nom contient « admin ».

---

## 4. Quirks (comportements réellement observés)

Chaque point ci-dessous a été **re-vérifié en direct** le 21/10/2026 (sondes
HTTP + exécution réelle des commandes), en plus des notes de recherche
`.research/`.

### `romonitorstats.py`

* **Fenêtre de 14 jours maximum en anonyme.** Au-delà, l'API répond
  `403 {"message":"You must be logged in to view this chart."}` — exactement
  le même message que pour un graphique réservé aux comptes, donc impossible
  de distinguer les deux cas. `romonitorstats.py` plafonne donc la fenêtre à
  `MAX_DAYS = 14` : `chart … 30` et `chart … 90` renvoient exactement les 14
  mêmes points que `chart … 14`. Le plafonnement est **annoncé** dans le
  bandeau — `14 j — 30 j demandés, plafonné à 14 j (accès anonyme)` — donc
  la fenêtre effective n'est jamais silencieuse. (Détail : ce 403 n'est du
  JSON que si on envoie `Accept: application/json` ; sans cet en-tête on
  reçoit une page HTML « Forbidden ».)
* **Handshake CSRF Laravel pour les POST.** Un POST sans jeton renvoie
  `419 {"message":"CSRF token mismatch."}`. Il faut d'abord
  `GET /sanctum/csrf-cookie/` (204, pose `XSRF-TOKEN` + `romonitor_session`),
  puis envoyer l'en-tête `X-XSRF-TOKEN` avec la valeur du cookie `XSRF-TOKEN`
  **décodée** (Laravel l'URL-encode : `eyJpdiI6…`). Le client fait ce
  handshake tout seul, sans compte.
* **La query string l'emporte sur le corps JSON.** Sur
  `POST /api/v1/stats/game-profile/get/?placeId=107778070777162` avec un
  corps `{"placeId": 1}`, c'est la valeur de la query string qui est
  utilisée et le corps est ignoré (la réponse porte bien le nom
  « Steal An Egg »). Le corps seul fonctionne aussi, mais il est ignoré dès
  qu'un paramètre est présent dans l'URL.
* **C'est `ends`, pas `end`.** La borne haute de la fenêtre de dates est le
  paramètre `ends` ; passer `end` à la place renvoie `422 Unprocessable
  Content`.
* **Noms de champs en camelCase.** `placeId`, `userId`, `communityId`,
  `gameId`, `analytic`, `timeslice`, `badgeId`… et non `place_id`.
* **`/stats/charts/get/` ignore `name`.** L'endpoint renvoie toujours les
  **26** graphiques d'une expérience : la réponse avec `name=zzz-inexistant`
  est **identique octet pour octet** à la réponse sans `name`. `name` n'est
  pas un filtre.
* **`/search/experience-preload/` ignore `term`.** La réponse ne change pas
  selon le terme : `term=steal` et `term=zzz-inexistant-xyz` renvoient les
  **mêmes 30** expériences (le top courant), réponses identiques. La
  recherche réelle passe par l'hôte Meilisearch
  `https://search.romonitorstats.com/indexes/games_index/search` avec une clé
  publique (`Bearer …`) embarquée dans le bundle de la SPA. Le client utilise
  donc ce second hôte pour la commande `search`.
* **Limite de débit : 80 requêtes/minute/IP** (300 pour les graphiques et
  `game-profile`) — confirmé par l'en-tête `x-ratelimit-limit: 80` présent
  sur toutes les réponses. Au-delà → `429` avec `retry-after` et
  `{"message":"Too Many Attempts."}`.
* **La charge utile n'est pas toujours un objet.** `peak` renvoie la chaîne
  JSON `"14313917"`, `genre` la chaîne `"136837926908"` et `total-visits` le
  nombre `1737116457` : ce sont des **scalaires**, pas des dictionnaires.
* **Aucun filtre de client HTTP ici.** Sur `/homepage-data/get/`, les quatre
  configurations testées (avec / sans `impersonate="chrome"`, avec / sans
  `User-Agent`) renvoient toutes `200` et la même réponse (108 155 octets) :
  l'empreinte navigateur utilisée par le client est une convention, pas une
  condition d'accès. (C'est le contraire de `rolimons.com`, voir plus bas.)

### `rolimons.py`

* **L'API est sur `api.rolimons.com`, pas `www.rolimons.com/api`.** Tout le
  namespace `/api/…` sur `www.rolimons.com` est mort : `/api/item/1029025`
  renvoie un `404 text/html`, et aucune négociation `Accept: application/json`
  ni suffixe `.json` ne fonctionne.
* **`impersonate="chrome"` n'est exigé par aucun endpoint.** C'est une
  convention héritée de `rotrend.py` et un choix par défaut raisonnable (il
  positionne notamment un `User-Agent` de navigateur), **pas une condition
  d'accès**. Ce qui compte réellement, c'est de ne pas partir **sans
  `User-Agent` du tout** : `curl_cffi` sans `impersonate` n'en envoie aucun,
  et le WAF de Cloudflare répond alors **403 « Sorry, you have been blocked »**
  (4 546 octets) sur *tous* les endpoints `rolimons.com`. Il suffit d'ajouter
  n'importe quel `User-Agent` — y compris `curl/8.21.0` — pour retrouver
  `200` partout. (Le résultat dépend de l'IP et du point de présence
  Cloudflare : ailleurs, `curl_cffi` sans `impersonate` passe directement.)
* **`/player/<id>` : le `Referer` est exigé quand on imite un navigateur.**
  Avec `impersonate="chrome"` et **sans** `Referer`, Cloudflare répond 403
  `<title>Just a moment...</title>` (5 953 octets) : une empreinte de
  navigateur sans `Referer`, c'est exactement la signature d'un scraper.
  Avec `Referer: https://www.rolimons.com/` → `200` (882 531 octets). **Sans**
  l'empreinte navigateur, `/player/1` répond `200` avec ou sans `Referer`.
  C'est le seul point du site qui déclenche un challenge : `/item/<id>` et
  `/catalog` renvoient `200` dans toutes les configurations. D'où le `referer`
  de `HTML_HEADERS` (rolimons.py, ligne 74).

  Mesure directe (3 échantillons par cellule, statut HTTP identique à chaque fois) :

  | endpoint | `curl_cffi` **sans** UA | `curl_cffi` + UA `curl/8.21.0` | `impersonate="chrome"` sans `Referer` | `impersonate="chrome"` + `Referer` |
  |---|---|---|---|---|
  | `api.rolimons.com/items/v3/itemdetails` | **403** (4 546 o) | 200 (172 499 o) | 200 (172 499 o) | 200 |
  | `www.rolimons.com/item/1029025` | **403** (4 546 o) | 200 (1 674 833 o) | 200 | 200 |
  | `www.rolimons.com/catalog` | **403** (4 546 o) | 200 (772 384 o) | 200 | 200 |
  | `www.rolimons.com/player/1` | **403** (4 546 o) | 200 (882 531 o) | **403 « Just a moment… »** (5 953 o) | 200 (882 531 o) |

  Les deux premières colonnes sont **sans** `impersonate` (donc sans
  `User-Agent` par défaut, sauf la 2ᵉ où on l'ajoute à la main). Les tailles
  exactes dérivent de quelques octets d'un tirage à l'autre (pages vivantes) ;
  seul le code HTTP est stable.
* **Les endpoints de catalogue ignorent `id` / `ids` / `limit` / `gameid`.**
  `items/v3/itemdetails?id=1029025` renvoie **tout** le catalogue (2 415
  assets + 160 bundles) au lieu d'un seul objet — la réponse est identique
  octet pour octet à celle sans paramètre. `games/v1/gamelist?gameid=…`
  renvoie de même les 7 822 jeux. Le filtrage se fait donc **côté client**
  en Python — c'est exactement ce que font `item_search()` et `game_search()`.
* **Les objets arrivent sous forme de tableaux.** `items/v3/itemdetails` donne
  des tableaux de **9 éléments** par objet (asset *et* bundle) ; la variable
  `item_details` de la page `/catalog` donne des **2 575** entrées (clés
  `"1:<assetId>"` / `"2:<bundleId>"`) sous forme de tableaux de **26
  éléments**. Les clients les convertissent en dictionnaires à clés nommées
  (`ITEM_FIELDS`, `CATALOG_FIELDS`).
* **Les données riches sont du JSON embarqué dans le HTML.** L'historique de
  prix, les ventes, les changements de valeur et le journal global (55 938
  entrées sur `/valuechanges`) ne sont pas exposés par l'API JSON : ils
  vivent dans des variables JS inline (`var item_details_data = {…}`,
  `var history_data = {…}`) sur les pages `www.rolimons.com`, et la page
  `/game/<id>` utilise un vrai bloc
  `<script id="game_history_json" type="application/json">`. L'extraction
  se fait par **scan équilibré des accolades** : une regex gloutonne
  sur-capture sur `/itemtable` et `/gametable`.
* **`groupsearch` : 20 requêtes / 60 s** — la plus stricte (en-tête
  `x-ratelimit-limit: 20` observé), contre `1100` pour `playersearch` et
  `1600` pour `playerassets`. Un dépassement donne
  `429 {"success":false,"code":6,"message":"You are sending requests too
  fast"}`, et ~40 requêtes de recherche rapprochées dégénèrent en blocage
  Cloudflare **1015** (~90 s) sur *toutes* les requêtes vers
  `api.rolimons.com`. Le client espace les appels (`_pace()`) et met en
  cache 60 s les endpoints statiques.

### Les deux scripts (et `rotrend.py`)

* **La console Windows est en cp1252.** Les noms de jeux et d'objets
  contiennent des emoji (`Brookhaven 🏡RP`, `PIGU 🔴`) : un simple `print()`
  lève `UnicodeEncodeError` sur un terminal cp1252. D'où le garde-fou en tête
  de chaque script :
  `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`. Le
  vérificateur a exactement le même problème (son tableau ASCII-art) : il
  applique le même garde-fou et force `PYTHONIOENCODING=utf-8` dans les
  sous-processus. En PowerShell, préférer `chcp 65001` ou
  `$env:PYTHONIOENCODING="utf-8"`.

---

## 5. Vérificateur

`verify_clients.py` rejoue **toutes** les commandes des deux clients dans un
sous-processus et vérifie trois choses par commande : code de sortie `0`,
présence d'une charge utile JSON analysable, et charge utile non vide.
Cela fait **49 contrôles** : 23 commandes `romonitorstats.py` + 24 commandes
`rolimons.py` + le bloc d'usage de chaque script. `rotrend.py` n'y est pas
inclus : sa commande `ccu` sort un rapport **texte**, pas du JSON.

```bash
py verify_clients.py
```

La liste des commandes n'est pas codée en dur : elle est lue dans le bloc
`if __name__ == "__main__":` de chaque script, et le nombre d'arguments
positionnels attendus par chaque branche est déduit du même source (les
helpers `_arg` / `_int_arg` / `_text_arg` sont relus pour savoir à quelle
position se trouve l'index `argv`). Options utiles :

```bash
py verify_clients.py --list              # commandes détectées
py verify_clients.py --only rolimons     # un seul script
py verify_clients.py --cmd chart         # une seule commande
py verify_clients.py --verbose           # extrait de stdout dans le tableau
```

Le code de sortie est `1` si au moins une commande échoue, `0` sinon.

---

## 6. Éthique et limites de débit

Ces trois clients n'interrogent que des **endpoints publics et en lecture
seule**. Ils ne contournent aucune authentification : le seul « contournement »
est le handshake CSRF Laravel, qui est exactement le mécanisme prévu par le
site pour ses propres appels navigateur — il ne donne aucun accès
supplémentaire, il permet simplement d'utiliser les endpoints POST publics
depuis un script.

Les quotas existent et sont agresifs sur certains endpoints :

| API | Limite | Comportement en dépassement |
|---|---|---|
| `api.rolimons.com` — `groups/v1/groupsearch` | **20 req / 60 s** | `429 code 6`, puis blocage Cloudflare **1015** (~90 s) sur tout l'hôte |
| `api.rolimons.com` — `players/v1/playersearch` | 1 100 req / ~31 h | `429 code 6` |
| `api.rolimons.com` — `players/v1/playerassets/<id>` | 1 600 req / ~6,8 h | `429 code 6` |
| `www.rolimons.com` (pages HTML) | 900 req / ~54 min | `429` |
| `romonitorstats.com/api/v1` | **80 req / min** (300 sur les graphiques) | `429` + `retry-after` |

Les quotas sont annoncés par les en-têtes `x-ratelimit-limit` /
`x-ratelimit-remaining` / `x-ratelimit-reset` : lisez-les plutôt que de
deviner.

En pratique : espacez les appels (le client espace déjà les recherches et
met en cache 60 s les endpoints statiques), respectez les `Retry-After`, et
n'utilisez pas ces clients pour du trafic de production. Les données
affichées appartiennent à RoMonitor Stats et à Rolimons : citez-les, ne les
revendiquez pas.

---

## 7. Installation

```bash
pip install curl_cffi
```

`curl_cffi` est utilisé partout avec `impersonate="chrome"` : c'est la
convention de la maison (`rotrend.py` fait de même) et un choix par défaut
raisonnable — il pose un `User-Agent` de navigateur, ce qui suffit à passer
le WAF de Cloudflare sur `rolimons.com` (§ 4). Ce n'est **pas** une
obligation de l'API : aucun endpoint n'exige cette empreinte (voir § 4 pour
la matrice de mesure et pour le seul cas où elle devient un handicap,
`/player/<id>` sans `Referer`).
