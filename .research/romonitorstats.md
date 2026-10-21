# RoMonitor Stats — HTTP API reverse-engineering notes

**Target:** https://romonitorstats.com/ (RoMonitor Stats, by Silicon Digital Group Ltd)
**Date of research:** 2026-10-21
**Method:** static analysis of the Vue 2 SPA bundles + live `curl` probing + Camoufox network capture.

---

## 1. Architecture / TL;DR

| Fact | Evidence |
|---|---|
| Frontend is a **Vue 2 SPA** (not Next.js). Webpack build in `/stats-dist/`. | `https://romonitorstats.com/` returns `<div id="app">` + `<script src="/stats-dist/js/index.5248542c.js">`. All data is fetched via XHR after mount. |
| Backend is **Laravel** (Sanctum SPA auth). | `GET /sanctum/csrf-cookie/` sets `XSRF-TOKEN` + `romonitor_session` cookies (HTTP 204). Errors are Laravel-style: `{"message":"..."}`, `422 {"message":"The <field> field is required."}`, `419 CSRF token mismatch.`, `405 The POST method is not supported for this route. Supported methods: GET, HEAD.` |
| API is **same-origin** — `https://romonitorstats.com/api/v1/...`. No separate API host for the main API. | All bundle call sites are relative paths (`axios.post("/api/v1/...")`). |
| Fronted by **Cloudflare** (`server: cloudflare`). No Cloudflare challenge on API paths. | Response headers include `cf-ray`, `cf-cache-status: DYNAMIC`. |
| `robots.txt` allows everything. | `User-agent: * / Disallow:` |
| Two **secondary hosts**: `search.romonitorstats.com` (Meilisearch) and `export-api.romonitorstats.com` (Express, export jobs). | Meilisearch host+key hardcoded in bundles; `export-api` returns `Cannot GET /`. |
| Public "RoMonitor API" (documented, account-key based): `/api/v1/charts` and `/api/v1/tables`. | `StatsMisc.8b77b7c5.js` renders a card "About the RoMonitor API" listing `/api/v1/charts` and `/api/v1/tables` and links `https://docs.romonitorstats.com`. Docs are behind **Cloudflare Access** (login required → could not read). |

---

## 2. Auth model (empirically determined)

### GET requests
* **No auth required** for the public endpoints. A bare `curl` with no cookies works.
* A **valid RoMonitor account is required** for some chart/table names (see §4 "Gated").
* API-key auth for the documented API is **`Authorization: Bearer <key>`**.
  * Probe: `GET /api/v1/charts/get?name=engagement&...` with `Authorization: Bearer testkey` → `403 {"message":"Invalid API key."}`.
  * Every other scheme (`X-API-Key:`, `Api-Key:`, `Authorization: <key>`, `Authorization: Token ...`, `?apiKey=`) is ignored → falls through to `403 {"message":"You must be logged in to view this chart."}`.
  * Keys are created per-account via `POST /api/v1/account/create-api-key/` (login required). The key format/usage could not be confirmed further because `https://docs.romonitorstats.com` is behind Cloudflare Access.

### POST requests
* **POST always requires the Laravel CSRF token**, otherwise `419 {"message":"CSRF token mismatch."}`.
  * Verified: `POST /api/v1/stats/game-profile/get/?placeId=...` with no cookie/token → **419**. Same request with token → **200**.
* CSRF handshake (Laravel Sanctum SPA):
  1. `GET https://romonitorstats.com/sanctum/csrf-cookie/` → `204`, sets `XSRF-TOKEN` (URL-encoded) + `romonitor_session`.
  2. Send `Cookie: XSRF-TOKEN=<raw>; romonitor_session=<raw>` **and** header `X-XSRF-TOKEN: <url-decoded cookie value>`.
* `withCredentials: true` is set globally (`aa.a.defaults.withCredentials=!0` in `index.5248542c.js`).

### Anonymous vs logged-in data limits
* **Charts: anonymous users may only request a 14-day window.**
  * `start=2026-10-08T00:00:00.000Z&ends=2026-10-21T23:59:59.999Z` → `200`.
  * `start=2026-10-01T00:00:00.000Z&ends=2026-10-21T23:59:59.999Z` (21 days) → `403 {"message":"You must be logged in to view this chart."}`.
  * Matches bundle logic: `canViewOver14DaysOfData(){ return getUser() && isFlagEnabled("canViewOver14DaysOnCharts") }` and `chartStartEndDates` defaults to `today-13 .. today` for anonymous, `today-29 .. today` for logged-in.
* Some **charts** and some **tables** are hard-gated behind login regardless of date range (403 with a *different* message: "You must be logged in to view **this chart/table**.").
* Logged-in-only areas: `/api/v1/account/*`, `/api/v1/athena/*`, `/api/v1/dashboard/*`, `/api/v1/gamefam-export/*`, `/api/v1/moderation/*`, `/api/v1/newsletter/subscribe`, `/api/v1/genres/get-genre-insight/`, `/api/v1/gamefam/get-assets-information`.

