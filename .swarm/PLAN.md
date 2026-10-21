# Swarm Plan — Roblox Analytics Clients

**Epic:** Build `romonitorstats.py` + `rolimons.py` Python API clients, mirroring the
existing `rotrend.py` (public API, no auth, plain functions returning dicts, `__main__`
CLI with JSON output, `curl_cffi`).

**Location:** `C:\Users\Zenith\Tools\roblox-scripting\`
**Branch:** `swarm/roblox-analytics-clients`

---

## Environment deviations (swarm plugin tools unavailable)

The swarm plugin exists at `~/.config/opencode/plugin/swarm.ts` (117 KB, defines
`swarmmail_*`, `hive_*`, `hivemind_*`, `skills_*`, `cass_*`) but **none of its tools are
registered in this session**.

**Root cause (confirmed + fix VERIFIED):** the `swarm-fs` MCP server is launched as
`node mcp/swarm-fs/dist/index.js` (see `C:\Users\Zenith\Tools\opencode-swarm_8\opencode.json`),
but that path **does not exist** — the compiled server is at
`dist/mcp/swarm-fs/src/index.js` (tsc `rootDir: "."`, `outDir: "dist"`). Additionally
`src/index.ts:36` does `join(process.cwd(), "runs", RUN_ID)` where `RUN_ID` comes from
`process.env.SWARM_RUN_ID` — unset ⇒ `TypeError: The "path" argument must be of type
string. Received undefined` ⇒ server dies ⇒ plugin tools never register.

**Verified working configuration** (I hand-ran an MCP `initialize` + `tools/list`
against it and got a valid handshake listing 8 tools: `board_status`, `log_append`,
`log_tail`, `artifact_write`, `artifact_read`, `dependency_wait`, `handoff`, `task_done`):

```jsonc
// ~/.config/opencode/opencode.jsonc  ->  mcp block
"swarm-fs": {
  "type": "local",
  "command": ["node", "dist/mcp/swarm-fs/src/index.js"],
  "cwd": "C:\\Users\\Zenith\\Tools\\opencode-swarm_8",
  "enabled": true,
  "environment": {
    "SWARM_RUN_ID": "{env:SWARM_RUN_ID}",
    "SWARM_RUN_DIR": "{env:SWARM_RUN_DIR}"   // <-- this one prevents the crash
  }
}
```
Two changes matter: **correct the path** and **set `SWARM_RUN_DIR`** to a real directory
(then `SWARM_RUN_ID` is never needed for path building). `cwd` is required because the
command path is relative.

**Adaptation used** (same workflow, harness-native primitives):

| Swarm concept | Available here | Used as |
|---|---|---|
| `swarmmail_init` | — | this plan file is the task ledger |
| `skills_use` | `skill` tool | ✅ direct equivalent |
| `swarm_plan_interactive` / `swarm-planner` | `question` + `subagent` | ✅ Socratic Q + delegated planning |
| `hive_create_epic` | — | this file's bead table |
| `swarm_spawn_subtask` / `Task(swarm-worker)` | `subagent` (general/explore) | ✅ worker spawn |
| `swarmmail_reserve` | — | file ownership = disjoint file lists (no overlap) |
| `swarmmail_inbox` | — | coordinator polls `subagent` completion notifications |
| `swarm_review` | — | coordinator reads each worker's file + runs the verifier |
| `swarm_complete` | — | final commit on branch |

`gh` CLI is **not installed** → PR step is blocked; will commit to branch and report.

---

## Beads

| # | Bead | Files (exclusive) | Depends on | Status |
|---|------|-------------------|------------|--------|
| B0 | Blueprint: shared skeleton + per-site checklists | `.swarm/BLUEPRINT.md` | — | ✅ done (640 ln, py_compile-verified) |
| R1 | Research `romonitorstats.com` API | `.research/romonitorstats.md` | — | ✅ done — 33 public endpoints verified |
| R2 | Research `rolimons.com` API | `.research/rolimons.md` | — | ⏳ running |
| B1 | Build `romonitorstats.py` | `romonitorstats.py` | R1, B0 | ✅ **reviewed + committed** `5e350d7` |
| B2 | Build `rolimons.py` | `rolimons.py` | R2, B0 | ✅ **reviewed + fixed + committed** `e7151f2` |
| B3 | Cross-verify both clients + README | `README.md`, `verify_clients.py` | B1, B2 | ✅ **committed** `8eb4dd5` |
| F1 | Fix `romonitorstats.py` banner day clamp | `romonitorstats.py` | — | ✅ **committed** `eed61dd` |
| F2 | Correct README's TLS/impersonate claim | `README.md` | — | ✅ **committed** `8eb4dd5` |

## FINAL STATE — swarm complete

```
 5 commits · 5 files · 3 085 insertions · working tree clean
 branch: swarm/roblox-analytics-clients
 verify_clients.py → 49/49 PASS, exit 0
