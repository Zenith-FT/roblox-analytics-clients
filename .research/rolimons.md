# Rolimons HTTP API — Reverse-Engineering Notes

**Target:** `https://www.rolimons.com/` (Rolimons — Roblox Limited/Ultimate item value tracker)
**Research date:** 2026-10-21
**Method:** every claim below is backed by an actual request (curl / python urllib) made during this session.

---

## 0. Executive summary

* There is **NO** `/api/...` path on `www.rolimons.com`. `https://www.rolimons.com/api/item/1029025` → **404** (`text/html`).
* The real JSON API lives on a **separate host: `https://api.rolimons.com`**, path shape `/{namespace}/v{N}/{action}`.
  It was discovered by grepping the site's own JS bundles (`/js/search12.js`, `/js/player22.js`, `/js/deals5.js`, …) for `api.rolimons.com`.
* A second API host exists: **`https://thumbnails.rolimons.com`** (player avatars).
* **No authentication, no API key, no Cloudflare challenge** for any GET endpoint. Plain `curl` with no
  `User-Agent` at all works.
* All "rich" per-item / per-game / per-player data (price history, sales, copies, value changes, chart
  series) is **not** exposed via the JSON API — it is **server-rendered into the HTML pages** as inline
  JavaScript variables (`var item_details_data = {...}`) or a `<script type="application/json">` block.
* **Rate limits** exist and are **per-endpoint**, advertised via `X-RateLimit-*` headers. The search
  endpoints (`playersearch`, `groupsearch`) are the strictest: **20 requests / ~60 s window**.

---

## 1. Working endpoints

All responses are `application/json; charset=utf-8` unless noted.

### 1.1 `api.rolimons.com` — read-only, no auth

| # | METHOD | Full URL | Required params | Auth | Rate limit (observed) | Sample response shape (trimmed) |
|---|--------|----------|-----------------|------|----------------------|--------------------------------|
| 1 | GET | `https://api.rolimons.com/items/v3/itemdetails` | none | **No** | none (CF-cached, `cache-control: public, max-age=60`) | `{"success":true,"asset_count":2415,"bundle_count":160,"item_count":2575,"assets":{"1029025":["The Classic ROBLOX Fedora","CF",412613,450000,450000,4,2,-1,-1]},"bundles":{"939596":["The Jade Catseye","",19868,-1,19868,-1,-1,-1,-1]}}` |
| 2 | GET | `https://api.rolimons.com/items/v2/itemdetails` | none | **No** | none | `{"success":true,"item_count":2573,"items":{"1029025":[...9 elems...]}}` (older: flat `items` map, 10 elems) |
| 3 | GET | `https://api.rolimons.com/items/v1/itemdetails` | none | **No** | none | `{"success":true,"item_count":2514,"items":{...}}` (oldest, 10 elems) |
| 4 | GET | `https://api.rolimons.com/itemthumbs/v2/thumbssm` | none | **No** | none | `{"success":true,"asset_count":2415,"bundle_count":160,"item_count":2575,"assets":{"1029025":"https://tr.rbxcdn.com/.../110/110/Hat/Webp/noFilter"},"bundles":{...}}` |
| 5 | GET | `https://api.rolimons.com/itemthumbs/v1/thumbssm` | none | **No** | none | `{"success":true,"item_count":2573,"items":{"1029025":"https://tr.rbxcdn.com/..."}}` |
| 6 | GET | `https://api.rolimons.com/games/v1/gamelist` | none | **No** | none | `{"success":true,"game_count":7822,"games":{"1818":["Crossroads",28,"https://tr.rbxcdn.com/.../150/150/Image/Webp/noFilter"]}}` |
| 7 | GET | `https://api.rolimons.com/market/v2/saleactivity` | none | **No** | none | `{"success":true,"activities":[[1792604888,110673146052704,1,10119,10173,8711490], ...]}` |
| 8 | GET | `https://api.rolimons.com/market/v1/saleactivity` | none | **No** | none | same but 5-element tuples (no `item_type`) |
| 9 | GET | `https://api.rolimons.com/market/v2/dealactivity` | none | **No** | none | `{"success":true,"activities":[[1792604919,0,20945145,1,33017], ...]}` |
| 10 | GET | `https://api.rolimons.com/market/v1/dealactivity` | none | **No** | none | same shape as v2 |
| 11 | GET | `https://api.rolimons.com/tradeads/v1/getrecentads` | none | **No** | none | `{"success":true,"trade_ad_count":319,"trade_ads":[[99463740,1792604936,80440709,"tacotruck20004",{"items":[1082932,1241182524,67996263,25535420]},{"items":[1080949],"tags":[5,6]}], ...]}` |
| 12 | GET | `https://api.rolimons.com/players/v1/playersearch` | **`searchstring`** | **No** | `X-RateLimit-Limit: 1100`, long window (~31 h) | `{"success":true,"result_count":15,"players":[[156,"builderman"],[66519,"Builderman0"], ...]}` |
| 13 | GET | `https://api.rolimons.com/players/v1/playerassets/<userId>` | path param | **No** | `X-RateLimit-Limit: 1600`, window ~6.8 h | `{"success":true,"playerTerminated":false,"playerPrivacyEnabled":false,"playerVerified":false,"playerId":1,"chartNominalScanTime":1792540800,"playerAssets":{"1029025":[30169,8835350], ...},"isOnline":false,"presenceType":0,"lastOnline":null,"lastLocation":"Website","lastPlaceId":null,"locationGameIsTracked":false,"premium":true,"badges":{...},"holds":[]}` |
| 14 | GET | `https://api.rolimons.com/groups/v1/groupsearch` | **`searchstring`** | **No** | `X-RateLimit-Limit: 20`, ~60 s window | `{"success":true,"result_count":30,"groups":[[36001589,"Admin Abuse Games",1748793607,1,0,1735,"https://tr.rbxcdn.com/.../150/150/Image/Webp/noFilter"], ...]}` |
| 15 | POST | `https://api.rolimons.com/auth/v1/logout` | — | cookie (no-op) | — | `{"success":true}` (GET on this path → 404) |