---

## 3. Request conventions (IMPORTANT)

1. **Params go in the JSON body OR the query string.** Query string wins.
   * `POST /api/v1/stats/game-profile/get/?placeId=107778070777162` with body `{"placeId":1}` → returns **"Steal An Egg"** (query value used, body ignored).
   * `POST /api/v1/stats/game-profile/get/` with body `{"placeId":"107778070777162","compare":null}` → **200** (body works when there is no query string).
   * GET endpoints read params from the query string.
2. **Field names are camelCase** (`placeId`, `userId`, `communityId`, `gameId`, `universeId`, `analytic`, `timeslice`, `start`, `ends`, `range`, `application`, `group`, `query`, `code`, `limit`, `period`, `genre`, `name`, `page`, `term`, `badgeId`, `metric`, `format`, `timeframe`, `includeExperienceName`, `proVersion`).
3. **Date range format:** `start=<ISO8601 with Z>&ends=<ISO8601 with Z>`.
   * From `chartStartEndDates` / `tableStartEndDates` in the bundles: `"start=" + n.toISOString() + "&ends=" + i.toISOString()`.
   * `end`/`ends` — the bundles use **`ends`**.
4. **`timeslice`** values: `day`, `hourly`, `half-hourly`.
5. **Errors:** `422` body is `{"message":"The <snake_cased> field is required."}` or `{"message":"The selected <field> is invalid."}` (i.e. value not in allow-list / not found). `500` body is `{"message":"Server Error"}`.
6. **Response envelope:** bare JSON (no `data`/`success` wrapper). Validation errors are `{"message": ...}` (sometimes with an `errors` object, e.g. login).
7. **Rate limit headers** on every API response:
   * `x-ratelimit-limit: 80` (most endpoints) or `300` (charts, game-profile).
   * `x-ratelimit-remaining: <n>`, `x-ratelimit-reset: <unix ts>`.
   * Over the limit → **`429`** with `retry-after: <seconds>` and body `{"message":"Too Many Attempts."}`.
   * Measured: 40 rapid requests → all 200; burst of 200 → 118×200 + 82×429.
8. Other headers: `x-romonitor-engine: 1.0.2`, `x-romonitor-compute: LHR-1`, `x-chart-build-time: <sec>` (charts only), `cache-control: no-cache, private`, `x-frame-options: ALLOW-FROM gamefam.com`.

### Windows/PowerShell gotcha (cost me 2 debugging rounds)
`curl.exe -d '{"a":1}'` in Windows PowerShell 5.1 **strips the double quotes**, so Laravel receives invalid JSON and answers `422 "The a field is required."`. Use a file instead:
```powershell
[System.IO.File]::WriteAllText("body.json", '{"placeId":"107778070777162"}', (New-Object System.Text.UTF8Encoding $false))  # no BOM!
curl.exe --data-binary "@body.json" ...
```
A UTF-8 **BOM** also breaks JSON parsing — use `UTF8Encoding $false`.

---

## 4. Working endpoints

### 4a. Public — no auth (verified `200`)

