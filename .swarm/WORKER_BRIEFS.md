# Worker Briefs — ready to fire

Both briefs share the same shared_context. **B1 and B2 must be spawned in a SINGLE
message** so they run in parallel. Each worker owns exactly ONE file — no overlap.

---

## B1 — Build `romonitorstats.py`

**Owns (exclusive):** `C:\Users\Zenith\Tools\roblox-scripting\romonitorstats.py`
**Reads:** `rotrend.py`, `.swarm/BLUEPRINT.md`, `.research/romonitorstats.md`
**Writes:** only `romonitorstats.py`

### Prompt

```
You are worker B1 in a swarm. Build ONE file: romonitorstats.py

## Your exclusive file (do not create/modify any other file)
C:\Users\Zenith\Tools\roblox-scripting\romonitorstats.py

## Read these first (in this order)
1. C:\Users\Zenith\Tools\roblox-scripting\rotrend.py
   The PROVEN reference implementation. Mirror its conventions exactly.
2. C:\Users\Zenith\Tools\roblox-scripting\.swarm\BLUEPRINT.md
   Sections 1 (skeleton - copy it), 1.1 (deliberate deviations - keep them),
   2.1 (your per-site checklist), 4 (verification checklist), 5 (pitfalls).
3. C:\Users\Zenith\Tools\roblox-scripting\.research\romonitorstats.md
   The live API map, produced by a research agent. EVERY endpoint you expose MUST
   come from this file. If it lists an endpoint you cannot make work, say so in
   your final report rather than inventing a substitute.

## What to build
A standalone, self-contained Python client for https://romonitorstats.com/ that
looks and behaves like rotrend.py: no auth, plain functions returning dicts/lists,
a `__main__` CLI with JSON output.

Use the skeleton from BLUEPRINT section 1 as your base, with the per-site
substitutions from section 2.1. Implement the 13 functions and 12 CLI commands
listed in BLUEPRINT section 2.1 — but ONLY those whose endpoint is confirmed in
.research/romonitorstats.md. If the research found different or better endpoints,
use the research as the source of truth and adapt the function list accordingly.

## Non-negotiable conventions
- `curl_cffi` only (plain `requests` gets Cloudflare-blocked on these hosts).
  `requests.get(url, params=..., headers=BASE_HEADERS, impersonate="chrome")`
- The UTF-8 stdout guard must be the first thing after the imports.
- Every public function wraps its HTTP call in `_check(_get(...))` / `_check(_post(...))`.
- French docstrings. Each function's docstring states its endpoint.
- Optional filters are only added to `params` when not None.
- CLI: `sys.argv[1]` = command, `sys.argv[2:]` = args (use `_text_arg` so
  "search dead rails" works as one argument).
- Every CLI branch prints a human-readable header line, then `pp(...)` JSON.
- An unknown command prints the usage block.
- On ApiError: print `{"error": ...}` and `sys.exit(1)`. NEVER a traceback.

## Reviewer corrections to the blueprint — apply these
1. ADD a request timeout. The skeleton has none, and a hung connection blocks
   the CLI forever. Use `requests.get(url, params=..., headers=..., timeout=30,
   impersonate="chrome")`. Apply to both _get and _post.
2. `_unwrap()` treats `status in ("error","failed","failure")` as a failure. If the
   real romonitorstats payload uses `status` with a different meaning, narrow that
   check to only what the research file documents. Do not let a legit data payload
   raise.
3. `_check()` treats ANY `"error"` key in the payload as a failure. If a real
   endpoint legitimately returns an `error` field as data, restrict the check to
   the error-dict shape you produce yourself in _get/_post (e.g. use a distinct
   key like `"__http_error__"` instead of `"error"`).
4. If the research shows the API returns bare JSON arrays, `_data()` must not
   mangle them — verify with real calls.

## Verification gate — you must run these and PASS them before reporting done
Run from C:\Users\Zenith\Tools\roblox-scripting\ :
  py -m py_compile romonitorstats.py
  py romonitorstats.py                      # usage block, exit 0
  py romonitorstats.py <every command>      # each: exit 0, prints non-empty JSON
Then confirm at least 3 commands return REAL data (not empty lists) and that the
values match what you saw in .research/romonitorstats.md.
Also verify a failure path exits 1 with no traceback.

## Report back (concise, max 15 lines)
- the command list you implemented
- which research endpoints you could NOT make work, and why
- the verification output summary (how many commands passed / failed)
- any deviation from the blueprint and its reason
Do not paste the file back.
```