### 1.2 `thumbnails.rolimons.com`

| # | METHOD | Full URL | Required params | Auth | Sample response |
|---|--------|----------|-----------------|------|-----------------|
| 16 | GET | `https://thumbnails.rolimons.com/avatar` | **`userIds`** (comma-sep, ≤99), `size` (`150x150`/`420x420`) | **No** | `{"success":true,"thumbnails":{"1":{"state":"Completed","url":"https://tr.rbxcdn.com/30DAY-Avatar-...-Png/150/150/Avatar/Webp/noFilter"}}}` |
| 17 | GET | `https://thumbnails.rolimons.com/avatarbust` | same | **No** | same, `.../AvatarBust/Webp/noFilter` |

> Wrong param name → `400 {"success":false,"code":1,"message":"Missing 'userIds' parameter"}`

### 1.3 Endpoints that REQUIRE auth (not usable by third parties)

| METHOD | Full URL | Result |
|--------|----------|--------|
| POST | `https://api.rolimons.com/players/v1/addplayerbyname` | `401 {"success":false,"code":4,"message":"Missing verification cookie"}` |
| POST | `https://api.rolimons.com/tradeads/v1/removead/<adId>` | `401 {"success":false,"code":4,"message":"Missing verification cookie"}` |

The required cookie is **`_RoliVerification`** (signed token). Sending a bogus value changes the error to
`"Invalid verification token format or signature"`. The cookie is **never** set by `www.rolimons.com`
(no `Set-Cookie` on `/`, `/verify`, `/players`, `/leaderboard`, `/trades`, or any API GET), so it cannot be
obtained by an anonymous client. → **Treat these two endpoints as unusable.**

### 1.4 HTML pages on `www.rolimons.com` that carry the data you actually want

These are the real "API" for per-item / per-game / per-player detail. All are `200 text/html`, all embed
JSON (see §4). Rate limit header on the HTML host: `X-RateLimit-Limit: 900`.