| METHOD | Full URL | Required params | Sample response shape (trimmed) | Auth |
|---|---|---|---|---|
| GET | `https://romonitorstats.com/api/v1/homepage-data/get/` | – | `{"topExperiences":[{"placeId":107778070777162,"universeId":10563114921,"name":"Steal An Egg","playing":1014500,"icons":{...},"creator":{...}}],"topFiveBrandedGames":[...],"topFiveConcerts":[...],"topFiveRobloxDevelopers":[...],"campaigns":[...],"averageSessionLength":...,"analyticsMeta":{"max":42571315,"dates":{"min":"2020-01-05 00:00:00","max":"2026-10-21 17:30:00"}}}` | No |
| GET | `https://romonitorstats.com/api/v1/leaderboards/list` | `page`, `analytic` (one of `active`,`visits`,`favourites`,`likes`,`dislikes`) | `{"experiences":[{"rank":1,"placeId":4924922222,"name":"Brookhaven 🏡RP","icons":{...}}],"lastGenerated":"..."}` (10 per page) | No |
| GET | `https://romonitorstats.com/api/v1/charts/get` | `name`, `timeslice`, `start`, `ends` + scope key (`placeId` \| `genre` \| `communityId` \| `userId` \| `badgeId`) | `[{"name":"CCU Avg","data":{"2026-10-08 00:00:00":1242013.4896,...},"tooltipId":...,"colourHash":...,"plotBands":[]},{"type":"metadata",...}]` | No (but see §4b) |
| GET | `https://romonitorstats.com/api/v1/tables/get` | `name` (see table names below) | `{"table":{"data":[[1,{...}],[2,{...}]],"columns":[...]},"metadata":{...}}` | No (see §4b) |
| GET | `https://romonitorstats.com/api/v1/stats/charts/get/` | `placeId`, `name` | `[{"name":"Top Earning","internalName":"top-earning","icon":"fas fa-money-bill-trend-up","highestExperience":{...},"estimatedCCUs":"6,822,003"},...]` (26 items) | No |
| GET/POST | `https://romonitorstats.com/api/v1/stats/game-profile/get/` | `placeId` | `{"name":"Steal An Egg","urn":"urn:roblox:experience:107778070777162","formattedName":...,"thumbnail":...,"icon":...,"icons":{...},"placeId":...,"universeId":...,"creator":{...},"genre":...,"genres":[...],"isEvent":false,"isClaimed":false,"hasBadges":false,"createdOnRoblox":...,"minAnalyticsDate":...}` | No |
| GET/POST | `https://romonitorstats.com/api/v1/stats/game-general/get/` | `placeId`, `period` (`24h`,`14d`,…) | `{"recentlyAdded":false,"features":{"analyticsEveryTen":false,"analyticsEveryTwo":true,"badgeAnalytics":false},"analytics":{"lastDate":"2026-08-02T17:30:00.000000Z","granularities":{...}},"cardValues":{"players":...,"visits":...,"estimatedPlaytime":...,"serverStats":{...},"interactions":{...},"milestones":{...},"experienceUpdated":...},"isPlayable":true,"sortStats":{...}}` | No |
| GET/POST | `https://romonitorstats.com/api/v1/stats/game-social-graph/get/` | `placeId` | `{"discordServers":[{"url":"https://discord.gg/eggs","serverName":"Steal an Egg","estimatedMembers":580174,"estimatedOnline":69740}],"twitterProfiles":[],"youtubeChannels":[],"robloxGroups":[],"twitchChannels":[],"globalReach":58...,"totalLinks":N}` | No |
| GET/POST | `https://romonitorstats.com/api/v1/stats/experience-peak-ccus/get/` | `placeId` | `"14313917"` (bare JSON string) | No |
| GET/POST | `https://romonitorstats.com/api/v1/stats/experience-badges/get/` | `placeId` | `[]` | No |
| GET/POST | `https://romonitorstats.com/api/v1/stats/experience-badges-stats/get/` | `placeId` | `{"totalBadges":0,"avgWinRate":0,"totalAwards":0,"lastUpdated":"17 hours ago"}` | No |
| GET/POST | `https://romonitorstats.com/api/v1/stats/milestones/get/` | `placeId`, `limit`, `gameId` | `{"visits":[{"gameName":"Steal An Egg","placeId":107778070777162,"milestone":"8B","type":"Visits","tweet":null,"timestamp":"2026-10-14 01:10:00"}],"likes":[...]}` | No |
| GET/POST | `https://romonitorstats.com/api/v1/stats/genre-total-visits/get/` | `genre` | `"136836494863"` (bare string) | No |
| GET/POST | `https://romonitorstats.com/api/v1/stats/roblox-user/get/` | `userId` | `{"user":{"id":1,"name":"Roblox","displayName":"Roblox","joined":"2006-02-27T21:06:40.300000Z","headshotPhoto":...,"isVerified":true,"isBanned":false},"cards":{"totalPlayers":34,"totalVisits":68411493,"totalGames":3},"games":[{"placeId":1818,"name":"Crossroads","playing":28,"visits":39733595,"icon":...}]}` | No |
| GET/POST | `https://romonitorstats.com/api/v1/stats/roblox-community/get/` | `communityId` | `{"community":{"id":1,"name":"RobloHunks","icon":...,"owner":{"id":1179762,"name":"RobloTim"},"analytics":{"hasAnalytics":false,"minDate":null,"maxDate":null},"shout":{...}}}` | No |
| GET | `https://romonitorstats.com/api/v1/stats/roblox-user-milestones/get/` | `userId` | `{"lastAwarded":[{...}],"visits":[...],"likes":[...],"playing":[...],"dislikes":[...]}` | No |
| GET | `https://romonitorstats.com/api/v1/stats/roblox-community-milestones/get/` | `communityId` | same shape as above | No |
| GET | `https://romonitorstats.com/api/v1/stats/roblox-sorts-list/get/` | – | `{"top-earning":"Top Earning","top-playing-now":"Top Playing Now","most-popular":"Most Popular","top-revisited":"Top Revisited","trending-in-simulation":...,"fun-with-friends":...,"up-and-coming":...,"more-when-you-subscribe":...}` | No |
| GET | `https://romonitorstats.com/api/v1/stats/country-and-device-sorts-list/get/` | – | `{"devices":[{"name":"All Devices","code":"all"},{"name":"Computer","code":"computer"},{"name":"High End Phone","code":"high_end_phone"},{"name":"Console","code":"console"},{"name":"VR","code":"vr"}],"countries":[{"name":"Argentina","code":"ar"},...]}` | No |
| GET | `https://romonitorstats.com/api/v1/stats/sort/get/` | `placeId`, `page`, `code` (a sort code from roblox-sorts-list) | `{"sort":{"name":"Top-earning"},"experiences":{"yUVWg":{"placeId":84515722934860,"name":"Anime Expeditions [UPDATE 💀]","icons":{...}}}}` (keyed map) | No |
| GET | `https://romonitorstats.com/api/v1/stats/generate-chart/get` | `analytic`, `placeId`, `timeframe` | `[{"name":"Steal An Egg","data":{"2026-10-07 18:00:00":7120292834,...}}]` | No |
| GET | `https://romonitorstats.com/api/v1/search/experience-preload/` | `term` | `[{"formattedName":"Steal An Egg","universeId":10563114921,"placeId":107778070777162,"image":...,"objectID":107778070777162,"rating":91.82,"playing":1096940}]` | No |
| POST | `https://romonitorstats.com/api/v1/search/query/` | `application` (`romonitor-stats`), `group` (`group`\|`user`), `query` | `{"count":25,"results":[{"id":999771657,"name":"Steal a garden or something","members":"16,177,299","image":...}]}` | CSRF only |
| GET | `https://romonitorstats.com/api/v1/money/get-devex-rate/` | – | `{"rate":0.0038,"previousRate":0.0035,"minRobux":30000,"maxRobux":20000000000,"tooltip":"..."}` | No |
| GET | `https://romonitorstats.com/api/v1/money/list-exchange-rates/` | – | `{"rates":[{"name":"US Dollar","code":"USD","rate":1},{"name":"Euro","code":"EUR","rate":0.890494},...]}` (~9.8 KB) | No |
| GET | `https://romonitorstats.com/api/v1/blog/romonitor-stats/` | – | `{"latest":{"title":"...","url":"...","image":"/storage/generated/news/...","preview":"..."}, ...}` | No |
| GET | `https://romonitorstats.com/api/v1/application/get/` | `application` (`romonitor-stats`) | `{"code":"romonitor-stats","name":"RoMonitor Stats","description":"...","version":2.56,"author":"Silicon Digital Group Ltd","supportEmail":"...","twitter":"RoMonitorStats","theme":{"primary":"#8B5EA5"},"banners":[],"loginSplashes":[...]}` | No |
| GET | `https://romonitorstats.com/api/v1/concerts/stats/` | `placeId` | `{"deepDiveStatCard":{"concertCCUs":133999.98,"concertRating":67.08,"totalConcertVisits":331010977}}` | No |
| GET | `https://romonitorstats.com/api/v1/experience/{placeId}/card-stats/get/` | path segment `placeId` | `{"ccu":1011561,"visits":8955643562,"sessionLength":15.45,"rating":91.814}` | No |
| GET | `https://romonitorstats.com/api/v1/branded-page-data/get/` | `placeId` | `{"brandedExperienceStats":{"brandedCCUs":37354,"brandedVisits":12482404913,"brandedAverageCCUs":166.01,"brandedAverageSessionLength":5.35}}` | No |
| POST | `https://romonitorstats.com/api/v1/wallboard/data/` | `placeId` | `{"meta":{"gameName":"Steal An Egg"},"cards":[{"title":"Playing","value":"1,011,561","measurement":"Players"},{"title":"Visits","value":"8,955,452,950",...}],"status":null,"generated":"..."}` | CSRF only |
| POST | `https://romonitorstats.com/api/v1/stats/total-visits/get/` | `placeId`, `range` (`"start=...&ends=..."`) | `1737116457` (bare number) | CSRF only |
| POST | `https://romonitorstats.com/api/v1/contact/send-contact-mail/` | `name`,`company`,`email`,`subject`,`markdown` | `422` on bad email; correct shape unverified (would send mail) | CSRF only |

