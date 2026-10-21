# B3 brief — cross-verify both clients + write the README

Spawn **after** B1 and B2 are final. B3 owns exactly two files:
`C:\Users\Zenith\Tools\roblox-scripting\README.md`
`C:\Users\Zenith\Tools\roblox-scripting\verify_clients.py`

B3 must **NOT** edit `romonitorstats.py`, `rolimons.py` or `rotrend.py` — if it finds a
bug in them it REPORTS it, it does not fix it. The coordinator dispatches a fix cell.

---

## 1. `verify_clients.py` — the standalone verifier

For each of `romonitorstats.py` and `rolimons.py`:

- run every CLI command as a subprocess
- assert exit code == 0
- assert stdout contains a **parseable JSON payload**
- assert the payload is **not empty**
- print a per-command PASS/FAIL table; exit 1 if any command fails

### Harness rules learned the hard way — follow these exactly

1. **Strip the header line.** Every command prints a human-readable banner first:
   `=== Recherche objet : 'fedora' ===`. Only the lines after it are JSON.
   Filter with `not l.lstrip().startswith("===")`.
2. **The JSON payload can be a SCALAR.** Three romonitorstats commands return a bare
   value, not an object:
   - `peak` → `"14313917"` (a JSON string)
   - `genre` → `"136837926908"` (a JSON string)
   - `total-visits` → `1737116457` (a JSON number)

   So **do not anchor the parse on `{` or `[`** — that produces false failures on
   exactly those three. Parse the whole remaining text with `json.loads()` and treat
   a valid scalar as a non-empty result. Use `len()` for list/dict, and count a
   scalar as 1.
3. **Force UTF-8 in the subprocess.** Set `env["PYTHONIOENCODING"] = "utf-8"` and pass
   `encoding="utf-8"` to `subprocess.run`. Roblox names contain emoji
   (`Brookhaven 🏡RP`, `PIGU 🔴`) and the default Windows cp1252 pipe corrupts them.
4. Use `subprocess.run([sys.executable, "<script>", "<cmd>", ...], capture_output=True,
   text=True, encoding="utf-8", env=env)`.
5. **Do not hardcode a command list from memory — read it from the source.** Parse the
   `__main__` block of each script for the `cmd == "..."` branches to get the exact
   command names, and read each branch to work out which positional argument it
   expects. Then supply sensible arguments (a known game id, a known username, a
   search term) so the command returns real data rather than an error.
6. **Rate limits.** rolimons `groups/v1/groupsearch` is 20 req/60 s and escalates to a
   Cloudflare 1015 hard block (~90 s). The clients already pace themselves, but do not
   add a loop that hammers it. If you hit a 429, back off and report it rather than
   retrying hard.
7. Report a failure as **"script bug"** vs **"upstream blocks us"** — they are not the
   same thing and the coordinator needs the distinction.

## 2. `README.md`

French (the scripts' docstrings are French). Sections:

1. **What it is** — one short paragraph per script, the API base URL, and the key
   fact that **no authentication is required**: these are public endpoints.
2. **Command list** — every command of both scripts, one line each. Use the real
   output of `py romonitorstats.py` and `py rolimons.py` (the usage blocks).
3. **Usage examples** — 3-5 copy-pasteable commands per script, with a one-line
   expected result.
4. **Quirks** — only the ones actually observed, each with the concrete symptom:
   - romonitorstats: 14-day window cap for anonymous users; Laravel CSRF handshake
     for POSTs; query string wins over the JSON body; `ends` not `end`; camelCase
     params; `stats/charts/get/` ignores `name`; `search/experience-preload/` ignores
     `term` (search goes through the Meilisearch host); rate limit 80/min
   - rolimons: the real API is on `api.rolimons.com`, **not** `www.rolimons.com/api`
     (that whole namespace is dead); the catalogue endpoints ignore `id`/`limit` and
     always return everything, so filtering is client-side; items arrive as 9-element
     arrays and `/catalog` as 26-element arrays; the rich per-item data is JSON
     embedded in HTML pages; `/player/<id>` needs navigation-style headers or
     Cloudflare serves "Just a moment…"; rate limit 20/60 s on groupsearch
   - both: the Windows console is cp1252, hence the UTF-8 guard in every script
5. **How to run the verifier** — `py verify_clients.py`.
6. **Ethics / rate limits** — read-only public endpoints, respect the limits, don't
   hammer.
7. Add a small ASCII-art block (the project style: `┌ ─ ┐ │ └ ┘`) summarising the
   three scripts and what each one covers.

## 3. Report back (max 15 lines)

- the PASS/FAIL table
- any **script bug** found (file + line + what breaks) — DO NOT FIX
- any command that legitimately returns empty, and why
- confirmation the README was written