| Path pattern | Embedded variable(s) | Notes |
|--------------|----------------------|-------|
| `/item/<assetId>` | `item_details_data`, `history_data`, `sales_data`, `ownership_data`, `all_copies_data`, `bc_copies_data`, `hoards_data`, `value_changes` | `item_details_data` is **named-key JSON** — best option for a client |
| `/bundle/<bundleId>` | `bundle_details_data` (+ same history vars) | same shape as item page |
| `/game/<gameId>` | `<script id="game_history_json" type="application/json">` + JSON-LD | chart series: `timestamps, players, avg_playtime, visits, upvotes, downvotes, favorites` |
| `/player/<userId>` | `player_details_data`, `chart_data`, `item_list`, `scanned_player_assets`, `player_ugc_assets_raw` | |
| `/catalog`, `/itemtable`, `/deals`, `/projecteditems`, `/tradecalculator` | `item_details` (2575 items, 26-element arrays) | richest full-catalog dump |
| `/valuechanges` | `item_details` + `value_changes` (55 938 rows) | global value-change log |
| `/trades`, `/itemtrades/<id>` | `item_details` + `trade_ads` (2000 rows) | |
| `/itemsales/<id>`, `/bundlesales/<id>` | `item_sales` | `num_points, timestamp_list, sale_id_list, sale_price_list, sale_rap_list, sale_value_list` |
| `/games` | `games` (7822 games, **object** values) | `{name, genre, icon_url, players, visits, upvotes, downvotes, favorites}` |
| `/gametable` | `game_details` (7822 games, array values) | `[name, genre, icon_url, players, visits, upvotes, downvotes, favorites, ...]` |
| `/marketactivity` | `initial_activity` (50 rows) | |
| `/leaks` | `leaks` (2169 rows) | |
| `/promotionrates` | `promotion_rate_history_data`, `latest_promotion_rates` | CPI rates |

Also confirmed working (HTML, no embedded JSON of note): `/leaderboard`, `/rolibadges`, `/requestgame`,
`/discordbots`, `/preferences`, `/about`, `/groups`, `/players`, `/trades`, `/valuechanges`,
`/article/<slug>` (e.g. `/article/is-roblox-plus-actually-worth-it` → 200).

**Not found (404):** `/bundle/1`, `/item/939596` (a bundle id is *not* an asset id), `/item/999999999999`,
`/game/1`, `/player/0`.

---

## 2. Tuple / field semantics (decoded from the site's own JS)

### 2.1 `items/v3/itemdetails` → `assets["<assetId>"]` / `bundles["<bundleId>"]` — 9-element array

| idx | meaning | example (`1029025`) |
|-----|---------|---------------------|
| 0 | name | `"The Classic ROBLOX Fedora"` |
| 1 | acronym (`""` if none) | `"CF"` |
| 2 | RAP (recent average price) | `412613` |
| 3 | **value** (`-1` = unassigned) | `450000` |
| 4 | default value | `450000` |
| 5 | demand (`0` Terrible … `4` Amazing, `-1` unassigned) | `4` |
| 6 | trend (`0` Lowering, `1` Unstable, `2` Stable, `3` Raising, `4` Fluctuating, `-1` unassigned) | `2` |
| 7 | projected (`1` = projected) | `-1` |
| 8 | rare (`1` = rare) | `-1` |

*(Verified by cross-referencing `api.rolimons.com/items/v3/itemdetails` against the `/catalog` embedded
array and against `item_details_data` on `/item/1029025`.)*

### 2.2 `/catalog` embedded `item_details` — 26-element array, keyed `"1:<assetId>"` / `"2:<bundleId>"`