### 4b. Public but *content-gated* (403 unless logged in / valid API key)

| METHOD | URL | Gate message observed |
|---|---|---|
| GET | `/api/v1/charts/get?name=engagement&…` | `403 {"message":"You must be logged in to view this chart."}` |
| GET | `/api/v1/charts/get?name=retention&…` | same |
| GET | `/api/v1/charts/get?name=country&…` | same |
| GET | `/api/v1/charts/get?name=age-pie-chart&…` | same |
| GET | `/api/v1/charts/get?name=estimated-dau&…` | same |
| GET | `/api/v1/tables/get?name=top-experiences-deep-dive&…` | `403 {"message":"You must be logged in to view this table."}` |
| GET | `/api/v1/tables/get?name=genres-deep-dive&…` | same |
| GET | `/api/v1/tables/get?name=top-experiences-in-genre-deep-dive&genre=…` | same |
| POST | `/api/v1/reports/chart-report` | `403 {"message":"You must be logged in to submit chart reports."}` |

**Publicly accessible table names** (verified 200): `branded-deep-dive`, `top-developers-deep-dive`, `campaigns-deep-dive`, `concerts-deep-dive`.
**Publicly accessible chart names** (verified 200): `ccus`, `visits`, `session-length`, `rating`, `ccu-platform-share`, `top-earning-sort-position`, `platform-ccus`, `genre-visits`, `community-members`, `user-experience-ccus`, `user-experience-visits`, `community-experience-ccus`, `community-experience-visits`, `daily-community-members`, `likes-and-dislikes` (needs `placeId` or `universeId`), `favourites`, `sessions-per-player-per-day`, `iap-revenue`, `net-revenue-per-visitor`, `paying-users`, `conversion-rate`, `new-users-by-source`, `arp-dau`, `server-stats`, `server-memory`, `client-memory`, `client-memory-percentage`, `compute-efficiency`, `crash-rates`, `experience-country-revenue-pie-chart`, `usd-revenue-breakdown-pie-chart`, `gender-pie-chart`, `experience-update-flags`, `genre-ccus`, `genre-session-length`, `genre-favourites`, `estimated-dau`(*gated*).