---

## B2 — Build `rolimons.py`

**Owns (exclusive):** `C:\Users\Zenith\Tools\roblox-scripting\rolimons.py`
**Reads:** `rotrend.py`, `.swarm/BLUEPRINT.md`, `.research/rolimons.md`
**Writes:** only `rolimons.py`

### Prompt

```
You are worker B2 in a swarm. Build ONE file: rolimons.py

## Your exclusive file (do not create/modify any other file)
C:\Users\Zenith\Tools\roblox-scripting\rolimons.py

## Read these first (in this order)
1. C:\Users\Zenith\Tools\roblox-scripting\rotrend.py
   The PROVEN reference implementation. Mirror its conventions exactly.
2. C:\Users\Zenith\Tools\roblox-scripting\.swarm\BLUEPRINT.md
   Sections 1 (skeleton - copy it), 1.1 (deliberate deviations - keep them),
   2.2 (your per-site checklist), 4 (verification checklist), 5 (pitfalls).
3. C:\Users\Zenith\Tools\roblox-scripting\.research\rolimons.md
   The live API map, produced by a research agent. EVERY endpoint you expose MUST
   come from this file. If it lists an endpoint you cannot make work, say so in
   your final report rather than inventing a substitute.

## What to build
A standalone, self-contained Python client for https://www.rolimons.com/ that
looks and behaves like rotrend.py: no auth, plain functions returning dicts/lists,
a `__main__` CLI with JSON output.

Use the skeleton from BLUEPRINT section 1 as your base, with the per-site
substitutions from section 2.2. Implement the 12 functions and 12 CLI commands
listed in BLUEPRINT section 2.2 — but ONLY those whose endpoint is confirmed in
.research/rolimons.md. If the research found different or better endpoints, use
the research as the source of truth and adapt the function list accordingly.

## Special case for this site
Rolimons may serve HTML pages that embed JSON in a <script> tag rather than
returning a JSON API. If the research found that:
  - implement a small, clearly-named parser helper (e.g. `_extract_embedded_json(html)`)
    that pulls the documented variable out of the HTML, and
  - document the exact variable name and regex in the module docstring,
  - and still return plain dicts from every public function.
Do not return raw HTML strings to the caller.

## Non-negotiable conventions
- `curl_cffi` only (plain `requests` gets Cloudflare-blocked on these hosts).
  `requests.get(url, params=..., headers=BASE_HEADERS, impersonate="chrome")`
- The UTF-8 stdout guard must be the first thing after the imports.
- Every public function wraps its HTTP call in `_check(_get(...))` / `_check(_post(...))`.
- French docstrings. Each function's docstring states its endpoint.
- Optional filters are only added to `params` when not None.
- CLI: `sys.argv[1]` = command, `sys.argv[2:]` = args (use `_text_arg` so
  "search fat cat" works as one argument).
- Every CLI branch prints a human-readable header line, then `pp(...)` JSON.
- An unknown command prints the usage block.
- On ApiError: print `{"error": ...}` and `sys.exit(1)`. NEVER a traceback.

## Reviewer corrections to the blueprint — apply these
1. ADD a request timeout. The skeleton has none, and a hung connection blocks
   the CLI forever. Use `requests.get(url, params=..., headers=..., timeout=30,
   impersonate="chrome")`. Apply to both _get and _post.
2. `_unwrap()` treats `status in ("error","failed","failure")` as a failure. If the
   real rolimons payload uses `status` with a different meaning, narrow that
   check to only what the research file documents. Do not let a legit data payload
   raise.
3. `_check()` treats ANY `"error"` key in the payload as a failure. If a real
   endpoint legitimately returns an `error` field as data, restrict the check to
   the error-dict shape you produce yourself in _get/_post (e.g. use a distinct
   key like `"__http_error__"` instead of `"error"`).
4. If the research shows the API returns bare JSON arrays, `_data()` must not
   mangle them — verify with real calls.
5. If a rate limit (429) is hit, do NOT hammer the endpoint. Back off and note it.

## Verification gate — you must run these and PASS them before reporting done
Run from C:\Users\Zenith\Tools\roblox-scripting\ :
  py -m py_compile rolimons.py
  py rolimons.py                      # usage block, exit 0
  py rolimons.py <every command>      # each: exit 0, prints non-empty JSON
Then confirm at least 3 commands return REAL data (not empty lists) and that the
values match what you saw in .research/rolimons.md.
Also verify a failure path exits 1 with no traceback.

## Report back (concise, max 15 lines)
- the command list you implemented
- which research endpoints you could NOT make work, and why
- the verification output summary (how many commands passed / failed)
- any deviation from the blueprint and its reason
Do not paste the file back.
```