| idx | meaning | idx | meaning |
|-----|---------|-----|---------|
| 0 | name | 13 | bc_copies |
| 1 | `"asset:<assetTypeId>"` / `"bundle:<bundleTypeId>"` | 14 | hoarded_copies |
| 2 | original_price | 15 | acronym |
| 3 | created (unix) | 16 | **value** (null = unassigned) |
| 4 | first_timestamp (unix) | 17 | demand (0–4) |
| 5 | best_price | 18 | trend (0–4) |
| 6 | favorited | 19 | projected flag |
| 7 | num_sellers | 20 | hyped flag |
| 8 | rap | 21 | rare flag |
| 9 | owners | 22 | default_value |
| 10 | bc_owners | 23 | thumbnail_url_sm |
| 11 | copies | 24 | item_type (`1` asset, `2` bundle) |
| 12 | deleted_copies | 25 | id |

### 2.3 Activity tuples

* `market/v2/saleactivity` → `activities: [[timestamp, item_id, item_type, old_rap, rap, sale_id], ...]`
  *(from `/js/marketactivity5.js`: `[0]=timestamp, [1]=item_id, [2]=item_type, [3]=old_rap, [4]=rap, [5]=sale_id`)*
* `market/v2/dealactivity` → `activities: [[timestamp, activity_type, item_id, item_type, price], ...]`
  *(from `/js/deals5.js`: `[3]:[2]` form the `item_type:item_id` lookup key)*
* `tradeads/v1/getrecentads` → `trade_ads: [[ad_id, timestamp, owner_id, owner_name, {items:[ids]}, {items:[ids], tags:[ids]}], ...]`
* `/valuechanges` embedded `value_changes` → `[[timestamp, item_id, item_type, changed_field, old_value, new_value], ...]`
* `/item/<id>` embedded `value_changes` → `[[timestamp, change_type, old_value, new_value], ...]`
  where `change_type`: `1` = value change, `2` = demand change, `3` = trend change.
* `/deals` embedded `item_activity` → `{"<item_type>:<item_id>": [name, last_activity_ts, best_price, rap, activity_type, item_id]}`

### 2.4 `item_details_data` (on `/item/<id>`) — named keys, 28 of them

`item_id, item_name, description, asset_type_id, original_price, created, first_timestamp, best_price,
favorited, num_sellers, rap, owners, bc_owners, copies, deleted_copies, bc_copies, hoarded_copies,
acronym, valuation_method, value, demand, trend, projected, hyped, rare, thumbnail_url_lg, limited_type,
migrated_to_bundle_id`

`bundle_details_data` (on `/bundle/<id>`) has the same keys with `bundle_id, bundle_name, bundle_type_id,
migrated_from_asset_id` instead of the asset-specific ones.

### 2.5 `playersearch` / `groupsearch` tuples

* `playersearch` → `players: [[user_id, username], ...]`
* `groupsearch` → `groups: [[group_id, name, created_unix, is_locked?, flag, member_count, icon_url], ...]`

---

## 3. HOW TO CALL

### 3.1 JSON API (no auth, no headers required)

```bash
# Full item universe: name, acronym, rap, value, default_value, demand, trend, projected, rare
curl.exe -s "https://api.rolimons.com/items/v3/itemdetails"

# Item thumbnails (110x110 webp URLs)
curl.exe -s "https://api.rolimons.com/itemthumbs/v2/thumbssm"

# Game list (name, players, icon) for all 7822 games
curl.exe -s "https://api.rolimons.com/games/v1/gamelist"

# Player search  (REQUIRED param: searchstring)
curl.exe -s "https://api.rolimons.com/players/v1/playersearch?searchstring=builderman"

# Player's owned assets  (path param = Roblox user id)
curl.exe -s "https://api.rolimons.com/players/v1/playerassets/1"

# Group search  (REQUIRED param: searchstring)
curl.exe -s "https://api.rolimons.com/groups/v1/groupsearch?searchstring=admin"

# Live sale / deal activity feeds
curl.exe -s "https://api.rolimons.com/market/v2/saleactivity"
curl.exe -s "https://api.rolimons.com/market/v2/dealactivity"

# Recent trade ads
curl.exe -s "https://api.rolimons.com/tradeads/v1/getrecentads"

# Player avatar thumbnails (REQUIRED param: userIds, comma separated, max 99)
curl.exe -s "https://thumbnails.rolimons.com/avatar?userIds=1,2,3&size=150x150"
curl.exe -s "https://thumbnails.rolimons.com/avatarbust?userIds=1,2&size=420x420"
```