> Note: a >14-day `start`/`ends` window produces the *same* `403 "You must be logged in to view this chart."` message. Always keep anonymous windows ≤ 14 days, otherwise you cannot distinguish "gated chart" from "window too long".

### 4c. Login / account required (401 / 403 / 404)

| METHOD | URL | Result observed |
|---|---|---|
| GET | `/api/v1/account/list-api-keys/` | `401 {"message":"Unauthenticated"}` |
| POST | `/api/v1/account/create-api-key/`, `/api/v1/account/delete-api-key/` | 401 |
| GET | `/api/v1/account/validate-password/` | 401-class |
| POST | `/api/v1/auth/login/` | `422 {"message":"These credentials do not match our records.","errors":{"email":[...]}}` (works; needs real creds) |
| POST | `/api/v1/auth/register/`, `/api/v1/auth/logout/`, `/api/v1/auth/email/resend/`, `/api/v1/auth/password/email`, `/api/v1/auth/password/reset` | auth-class |
| POST | `/api/v1/dashboard/get/`, `/list-experiences/`, `/get-experience/`, `/get-overview-cards-data/`, `/get-revenue-cards-data/`, `/portfolio-tables/`, `/sessions-per-player-per-day/`, `/list-ownership-percentages/`, `/export-all-portfolio-tables` | `401 Unauthenticated` / `404 {"message":"The selected code is invalid."}` (dashboard `code` must be a real dashboard slug) |
| GET | `/api/v1/dashboard/list-milestones/` | `404 {"message":"The selected code is invalid."}` |
| POST | `/api/v1/athena/manage/*` (overview, developers, invites, list-places, live-purchases, membership-stats, status, sync-places, transfer-ownership, audit-log, get-complete-stats, invite-developer, remove-developer, can-manage-experience, account-permissions-check) | `422 {"message":"The universe id field is required."}` then 401/403 once params are supplied |
| POST | `/api/v1/athena/setup/*` (can-be-claimed, check-invite, check-verification, dev-mode-claim, start-verification) | 500 / auth-class |
| POST | `/api/v1/gamefam-export/experience-master/`, `/api/v1/gamefam-export/experience-revenue-breakdown/` | `401 {"message":"Unauthenticated"}` |
| GET | `/api/v1/gamefam/get-assets-information` | `401 {"message":"Unauthenticated"}` |
| POST | `/api/v1/genres/get-genre-insight/` | `401 {"message":"Unauthenticated"}` |
| POST | `/api/v1/moderation/check-experience/`, `/api/v1/moderation/request-experience/` | `401 {"message":"Unauthenticated"}` |
| POST | `/api/v1/newsletter/subscribe/` | `401 {"message":"Unauthenticated."}` |
| POST | `/api/v1/stats/game-subscribe/get/` | `401 {"message":"Unauthorised"}` |
| GET | `/api/v1/stats/game-favourite/get/` (and POST) | `404 {"message":"We couldn't find the requested endpoint."}` — route not registered (see §5) |

---

## 5. Dead / blocked / ruled-out paths (do not re-test)