```

| Commit | Deliverable |
|---|---|
| `36f6df6` | baseline (rotrend.py) |
| `5e350d7` | `romonitorstats.py` — 23 commandes |
| `e7151f2` | `rolimons.py` — 24 commandes |
| `eed61dd` | fix: bandeau plus de jours que les données (F1) |
| `8eb4dd5` | `README.md` + `verify_clients.py` (F2) |

### F2 — the README's TLS claim, resolved

The original claim ("l'empreinte TLS est obligatoire") was **wrong**; the rejected
rewrite was **incomplete**. The truth, measured by the coordinator (3 samples/cell,
identical HTTP status every time) and confirmed independently by B3:

| config | itemdetails | /item/1029025 | /player/1 |
|---|---|---|---|
| `impersonate=None`, no headers at all | **403** (4 546 o) | **403** | **403** |
| `impersonate=None`, `UA=curl/8.21.0` | 200 | 200 | 200 |
| `impersonate=None`, `UA=Chrome` | 200 | 200 | 200 |
| `impersonate="chrome"` (UA auto) | 200 | 200 | **403 « Just a moment… »** (5 953 o) |

**The discriminator is the `User-Agent`, not the TLS fingerprint.** `curl_cffi` without
`impersonate` sends *no* UA at all (unlike `curl.exe`, which sends `curl/8.21.0`), and
Cloudflare's WAF blocks that with 403 on every rolimons.com endpoint. Any UA at all
fixes it. And `/player/<id>` is the single point where impersonating Chrome is *worse*
than a plain curl — a real browser fingerprint with no `Referer` is the scraper
signature, which is why the client sends `referer: https://www.rolimons.com/`.

### Not done / out of scope
- **No PR**: `gh` is not installed on this machine. The branch is ready to push.
- **swarm plugin tools still absent this session**: `swarm-fs` MCP server fails
  (path + env bug, fix verified above). Needs a session restart to take effect.
- `rotrend.py` was left untouched — it is the pre-existing reference client, and the
  user asked only for the two new scripts.

### B3 review — verifier PASSED, one factual claim in the README rejected

`verify_clients.py` (B3) run by the **coordinator** → **49/49 PASS, exit 0**:
24/24 romonitorstats · 25/25 rolimons · all payloads valid JSON and non-empty.
The verifier reads the command list from each script's own `__main__` block and
derives the positional-arg count from the `_arg`/`_int_arg`/`_text_arg` helpers.

**B3 found a display bug in `romonitorstats.py` (lines 540/547/633):** the banner
printed the *requested* `days` while `_window()` silently clamps to 14 (the anonymous
window cap). `chart ccus 107778070777162 30` returns the same 14 points as `… 14` but
the banner claimed "30 j" — right data, lying label. → fix cell F1.

**B3 also made a claim the coordinator rejected.** The README asserted the TLS
fingerprint was *obligatory*. The coordinator ran the matrix (3 samples/cell, all
byte-identical):

```
endpoint                                  impersonate=None    impersonate="chrome"
api.rolimons.com/items/v3/itemdetails    200 / 172499  x3    200 / 172499  x3
www.rolimons.com/item/1029025            200 / 1674833 x3    200 / 1674833 x3
www.rolimons.com/catalog                 200 / 772384  x3    200 / 772384  x3
www.rolimons.com/player/1                200 / 882531  x3    403 / 5953   x3  <- only diff
```

**No endpoint requires the TLS fingerprint.** The accurate rule is narrower and
more interesting: `/player/<id>` is the only page that challenges, and only when the
request carries a Chrome fingerprint **without** a `Referer` — a browser TLS
fingerprint with no Referer is exactly what a scraper looks like. The client sends
`referer: https://www.rolimons.com/` (`rolimons.py` line 74), which is why it works.
→ fix cell F2.

### B2 review — APPROVED after one fix round (coordinator re-verified independently)