### 3.2 HTML pages + embedded JSON

```bash
# Per-item detail (named JSON)
curl.exe -s "https://www.rolimons.com/item/1029025"

# Per-bundle detail
curl.exe -s "https://www.rolimons.com/bundle/939596"

# Per-game chart history
curl.exe -s "https://www.rolimons.com/game/1537690962"

# Per-player
curl.exe -s "https://www.rolimons.com/player/1"

# Full catalog dump (2575 items, 26-element arrays)
curl.exe -s "https://www.rolimons.com/catalog"

# Global value-change log
curl.exe -s "https://www.rolimons.com/valuechanges"

# Trade ads
curl.exe -s "https://www.rolimons.com/trades"

# Item sale history
curl.exe -s "https://www.rolimons.com/itemsales/1029025"

# Games with genre/visits/upvotes
curl.exe -s "https://www.rolimons.com/games"
```

### 3.3 Extraction helper (JS) — balanced-brace scan, verified working

```js
// Returns the parsed JSON of `var <name> = {...}` inside the page HTML.
function extractJsonVar(html, name) {
  const re = new RegExp(`var\\s+${name}\\s*=\\s*`);
  const m = re.exec(html);
  if (!m) return null;
  let s = m.index + m[0].length;
  while (s < html.length && /\s/.test(html[s])) s++;
  const open = html[s], close = open === '{' ? '}' : ']';
  let depth = 0, inStr = false, esc = false;
  for (let i = s; i < html.length; i++) {
    const c = html[i];
    if (inStr) { if (esc) esc = false; else if (c === '\\') esc = true; else if (c === '"') inStr = false; continue; }
    if (c === '"') { inStr = true; continue; }
    if (c === open) depth++;
    else if (c === close) { depth--; if (depth === 0) return JSON.parse(html.slice(s, i + 1)); }
  }
  return null;
}

const html = await (await fetch('https://www.rolimons.com/item/1029025')).text();
const item = extractJsonVar(html, 'item_details_data');   // named-key JSON
const hist = extractJsonVar(html, 'history_data');         // {timestamp[], rap[], best_price[], favorited[], num_sellers[]}
const sales = extractJsonVar(html, 'sales_data');          // {timestamp[], avg_daily_sales_price[], sales_volume[]}

// game page uses a real JSON script tag instead:
const g = await (await fetch('https://www.rolimons.com/game/1537690962')).text();
const gameHistory = JSON.parse(
  /<script id="game_history_json" type="application\/json">([\s\S]*?)<\/script>/.exec(g)[1]
);
```

Verified: this extractor resolved **34/34** (page, variable) pairs with zero failures.

---

## 4. Embedded-JSON extraction notes

* **There is NO `window.__INITIAL_STATE__` / `__NEXT_DATA__`.** The site is server-rendered Jinja + vanilla
  jQuery. The only `window.*` assignments in the HTML are `window.dataLayer` (GTM) and `window.nitroAds` (ads).
* Data lives in **inline `<script>` blocks as `var <name> = <JSON>;`**. There is no `type="application/json"`
  on item/bundle/player pages — but the **game page does use one**:
  `<script id="game_history_json" type="application/json">{...}</script>`
* Regex that works for a **single-line** assignment (JSON is always on one line):
  `var\s+<NAME>\s*=\s*(\{.*\});` — **without** the `s`/DOTALL flag.
  ⚠️ A greedy `.*` over-captures on `/itemtable` and `/gametable` because the JSON is followed by
  `</script><script>...` on the same line. Use the balanced-brace scanner (above) everywhere.
* JSON-LD is present on the game page (`<script type="application/ld+json">`) but only contains
  `@context/@type/url/name/image/primaryImageOfPage` — not useful for stats.

---

## 5. Rate limits, blocking, headers