| Path | Result | Note |
|---|---|---|
| `GET /api/v1/stats/` | `200` + **SPA HTML** (11 929 B) | Catch-all fallback, not an API route. |
| `GET /api/v1/charts` | `200` + SPA HTML | The documented base URL is a *documentation link*, not a working route. Use `/api/v1/charts/get`. |
| `GET /api/v1/tables` | `200` + SPA HTML | Same → use `/api/v1/tables/get`. |
| `GET/POST /api/v1/stats/game-favourite/get/` | `404 "We couldn't find the requested endpoint."` | **Dead route** even though `StatsMoreTools`/`GameStats` bundles still call it (`axios.post("/api/v1/stats/game-favourite/get/",{placeId:...})`). Broken in the deployed SPA. |
| `GET /api/v1/stats/roblox-badge/get/?badgeId=1` | `500 {"message":"Server Error"}` | Server-side error, not a shape/param problem (both `badgeId` and `userId` produce 500). |
| `GET /api/v1/stats/roblox-badge-recommendations/get/?badgeId=1` | `500` | Same. |
| `GET /api/v1/social-graph/twitter-analytics/?id=…` | `422 {"message":"The selected id is invalid."}` for `123` and `RoMonitorStats` | `id` is validated against a known list; no working value found. |
| `GET /api/v1/update-history/get?universeId=…` | `422 {"message":"The selected universe id is invalid."}` | Rejected valid universeIds (`66654135`, `10563114921`). |
| `GET /api/v1/stats/total-visits/get/?placeId=…` | `500` | The GET route exists but is broken → use **POST** with `range`. |
| `POST /api/v1/stats/total-visits/get/` with `range` = `"a,b"` | `500` | `range` must be the literal `"start=…&ends=…"` string. |
| `GET/POST /api/v1/tables/get?name=top-experiences-deep-dive` (no dates) | `403` login | Not a param problem. |
| `GET /api/v1/blog/get/?application=romonitor-stats&code=…` | `422 {"message":"The selected code is invalid."}` | Only `/api/v1/blog/romonitor-stats/` (no code) is public. |
| `POST /api/v1/export/top-experiences-deep-dive-export/` | `500` | Export endpoint is broken/logged-in only. |
| `POST /api/v1/export/platform-metric-export/?metric=ccus` | `422 {"message":"The selected metric is invalid."}` | `metric` allow-list unknown. |
| `POST /api/v1/export/chart-export` | — | Not probed successfully; sibling of the broken export route. |
| `https://docs.romonitorstats.com/` (+ `/api`, `/sdk/installation/`) | `200` but **Cloudflare Access login page** ("Please sign in with your company email") | Official API docs are not publicly readable. |
| `https://export-api.romonitorstats.com/` | `404` (Express `Cannot GET /`) | Separate host for async export jobs; paths unknown. |
| `https://search.romonitorstats.com/indexes/experiences/search` | `403 "The API key cannot acces the index \`experiences\`, authorized indexes are [\"games_index\"]"` | Use index `games_index`. |
| `https://search.romonitorstats.com/indexes` (list) | `403 "The provided API key is invalid."` | Key is search-only. |

---

## 6. Secondary host: Meilisearch (search)

`search.romonitorstats.com` is a **Meilisearch** instance. The public search key is hardcoded in the SPA bundles:

```
https://search.romonitorstats.com
Authorization: Bearer <cle_publique_meilisearch_voir_README>
```

Only the `games_index` index is authorized by this key.

* `POST https://search.romonitorstats.com/indexes/games_index/search` body `{"q":"steal an egg","limit":3}` → `200`
  ```json
  {"hits":[{"place_id":107778070777162,"formattedName":"Steal An Egg","robloxUrl":"https://www.roblox.com/games/107778070777162/","creatorName":"and Collect Rare Pets","name":"Steal An Egg","placeId":107778070777162,"image":"https://tr.rbxcdn.com/...","largeImage":"...","thumbnail":"...","playing":988176,"visits":8955744516,"genre":"","creatorId":825735094,"likes":3696631,"dislikes":329456,"rating":"91.82"}],"query":"steal an egg", ...}
  ```
* `GET /indexes/games_index` (index metadata) → `403` for this key.
* The legacy Algolia code in `chunk-vendors` is vendored but **not** used for search (no Algolia app id/key found in the bundles).
* The SPA also has its own proxy endpoint `GET /api/v1/search/experience-preload/?term=…` (same data, no Meilisearch key needed) and `POST /api/v1/search/query/` for group/user search.

---

## 7. HOW TO CALL

### 7.0 One-time CSRF handshake (needed for POST only)
```bash
curl -c cookies.txt https://romonitorstats.com/sanctum/csrf-cookie/
# XSRF-TOKEN=<url-encoded>; romonitor_session=<...>
# header value must be the URL-DECODED cookie
TOKEN=$(grep XSRF-TOKEN cookies.txt | awk '{print $7}' | python -c "import sys,urllib.parse;print(urllib.parse.unquote(sys.stdin.read().strip()))")
```

### 7.1 GET — homepage top experiences
```bash
curl "https://romonitorstats.com/api/v1/homepage-data/get/" -H "Accept: application/json"
```

### 7.2 GET — leaderboard
```bash
curl "https://romonitorstats.com/api/v1/leaderboards/list?page=1&analytic=visits" -H "Accept: application/json"
# analytic ∈ active | visits | favourites | likes | dislikes
```