| Check | Result |
|---|---|
| `py -m py_compile` | ✅ |
| All 24 CLI commands | ✅ **24/24 exit 0, valid JSON, non-empty, no traceback** |
| Data vs research | ✅ `asset_count=2415` `bundle_count=160` `item_count=2575` `game_count=7822`; item 1029025 → "The Classic ROBLOX Fedora" / value 450000 / demand 4 / trend 2; bundle 939596 → "The Jade Catseye" / value −1 |
| Error paths | ✅ 5/5 exit 1 + `{"error": …}`, no traceback |
| Coordinator corrections applied | ✅ `__http_error__` sentinel · no `_data()` · `status` heuristic removed **with the reason documented** · `timeout=30` · named-dict mapping for the 9- and 26-element tuples |

**Fix round:** `avatar_thumbnails()` returned `{}` with exit 0 for an unknown user id
(the API answers `200 {"success":true,"thumbnails":{}}`, so the script was being
faithful — but silence is the worst CLI outcome, and every other "not found" path
in the script exits 1). B2 added the guard; coordinator re-verified:
`avatar 999999999` → **exit 1** + `{"error": "aucune miniature trouvée …"}` ·
`avatar 1` → exit 0 with the real thumbnail · `avatar 1,2,3` → exit 0, 3 thumbnails ·
24/24 still green, no regression.

**B2 exceeded the brief in three places:**
- `_error_detail()` distinguishes a Cloudflare **1015** hard block from a plain 429
  and tells the user to wait ~90 s; `_get()` honours `Retry-After` with one bounded retry
- a **balanced-brace extractor ported to Python** (tracks string state + escapes, and
  handles scalars) instead of the greedy regex the research warned over-captures