### 5.1 No blocking on GET
* Plain `curl` with **no** `User-Agent`, with `curl/8.0.1`, and with a Chrome UA → all **200**.
* No Cloudflare interstitial, no challenge, no API key, no `Authorization` header.
* `Origin`/`Referer` are **not** required. (CORS *response* headers do lock the browser origin to
  `https://www.rolimons.com`: `Access-Control-Allow-Origin: https://www.rolimons.com`,
  `Access-Control-Allow-Credentials: true`, `Access-Control-Allow-Methods: GET, POST, OPTIONS, DELETE`.
  This only affects browser clients, not server-side ones.)
* Static endpoints are Cloudflare-cached: `cache-control: public, max-age=60`, plus an `ETag`.

### 5.2 Rate limits (headers observed on 200 responses)

| Endpoint class | `X-RateLimit-Limit` | Window (measured `X-RateLimit-Reset - now`) | Behaviour on exceed |
|---|---|---|---|
| `groups/v1/groupsearch` | **20** | ~60 s | `429 {"success":false,"code":6,"message":"You are sending requests too fast"}` + `Retry-After: 14` |
| `players/v1/playersearch` | 1100 | ~31 h | same 429 shape |
| `players/v1/playerassets/<id>` | 1600 | ~6.8 h | — |
| `www.rolimons.com/item/<id>` (HTML) | 900 | ~54 min observed | — |
| static JSON (`itemdetails`, `thumbssm`, `gamelist`, `saleactivity`, `dealactivity`, `getrecentads`) | *no headers* | — | 30 rapid calls → 30×200, no 429 |

**Cloudflare 1015 (hard block)**: after ~40 rapid search requests from one IP the response becomes
`429 {"type":"https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1015/", ...}`
and *all* requests to `api.rolimons.com` fail until the CF window rolls over (observed recovery after
~90 s of idling). → **Be conservative: ≤1 search request per 3–4 s, and cache aggressively.**

### 5.3 Error body formats (exact, observed)

| Status | Body |
|---|---|
| 404 | `{"success":false,"code":3,"message":"Not found"}` |
| 400 (missing param) | `{"success":false,"code":1,"message":"Missing 'searchstring' parameter"}` |
| 400 (bad path param) | `{"success":false,"code":1,"message":"Invalid player id"}` |
| 401 (no verification cookie) | `{"success":false,"code":4,"message":"Missing verification cookie"}` |
| 401 (bad verification cookie) | `{"success":false,"code":4,"message":"Invalid verification token format or signature"}` |
| 429 (app rate limit) | `{"success":false,"code":6,"message":"You are sending requests too fast"}` |
| 429 (Cloudflare) | `{"type":"https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1015/","title":"You are being rate limited","status":403,...}` |

---

## 6. Dead / blocked paths — do NOT re-test

### 6.1 `www.rolimons.com/api/...` — the whole namespace is dead
`/api/item/1029025`, `/api/game/1537690962`, `/api/search?q=hat`, `/api/item.json` → **404** (HTML error page).
No `Accept: application/json` negotiation, no `?format=json`, no `.json` suffix on any HTML route —
`/item/1029025` with `Accept: application/json` still returns `text/html`.

### 6.2 `api.rolimons.com` paths that returned 404 (`code 3`)
`/api/item/1029025` · `/items/v3/item` · `/items/v2/item` · `/items/v3/items` · `/items/v3/itemdetails/1029025`
· `/items/v2/itemdetails/1029025` · `/item/v1/itemdetails` · `/games/v1/gamedetails` · `/games/v2/gamedetails`
· `/games/v1/game` · `/games/v2/gamelist` · `/games/v1/gamesearch` · `/trades/v1/trades` · `/groups/v1/group`
· `/players/v2/playerassets/1` · `/players/v1/playerprofile` · `/players/v1/playerinfo` · `/` · `/v1/`

A systematic sweep of `/{items,itemthumbs,games,players,groups,market,tradeads,trades,auth,values,
valuechanges,leaks,deals,badges,leaderboard,promotionrates,projects,catalog,charts,history,stats,news,
articles,discordbots}/{v1,v2,v3}/{30 candidate names}` produced **no additional 200 endpoints** beyond the
15 listed above — the API surface is exactly what the JS bundles reference.