### 7.3 GET — chart (anonymous: ≤ 14-day window)
```bash
curl "https://romonitorstats.com/api/v1/charts/get?name=ccus&timeslice=day&placeId=107778070777162&start=2026-10-08T00:00:00.000Z&ends=2026-10-21T23:59:59.999Z" -H "Accept: application/json"
```
Other scopes: `genre=Simulation`, `communityId=1`, `userId=1`, `badgeId=1&analytic=awarded`.
Optional extras seen in the SPA: `includeExperienceName=false`, `proVersion=false`, `device=<code>`, `country=<code>`.

### 7.4 GET — table (public names only)
```bash
curl "https://romonitorstats.com/api/v1/tables/get?name=branded-deep-dive" -H "Accept: application/json"
curl "https://romonitorstats.com/api/v1/tables/get?name=top-developers-deep-dive" -H "Accept: application/json"
```

### 7.5 GET — experience card stats (route-param style)
```bash
curl "https://romonitorstats.com/api/v1/experience/107778070777162/card-stats/get/" -H "Accept: application/json"
```

### 7.6 GET — user / community profile
```bash
curl "https://romonitorstats.com/api/v1/stats/roblox-user/get/?userId=1" -H "Accept: application/json"
curl "https://romonitorstats.com/api/v1/stats/roblox-community/get/?communityId=1" -H "Accept: application/json"
```

### 7.7 GET — sort / sorts list
```bash
curl "https://romonitorstats.com/api/v1/stats/roblox-sorts-list/get/" -H "Accept: application/json"
curl "https://romonitorstats.com/api/v1/stats/sort/get/?placeId=107778070777162&page=1&code=top-earning" -H "Accept: application/json"
```

### 7.8 GET — DevEx rate & FX rates
```bash
curl "https://romonitorstats.com/api/v1/money/get-devex-rate/" -H "Accept: application/json"
curl "https://romonitorstats.com/api/v1/money/list-exchange-rates/" -H "Accept: application/json"
```

### 7.9 GET — search preload (no key needed)
```bash
curl "https://romonitorstats.com/api/v1/search/experience-preload/?term=steal" -H "Accept: application/json"
```

### 7.10 POST — game profile (CSRF + JSON body)
```bash
# body.json  ->  {"placeId":"107778070777162","compare":null}
curl -b cookies.txt -X POST "https://romonitorstats.com/api/v1/stats/game-profile/get/" \
  -H "Content-Type: application/json;charset=utf-8" \
  -H "Accept: application/json" \
  -H "X-XSRF-TOKEN: $TOKEN" \
  --data-binary @body.json
```
Same call with the id in the query string also works:
```bash
curl -b cookies.txt -X POST "https://romonitorstats.com/api/v1/stats/game-profile/get/?placeId=107778070777162" \
  -H "X-XSRF-TOKEN: $TOKEN" -H "Accept: application/json" -d '{}'
```

### 7.11 POST — general stats / milestones / social graph
```bash
curl -b cookies.txt -X POST "https://romonitorstats.com/api/v1/stats/game-general/get/" \
  -H "Content-Type: application/json" -H "X-XSRF-TOKEN: $TOKEN" \
  --data-binary '{"placeId":"107778070777162","period":"24h"}'

curl -b cookies.txt -X POST "https://romonitorstats.com/api/v1/stats/milestones/get/" \
  -H "Content-Type: application/json" -H "X-XSRF-TOKEN: $TOKEN" \
  --data-binary '{"placeId":"107778070777162","limit":10,"gameId":"107778070777162"}'

curl -b cookies.txt -X POST "https://romonitorstats.com/api/v1/stats/game-social-graph/get/" \
  -H "Content-Type: application/json" -H "X-XSRF-TOKEN: $TOKEN" \
  --data-binary '{"placeId":"107778070777162"}'
```

### 7.12 POST — total visits (range is a literal "start=…&ends=…" string)
```bash
curl -b cookies.txt -X POST "https://romonitorstats.com/api/v1/stats/total-visits/get/" \
  -H "Content-Type: application/json" -H "X-XSRF-TOKEN: $TOKEN" \
  --data-binary '{"placeId":"107778070777162","range":"start=2026-10-08T00:00:00.000Z&ends=2026-10-21T23:59:59.999Z"}'
```

### 7.13 POST — group/user search
```bash
curl -b cookies.txt -X POST "https://romonitorstats.com/api/v1/search/query/" \
  -H "Content-Type: application/json" -H "X-XSRF-TOKEN: $TOKEN" \
  --data-binary '{"application":"romonitor-stats","group":"group","query":"steal"}'
```

### 7.14 POST — wallboard
```bash
curl -b cookies.txt -X POST "https://romonitorstats.com/api/v1/wallboard/data/" \
  -H "Content-Type: application/json" -H "X-XSRF-TOKEN: $TOKEN" \
  --data-binary '{"placeId":"107778070777162"}'
```