---

## B3 — Cross-verify + README (spawns AFTER B1 and B2 both complete)

**Owns (exclusive):** `C:\Users\Zenith\Tools\roblox-scripting\README.md`,
`C:\Users\Zenith\Tools\roblox-scripting\verify_clients.py`
**Reads:** everything.

### Prompt

```
You are worker B3 in a swarm. Two sibling workers just built romonitorstats.py and
rolimons.py. Your job is to VERIFY them and write the README.

## Your exclusive files (create/modify ONLY these two)
C:\Users\Zenith\Tools\roblox-scripting\README.md
C:\Users\Zenith\Tools\roblox-scripting\verify_clients.py
Do NOT edit romonitorstats.py, rolimons.py, or rotrend.py — if you find a bug in
them, REPORT it, do not fix it. (The coordinator will dispatch a fix cell.)

## Step 1 — write verify_clients.py
A standalone script that, for each of the two clients:
  - imports the module
  - runs EVERY CLI command as a subprocess (`py <script> <cmd> [arg]`)
  - asserts exit code == 0
  - asserts stdout contains a parseable JSON payload
  - asserts the payload is not empty (non-empty list / non-empty dict with content)
  - prints a per-command PASS/FAIL table and exits 1 if any command fails
Use `subprocess.run` with `capture_output=True, text=True, encoding="utf-8"`.
Note: on Windows, set `PYTHONIOENCODING=utf-8` in the subprocess env, or the
emoji in Roblox names will break the pipe.

## Step 2 — run it, and report honestly
Do not paper over failures. For each failing command: the command, the exit code,
and the first 300 chars of stderr/stdout. If a command legitimately cannot work
(a site blocking us, a rate limit), say so explicitly and distinguish
"script bug" from "upstream blocks us".

## Step 3 — write README.md
Document:
  - what each script does, the API base URL, and that NO AUTH is required
  - the full command list for both scripts with a one-line description each
  - 3-5 copy-pasteable usage examples per script
  - the "quirks" section: the non-obvious API behaviours (sort-must-be-in-fields,
    POST query-string-vs-body, enum route segments, embedded-JSON parsing, etc.)
    — only the ones you actually observed
  - how to run the verifier
  - a note that these are read-only public endpoints and to respect rate limits
Use French, matching the scripts' docstrings. Include the ASCII art style block
the project uses.

## Report back (concise, max 15 lines)
- the PASS/FAIL table
- any script bugs found (file + line + what breaks) — DO NOT FIX THEM
- confirmation the README was written
```

---

## Spawn order

1. Spawn B1 and B2 **in the same message** (two `subagent` calls, background=true).
2. Monitor. Both write to disjoint files — no conflict possible.
3. When BOTH complete: review each (read the file, run the verifier's checks
   manually for a sample), then spawn B3.
4. B3 writes README.md + verify_clients.py.
5. Coordinator: run the verifier, commit, produce the final ASCII summary.

## Skills to recommend to workers

Workers should load these before starting (via the `skill` tool):
- `cli-builder` — for the CLI structure and output formatting
- `testing-patterns` — for the verification gate
- `system-design` — only if they need to decide on an abstraction

## Shared context (append to both B1 and B2 prompts)

```
## Project
Directory: C:\Users\Zenith\Tools\roblox-scripting\
Reference implementation: rotrend.py (439 lines) — the proven, working client for
rotrends.com. Mirror its structure, naming, French docstring style and CLI shape.

## Environment
- Python 3.14.5 at C:\Users\Zenith\AppData\Local\Python\pythoncore-3.14-64\python.exe
- `py` is the launcher on this machine.
- curl_cffi 0.15.0 installed. requests 2.31.0 installed but MUST NOT be used
  (Cloudflare blocks it on these hosts).
- Windows console default encoding is cp1252 -> the UTF-8 stdout guard is mandatory.

## Constraints
- Both scripts are STANDALONE and self-contained: no shared module, no import
  coupling between them, no imports from rotrend.py. Copy what you need.
- No authentication, no tokens, no login flow. These are public endpoints.
- Read-only. Never POST anything that mutates data.

## Git
Branch: swarm/roblox-analytics-clients (already checked out).
Do NOT run git commands. The coordinator commits. Just write your file.
```