### 6.3 Query params that are silently IGNORED (not real filters)
* `items/v3/itemdetails?id=1029025` and `?ids=1029025,1028720` → **returns the whole catalogue** (2415
  assets / 160 bundles). There is **no per-item filter**.
* `games/v1/gamelist?gameid=1537690962` → returns all 7822 games.
* `tradeads/v1/getrecentads?limit=5` → returns ~300–320 ads regardless.
* `market/v2/saleactivity?limit=5` → returns the fixed-size feed (~50 rows).
* `groups/v1/groupsearch` with **no** `searchstring` → returns 30 generic groups instead of erroring.
* `players/v1/playerassets?playerid=1` → `{"success":false,"code":1,"message":"Invalid player id"}`
  (the id must be a **path** segment).

### 6.4 Other
* `https://www.rolimons.com/bundle/1` → 404; `https://www.rolimons.com/item/939596` → 404
  (bundle ids are only served under `/bundle/<id>`; asset ids only under `/item/<id>`).
* `https://www.rolimons.com/game/1` → 404; `https://www.rolimons.com/player/0` → 404.
* `https://www.rolimons.com/article/<slug>` → **200** for real slugs (e.g.
  `/article/is-roblox-plus-actually-worth-it`, `/article/roblox-trading-terms-guide`). The earlier 404 was
  caused by a *truncated* slug (`.../article/rolimons-value-changing-system-how-does-`) that I had cut off
  mid-string, not a dead route. Articles contain no embedded JSON of interest.
* `https://thumbnails.rolimons.com/avatar?userId=1` → 400 `Missing 'userIds' parameter`
  (param is `userIds`, plural, comma-separated).
* `GET https://api.rolimons.com/auth/v1/logout` → 404 (must be `POST`).
* `robots.txt` **disallows** `/shop` and `/history/` for `*`; `/uaid/` for Yandex & Pinterestbot.
  `sitemap.xml` lists only the 25 top-level routes (no `/item/…`, `/game/…`, `/player/…`).

---

## 7. Other hosts referenced by the site's JS

| Host | Purpose | Auth |
|------|---------|------|
| `api.rolimons.com` | JSON API | none (GET) / `_RoliVerification` cookie (POST) |
| `thumbnails.rolimons.com` | avatar/avatarbust proxy | none |
| `tr.rbxcdn.com` | Roblox CDN (thumbnails/images) | none |
| `s.nitropay.com`, `www.googletagmanager.com` | ads / analytics | — |

No other API host exists. `www.roblox.com` appears only as a link target.

---

## 8. Recommended client design (derived from the above)

1. **Item metadata for everything** → one call to `https://api.rolimons.com/items/v3/itemdetails`
   (172 KB) + `https://api.rolimons.com/itemthumbs/v2/thumbssm` (275 KB). Both are CF-cached, no rate
   limit observed; cache them for minutes, not seconds.
2. **Per-item deep data** (history/sales/copies/holders) → fetch `https://www.rolimons.com/item/<id>` and
   run the balanced-brace extractor over `item_details_data`, `history_data`, `sales_data`,
   `ownership_data`, `value_changes`.
3. **Item search by name** → the API has no item-search endpoint; download `itemdetails` once and filter
   client-side (the site's own search box does exactly this — see `/js/search12.js`).
4. **Player lookup** → `playersearch?searchstring=` (≤1 req / 3 s), then `playerassets/<userId>`.
5. **Game stats** → `api.rolimons.com/games/v1/gamelist` for names/players/icons; scrape
   `https://www.rolimons.com/games` for the richer object (`visits`, `upvotes`, `downvotes`, `favorites`,
   `genre`) — or `/game/<id>` for the full history series.
6. **Rate-limit hygiene** → exponential backoff on 429, honour `Retry-After`, and treat a CF 1015 body as
   a hard stop for ~60–120 s.