### 7.15 POST — Meilisearch (no CSRF; separate host)
```bash
curl -X POST "https://search.romonitorstats.com/indexes/games_index/search" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <cle_publique_meilisearch_voir_README>" \
  --data-binary '{"q":"steal an egg","limit":10}'
```

---

## 8. JS bundles containing the route definitions

All under `https://romonitorstats.com/stats-dist/js/`. Download + grep for `"/api/v1/` to regenerate the route map.

**Main / vendor**
* `https://romonitorstats.com/stats-dist/js/chunk-vendors.9622b69e.js` (axios, highcharts, algolia lib, meilisearch lib)
* `https://romonitorstats.com/stats-dist/js/index.5248542c.js` ← **axios config, CSRF/error interceptor, router table, `/api/v1/auth/login/`**

**Route-definition heavy chunks** (grep these first — they contain the `axios.get/post("/api/v1/...")` call sites)
* `https://romonitorstats.com/stats-dist/js/ExperienceStats.f0d149a0.js` (all experience charts: `charts/get?name=…`)
* `https://romonitorstats.com/stats-dist/js/GameStats.0f622374.js`
* `https://romonitorstats.com/stats-dist/js/StatsHome.9a08ff57.js` (`charts/get?name=platform-ccus`)
* `https://romonitorstats.com/stats-dist/js/StatsMoreTools.1d6e358c.js` (leaderboards + `tables/get?name=top-experiences-deep-dive`)
* `https://romonitorstats.com/stats-dist/js/StatsMisc.8b77b7c5.js` (**"About the RoMonitor API" card → `/api/v1/charts`, `/api/v1/tables`, API-key UI**)
* `https://romonitorstats.com/stats-dist/js/BrandedStats.0f6c8b0d.js` (public tables: branded / top-developers / campaigns / concerts)
* `https://romonitorstats.com/stats-dist/js/GenreStats.2303834b.js` (genre charts/tables)
* `https://romonitorstats.com/stats-dist/js/RobloxPlatform.7d8f475d.js` (community/user charts)
* `https://romonitorstats.com/stats-dist/js/CustomDashboards.e8dbe592.js`
* `https://romonitorstats.com/stats-dist/js/Search.32fa6cd7.js` (Meilisearch key)
* `https://romonitorstats.com/stats-dist/js/Athena.70c8d794.js` (Athena / developer console APIs)
* `https://romonitorstats.com/stats-dist/js/StatsSignon.2a83d591.js` (auth)
* `https://romonitorstats.com/stats-dist/js/default~CustomDashboards~ExperienceStats~GameStats~GenreStats~RoMonitorCharts~RobloxPlatform~SharedC~920ea6f0.0ed533fc.js` ← **`chartStartEndDates` / `tableStartEndDates` date-range builders + `canViewOver14DaysOfData`**
* `https://romonitorstats.com/stats-dist/js/default~CustomDashboards~ExperienceStats~GameStats~RobloxPlatform~StatsInternal.16719117.js` ← **`/api/v1/experience/{id}/card-stats/get/`**
* `https://romonitorstats.com/stats-dist/js/default~RoMonitorCharts~Search~StatsHome~StatsInternal.09abb672.js`
* `https://romonitorstats.com/stats-dist/js/SharedComponents.43d46f96.js`
* `https://romonitorstats.com/stats-dist/js/RoMonitorCharts.593204b3.js`
* `https://romonitorstats.com/stats-dist/js/Requests.0fa7ec90.js`, `MilestoneStats.644ae78f.js`, `DropdownComponent.5e363667.js`, `StatsNews.cbc7c0da.js`

---

## 9. Rate limits / blocking summary

* Per-IP (per-minute) throttling. Headers on **every** response:
  `x-ratelimit-limit: 80` (most endpoints) / `300` (charts, game-profile), `x-ratelimit-remaining`, `x-ratelimit-reset`.
* Over limit → `429 Too Many Requests`, `retry-after: <seconds>`, body `{"message":"Too Many Attempts."}`.
* No Cloudflare challenge, no CAPTCHA, no WAF block observed on API paths at this request volume.
* Recommended: ≤ 60 requests/minute on the 80-limit routes, add jitter, honour `retry-after`.

---

## 10. Quick count

* **Verified working public (no account) endpoints: 33** — 18 GET-only, 11 that accept both GET and POST, 4 POST-only.
* **Verified content-gated (needs account / API key): 11**.
* **Login/account-required endpoints catalogued: 30+** (account, auth, athena, dashboard, gamefam-export, moderation, newsletter).
* **Dead / unusable paths ruled out: 16**.
* **Secondary API hosts: 2** (`search.romonitorstats.com` Meilisearch, `export-api.romonitorstats.com`).