- 60 s catalogue cache + 3.5 s search pacing, protecting the 20 req/60 s `groupsearch`
- it **pushed back** on the blueprint's exact-import-list rule (`{curl_cffi, datetime,
  json, sys}`) because `re` and `time` are genuinely needed here — and said so rather
  than diverging silently

### B1 review — APPROVED (coordinator ran the checks independently, not from the agent's report)

| Check | Result |
|---|---|
| `py -m py_compile` | ✅ |
| All 22 CLI commands | ✅ **23/23 exit 0, valid JSON, non-empty, no traceback** |
| Failure paths (`game 1`→422, `user 999999999999`→500, `card 1`→404, bad enum) | ✅ exit 1, `{"error": …}`, no traceback |
| Real data matches research | ✅ `analyticsMeta.max=42571315`, `peak_ccus="14313917"`, homepage top = Steal An Egg, leaderboard #1 visits = Brookhaven 🏡RP |
| Coordinator corrections applied | ✅ `__http_error__` sentinel · no blind `_unwrap`/`_data` · `timeout=30` · 14-day clamp · client-side enum validation · CSRF handshake |
| 550 lines, 21 functions, French docstrings, `curl_cffi` only | ✅ |

**B1's deviations from my brief — all verified, all justified:**
1. `stats/social-graph/get/` → real path is `stats/game-social-graph/get/`
2. `stats/milestones/get/` also needs `gameId` (else 422)
3. `stats/generate-chart/get` only accepts `visits|playing|favourites|rating`
4. `stats/charts/get/` ignores `name` → returns all 26 charts, `name` not sent
5. **`search/experience-preload/` ignores `term`** → returns top games even for a
   nonsense term, i.e. a fake search. B1 switched to the Meilisearch host.
   *Coordinator re-verified: `search brookhaven` → Brookhaven 🏡RP; `search
   zzqqxxnotagame` → `[]`. Genuinely filters.*

**Harness note for B3:** three endpoints return a **bare JSON scalar**
(`peak`→`"14313917"`, `genre`→`"136837926908"`, `total-visits`→`1737116457`).
The verifier must strip the `=== … ===` header line and parse the remainder as a
scalar-capable JSON value — anchoring on `{`/`[` alone reports false failures.

**No file overlap between beads** — B1 and B2 run fully in parallel.
Briefs are staged and ready to fire: `.swarm/WORKER_BRIEFS.md`.

### R1 findings that shaped B1's brief (romonitorstats)

| Fact | Consequence for the client |
|---|---|
| Laravel + Vue 2, API at `https://romonitorstats.com/api/v1/*` | same-origin, `origin`/`referer` = `https://romonitorstats.com` |
| GETs need no auth; POSTs need Laravel CSRF | `GET /sanctum/csrf-cookie/` → `XSRF-TOKEN` cookie + `X-XSRF-TOKEN` header (url-decoded) |
| Params in query string **or** JSON body — query wins | send POST params as query string; body only as fallback |
| camelCase fields, date param is **`ends`** not `end` | `start=<ISO>&ends=<ISO>` |
| **Anonymous capped at a 14-day window** | clamp every `days` param to ≤ 14 |
| **Bare JSON** — no `success`/`data` envelope | blueprint's `_unwrap`/`_data` are unsafe here; detect errors from HTTP status + `{"message":...}` |
| Rate limit 80/min (300 charts) | no hammering; report 429s |
| 16 dead paths catalogued (404/500/422) | don't re-test them |
| `search.romonitorstats.com` = Meilisearch, `export-api.*` = async export host | optional / skipped |

## Coordinator review of B0 (blueprint) — corrections folded into both briefs

Blueprint quality: good. Three deliberate deviations from `rotrend.py` that are
**improvements** and are kept:
- `_check()` — the reference returns an error *dict* on non-200, so the CLI printed
  `{}` and exited 0 on a 403/429. `_check()` turns that into an `ApiError`.
- base64 fallback removed — it silently swallowed a Cloudflare HTML page into
  `{"raw": "<html>Just a moment…"}` with exit code 0.
- `except ApiError → pp({"error": …}) + sys.exit(1)` — the gate demands no tracebacks.

Four corrections I added when briefing the workers:
1. **Add `timeout=30` to `_get`/`_post`** — the skeleton had none; a hung connection
   blocks the CLI forever.
2. `_unwrap()`'s `status in ("error","failed","failure")` check must be narrowed to
   what the research actually documents — a legit payload must never raise.
3. `_check()`'s `"error" in data` test is too broad — the error key should be a
   distinct sentinel so a real `error` data field isn't misread as an HTTP failure.
4. If the API returns bare JSON arrays, `_data()` must not mangle them.

---

## Shared conventions (contract every worker must follow)

Derived from `rotrend.py`, the proven reference implementation.

1. **No auth.** These sites' public endpoints; never add login/token handling.
2. **Stdlib + `curl_cffi` only.** `curl_cffi` is installed (0.15.0) and required — plain
   `requests` gets blocked by Cloudflare on these hosts. Use
   `requests.get(url, params=..., headers=..., impersonate="chrome")`.
3. **UTF-8 stdout guard** — mandatory, Windows console is cp1252 and Roblox names
   contain emoji:
   ```python
   try:
       sys.stdout.reconfigure(encoding="utf-8", errors="replace")
       sys.stderr.reconfigure(encoding="utf-8", errors="replace")
   except Exception:
       pass
   ```
4. **`_get` / `_post` helpers** returning parsed dicts; never raise on non-200 — return
   `{"error": status, "detail": text}` like the reference.
5. **Envelope unwrapping** — these sites may wrap payloads in
   `{"success": bool, "message": str, "data": {...}}` (rotrends does). Normalize with a
   `_unwrap()` that raises `ApiError` on `success is False`, and always read
   `payload["data"]` when the envelope is present.
6. **Plain functions returning dicts/lists.** No classes, no global state.
7. **`__main__` CLI** — `argparse`-free, matching the reference: `sys.argv[1]` = command,
   optional `sys.argv[2]` = arg. JSON output via `json.dumps(obj, indent=2,
   ensure_ascii=False)`. Every command prints a human-readable header line first.
8. **Docstrings in French**, module docstring states the API base URL.
9. **No `import base64` unless actually used** (the reference has a vestigial
   base64 fallback — drop it if the API always returns JSON).

---

## API quirks already learned (rotrends → apply the lesson)

- A `sort` parameter must correspond to a field present in the requested `fields` list.
- `POST` endpoints may need params in the **query string** with an **empty JSON body**.
  (rotrends `/games/platform_stats` 500s if the datetimes go in the body.)
- Enum-style route segments: `/explore/games/{group}` where group ∈ `all`,
  `TopTrending`, `UpAndComing`.

## Deliverable contract for B1 / B2

- Module docstring: purpose + base URL + auth note ("aucune authentification requise").
- At least 6 public functions, each returning a plain dict or list of dicts.
- At least 8 CLI commands, each verified against the live site.
- Every function/command must be backed by an endpoint confirmed in the research file.
- Docstring per function stating the endpoint it hits.

## Verification gate (coordinator runs after each worker)

- `py -c "import romonitorstats"` (and `rolimons`) → imports clean, no syntax errors.
- Every CLI command runs with exit code 0 and prints non-empty JSON.
- No tracebacks.
- Spot-check: at least one returned value matches the live site.
