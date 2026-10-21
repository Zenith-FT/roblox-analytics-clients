"""
verify_clients.py — Vérificateur croisé de `romonitorstats.py` et `rolimons.py`.

Pour chaque commande CLI de chaque script :
  * on l'exécute dans un sous-processus (jamais dans le processus courant),
  * on exige un code de sortie == 0,
  * on exige que stdout contienne une charge utile JSON *analysable*,
  * on exige que cette charge utile ne soit *pas vide*.

La liste des commandes n'est PAS codée en dur : elle est lue dans le bloc
`if __name__ == "__main__":` de chaque script (`cmd == "…"`). Les arguments
positionnels attendus par chaque branche sont déduits du même source (on
relit les helpers `_arg` / `_int_arg` / `_text_arg` pour savoir à quelle
position se trouve l'index argv), puis les *valeurs* sont fournies ici —
elles relèvent du domaine, pas du code.

Garde-fous (appris à la dure) :
  * la bannière `=== … ===` est retirée AVANT l'analyse JSON,
  * une charge utile peut être un SCALARE (`"14313917"`, `1737116457`) :
    on ne s'ancre jamais sur `{` ou `[`,
  * l'encodage de sortie est forcé en UTF-8 (`PYTHONIOENCODING`) car la console
    Windows est en cp1252 et les noms de jeux contiennent des emoji,
  * on espace les appels (groupsearch = 20 req/60 s, plafond CF 1015 à ~90 s).

Usage :  py verify_clients.py [--only romonitorstats|rolimons] [--cmd X] [--delay S]
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

# La console Windows est souvent en cp1252 : le tableau ASCII-art et les noms
# de jeux contenant des emoji font planter print(). Même garde-fou que les
# scripts clients.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ─── Valeurs d'appel (domaine : placeId connu, pseudo connu, mot-clé) ────────
# Chaque entrée correspond à une branche du bloc __main__ ; le nombre
# d'arguments est contrôlé automatiquement contre la source (voir _slots).
PLACE_ID = "107778070777162"   # « Steal An Egg » — l'expérience par défaut
GAME_ID = "1537690962"         # jeu Roblox suivi par Rolimons
ITEM_ID = "1029025"            # « The Classic ROBLOX Fedora »
USER_NAME = "builderman"       # compte Roblox n°1

ARGS = {
    "romonitorstats": {
        "homepage":      [],
        "leaderboard":   ["visits", "2"],
        "chart":         ["ccus", PLACE_ID, "14"],
        "genre-chart":   ["genre-ccus", "Simulation", "14"],
        "table":         ["branded-deep-dive"],
        "game-charts":   [PLACE_ID],
        "game":          [PLACE_ID],
        "general":       [PLACE_ID, "24h"],
        "sort":          [PLACE_ID, "top-earning", "1"],
        "sorts":         [],
        "peak":          [PLACE_ID],
        "milestones":    [PLACE_ID, "10"],
        "genre":         ["Simulation"],
        "user":          ["1"],
        "community":     ["1"],
        "search":        ["steal an egg"],
        "card":          [PLACE_ID],
        "gen-chart":     ["visits", PLACE_ID, "14d"],
        "social":        [PLACE_ID],
        "total-visits":  [PLACE_ID, "14"],
        "wallboard":     [PLACE_ID],
        "devex":         [],
        "rates":         [],
    },
    "rolimons": {
        "search":      ["fedora"],
        "item":        [ITEM_ID],
        "value":       [ITEM_ID],
        "history":     [ITEM_ID, "30"],
        "itemsales":   [ITEM_ID, "50"],
        "limiteds":    ["20"],
        "new":         ["20"],
        "categories":  [],
        "rates":       [],
        "changes":     ["50"],
        "catalogue":   [],
        "thumbs":      ["20"],
        "games":       ["20"],
        "gsearch":     ["crossroads"],
        "game":        [GAME_ID, "30"],
        "sales":       ["50"],
        "deals":       ["50"],
        "trades":      ["20"],
        "usersearch":  [USER_NAME],
        "user":        [USER_NAME],
        "inventory":   [USER_NAME, "50"],
        "assets":      ["1", "50"],
        "avatar":      ["1,2,3"],
        "groups":      ["admin"],
    },
}

# Endpoint dont le quota est le plus strict : on lui laisse le temps.
SLOW_COMMANDS = {"rolimons": {"groups"}, "romonitorstats": set()}

DEFAULT_DELAY = {"romonitorstats": 1.2, "rolimons": 2.5}
BACKOFF_429 = 45          # secondes de repli avant UN unique nouvel essai
TIMEOUT = 150             # timeout par commande

# Signatures d'erreurs « l'amont nous bloque » (≠ bug du script).
UPSTREAM_MARKERS = (
    "429", "1015", "too many attempts", "rate limit", "rate-limit",
    "you must be logged in", "403", "cloudflare", "just a moment",
    "retry-after", "service unavailable", "502", "503", "504", "timeout",
)


# ─── 1. Lecture du source : commandes + slots positionnels ───────────────────

def read_source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def main_block(src: str) -> str:
    marker = 'if __name__ == "__main__":'
    idx = src.find(marker)
    if idx < 0:
        raise SystemExit("bloc `if __name__ == \"__main__\":` introuvable")
    return src[idx:]


def extract_commands(src: str):
    """Commandes du bloc __main__, dans l'ordre, sans doublons."""
    out = []
    for m in re.finditer(r'cmd\s*==\s*"([^"]+)"', main_block(src)):
        if m.group(1) not in out:
            out.append(m.group(1))
    return out


def extract_branches(src: str):
    """Branche de code (texte) associée à chaque commande."""
    block = main_block(src)
    marks = [(m.start(), m.group(1))
             for m in re.finditer(r'cmd\s*==\s*"([^"]+)"', block)]
    branches = {}
    for i, (pos, name) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(block)
        branches[name] = block[pos:end]
    return branches


def helper_signature(src: str, name: str):
    """(position du paramètre d'index, {param: défaut}) pour un helper d'args."""
    m = re.search(r"def\s+" + re.escape(name) + r"\s*\(([^)]*)\)", src)
    if not m:
        return None, {}
    params = []
    defaults = {}
    for raw in m.group(1).split(","):
        raw = raw.strip()
        if not raw:
            continue
        if "=" in raw:
            pname, default = raw.split("=", 1)
            pname = pname.split(":")[0].strip()
            defaults[pname] = default.strip()
        else:
            pname = raw.split(":")[0].strip()
        params.append(pname)
    pos = None
    for i, pname in enumerate(params):
        if pname in ("index", "start"):
            pos = i
            break
    return pos, defaults


def _split_args(text: str):
    """Découpe les arguments d'un appel de helper au niveau des virgules."""
    out, depth, cur, in_str = [], 0, "", None
    for ch in text:
        if in_str:
            cur += ch
            if ch == in_str:
                in_str = None
            continue
        if ch in "\"'":
            in_str = ch
            cur += ch
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
            continue
        cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def _iter_calls(body: str, name: str):
    """Parcourt les appels `name(...)` et yield (position, arguments bruts)."""
    for m in re.finditer(r"\b" + re.escape(name) + r"\s*\(", body):
        open_idx = m.end() - 1
        depth, in_str = 0, None
        for i in range(open_idx, len(body)):
            ch = body[i]
            if in_str:
                if ch == in_str:
                    in_str = None
                continue
            if ch in "\"'":
                in_str = ch
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    yield m.start(), body[open_idx + 1:i]
                    break


def _int_or_none(token):
    try:
        return int(str(token).strip().strip("\"'"))
    except (TypeError, ValueError):
        return None


def detect_slots(src: str, branch: str):
    """
    Indices argv utilisés par une branche → nombre de positionnels attendus.
    `argv[2]` = 1er positionnel, `argv[3]` = 2e, etc.
    """
    slots = set()

    # sys.argv[N] et sys.argv[N:]
    for m in re.finditer(r"sys\.argv\[\s*(\d+)\s*[\]:]", branch):
        slots.add(int(m.group(1)))

    # Helpers _arg / _int_arg / _text_arg
    # `_text_arg` peut consommer TOUT le reste de argv (argv[2:] joints par
    # des espaces) : le cas est traité comme un seul positionnel.
    for helper in ("_arg", "_int_arg", "_text_arg"):
        calls = list(_iter_calls(branch, helper))
        if not calls:
            continue
        pos, defaults = helper_signature(src, helper)
        if pos is None:
            # helper sans paramètre d'index : on regarde son corps
            body_m = re.search(r"def\s+" + re.escape(helper) + r"\s*\([^)]*\)[^:]*:(.*?)(?=\n\S|\Z)",
                               src, re.S)
            if body_m:
                for m in re.finditer(r"sys\.argv\[\s*(\d+)\s*[\]:]", body_m.group(1)):
                    slots.add(int(m.group(1)))
            continue
        pnames = re.search(r"def\s+" + re.escape(helper) + r"\s*\(([^)]*)\)", src)
        pnames = [p.split("=")[0].split(":")[0].strip()
                  for p in pnames.group(1).split(",") if p.strip()]
        for _pos, raw_args in calls:
            args = _split_args(raw_args)
            if len(args) > pos:
                value = _int_or_none(args[pos])
            else:
                # paramètre fourni par défaut dans la signature
                value = None
                if pos < len(pnames):
                    value = _int_or_none(defaults.get(pnames[pos], ""))
            if value is not None:
                slots.add(value)

    if not slots:
        return 0
    return max(slots) - 1  # argv[2] → 1 positionnel


# ─── 2. Exécution ────────────────────────────────────────────────────────────

def make_env():
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"   # console Windows en cp1252 → emoji cassés
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def run_script(script: Path, args_list, timeout=TIMEOUT):
    env = make_env()
    cmdline = [sys.executable, str(script), *args_list]
    return subprocess.run(
        cmdline, capture_output=True, text=True, encoding="utf-8",
        errors="replace", env=env, timeout=timeout, cwd=str(HERE),
    )


_FAILED = object()   # sentinelle : distingue « parse raté » de « JSON null »


def extract_payload(stdout: str):
    """
    Retire la bannière `=== … ===` puis analyse le reste en JSON.
    Renvoie (payload, erreur). Un scalaire JSON valide est un payload correct.
    """
    kept = [l for l in (stdout or "").splitlines()
            if not l.lstrip().startswith("===")]
    text = "\n".join(kept).strip()
    if not text:
        return _FAILED, "stdout vide après retrait de la bannière"
    try:
        return json.loads(text), None
    except Exception as exc:                      # noqa: BLE001
        return _FAILED, f"JSON illisible : {exc}"


def payload_size(payload) -> int:
    """Taille « utile » : len() pour liste/dict/str, 1 pour un scalaire."""
    if payload is None:
        return 0                                   # JSON null = charge utile vide
    if isinstance(payload, (dict, list, str)):
        return len(payload)
    return 1


def payload_kind(payload) -> str:
    if isinstance(payload, dict):
        return f"dict({len(payload)})"
    if isinstance(payload, list):
        return f"list({len(payload)})"
    if isinstance(payload, str):
        return f"str({len(payload)})"
    return f"scalaire({payload!r})"


def classify(message: str) -> str:
    """« amont » = l'API nous bloque ; « script » = le code est en cause."""
    low = (message or "").lower()
    if any(marker.lower() in low for marker in UPSTREAM_MARKERS):
        return "amont"
    return "script"


def first_chars(text: str, n: int = 300) -> str:
    text = (text or "").strip()
    return text[:n].replace("\n", " ").replace("\r", " ")


# ─── 3. Boucle de vérification ───────────────────────────────────────────────

class Result:
    def __init__(self, script, command, status, detail, note=""):
        self.script = script
        self.command = command
        self.status = status          # PASS | FAIL
        self.detail = detail
        self.note = note

    @property
    def failed(self):
        return self.status == "FAIL"


def verify_command(script_name, cmd, args, expected_slots, verbose=False):
    """Exécute une commande ; un unique réessai après repli en cas de 429."""
    result = _verify_once(script_name, cmd, args, expected_slots, verbose)
    if result.failed and result.note == "amont bloque l'API" and _looks_rate_limited(result.detail):
        time.sleep(BACKOFF_429)
        result = _verify_once(script_name, cmd, args, expected_slots, verbose)
        result.note = "amont bloque l'API (repli + 1 nouvel essai)"
    return result


def _looks_rate_limited(detail: str) -> bool:
    low = (detail or "").lower()
    return any(k in low for k in ("429", "1015", "trop de requêtes", "too many",
                                  "rate limit", "sending requests too fast"))


def _verify_once(script_name, cmd, args, expected_slots, verbose=False):
    script = HERE / f"{script_name}.py"
    cmdline = [cmd, *args]
    try:
        proc = run_script(script, cmdline)
    except subprocess.TimeoutExpired:
        return Result(script_name, cmd, "FAIL", f"timeout > {TIMEOUT}s",
                      "script ? (délai dépassé)")
    except Exception as exc:                      # noqa: BLE001
        return Result(script_name, cmd, "FAIL", f"{type(exc).__name__}: {exc}", "script")

    stdout, stderr = proc.stdout or "", proc.stderr or ""

    if proc.returncode != 0:
        payload, _ = extract_payload(stdout)
        message = ""
        if isinstance(payload, dict) and payload.get("error"):
            message = str(payload["error"])
        elif stderr:
            message = first_chars(stderr)
        else:
            message = first_chars(stdout)
        kind = classify(message)
        note = "amont bloque l'API" if kind == "amont" else "bug du script ?"
        detail = f"exit={proc.returncode} · {first_chars(message, 200)}"
        return Result(script_name, cmd, "FAIL", detail, note)

    payload, err = extract_payload(stdout)
    if payload is _FAILED:
        note = "bug du script ?" if classify(err) == "script" else "amont bloque l'API"
        return Result(script_name, cmd, "FAIL", f"{err} · stdout={first_chars(stdout)}", note)

    if isinstance(payload, dict) and payload.get("error"):
        message = str(payload["error"])
        kind = classify(message)
        note = "amont bloque l'API" if kind == "amont" else "bug du script ?"
        return Result(script_name, cmd, "FAIL", f"payload d'erreur : {first_chars(message, 200)}",
                      note)

    size = payload_size(payload)
    if size == 0:
        return Result(script_name, cmd, "FAIL",
                      f"charge utile vide ({payload_kind(payload)})", "à vérifier")

    detail = payload_kind(payload)
    if expected_slots is not None:
        detail += f" · args={expected_slots}"
    if verbose:
        detail += f" · {first_chars(stdout, 120)}"
    return Result(script_name, cmd, "PASS", detail, "")


def verify_help(script_name):
    """`py <script>` sans argument doit afficher l'usage et sortir en 0."""
    script = HERE / f"{script_name}.py"
    try:
        proc = run_script(script, [])
    except Exception as exc:                      # noqa: BLE001
        return Result(script_name, "<aide>", "FAIL", f"{type(exc).__name__}: {exc}", "script")
    out = proc.stdout or ""
    if proc.returncode != 0:
        return Result(script_name, "<aide>", "FAIL", f"exit={proc.returncode}", "script")
    if "Usage" not in out:
        return Result(script_name, "<aide>", "FAIL", "bloc d'usage absent", "script")
    return Result(script_name, "<aide>", "PASS", f"usage affiché ({len(out)} car.)", "")


def main():
    ap = argparse.ArgumentParser(description="Vérificateur des clients Roblox")
    ap.add_argument("--only", choices=sorted(ARGS), help="ne vérifier qu'un script")
    ap.add_argument("--cmd", help="ne vérifier qu'une commande (dans tous les scripts)")
    ap.add_argument("--delay", type=float, default=None,
                    help="pause entre deux commandes (s)")
    ap.add_argument("--verbose", action="store_true", help="extrait de stdout dans le tableau")
    ap.add_argument("--list", action="store_true", help="lister les commandes détectées et sortir")
    args = ap.parse_args()

    scripts = [args.only] if args.only else list(ARGS)
    plan = []
    for name in scripts:
        src = read_source(HERE / f"{name}.py")
        commands = extract_commands(src)
        branches = extract_branches(src)
        plan.append((name, src, commands, branches))

    if args.list:
        for name, _src, commands, _branches in plan:
            print(f"{name} : {len(commands)} commandes")
            for c in commands:
                print(f"  - {c}")
        return 0

    results = []
    for name, src, commands, branches in plan:
        results.append(verify_help(name))
        specs = ARGS.get(name, {})
        for cmd in commands:
            if args.cmd and cmd != args.cmd:
                continue
            if cmd not in specs:
                results.append(Result(name, cmd, "FAIL",
                                      "aucun jeu d'arguments défini pour cette commande",
                                      "à vérifier"))
                continue
            values = specs[cmd]
            slots = detect_slots(src, branches.get(cmd, ""))
            if slots != len(values):
                results.append(Result(name, cmd, "FAIL",
                                      f"incohérence : la branche attend {slots} argument(s), "
                                      f"le test en fournit {len(values)}",
                                      "à vérifier"))
                continue
            if cmd in SLOW_COMMANDS.get(name, set()):
                time.sleep(BACKOFF_429 / 3)         # marge avant un endpoint strict
            results.append(verify_command(name, cmd, values, slots, args.verbose))
            delay = args.delay if args.delay is not None else DEFAULT_DELAY.get(name, 1.5)
            time.sleep(delay)

    # ── tableau ──────────────────────────────────────────────────────────────
    width_script = max(max(len(r.script) for r in results), len("Script")) + 2
    width_cmd = max(max(len(r.command) for r in results), len("Commande")) + 2
    width_status = max(11, len("Résultat") + 1)
    width_detail = max(max(len(r.detail) for r in results), len("Détail")) + 2
    inner = width_script + width_cmd + width_status + width_detail

    def line(script, cmd, status, detail):
        return ("│ " + script.ljust(width_script) + cmd.ljust(width_cmd)
                + status.ljust(width_status) + detail.ljust(width_detail) + "│")

    print()
    print("┌" + "─" * inner + "┐")
    print(line("Script", "Commande", "Résultat", "Détail"))
    print("├" + "─" * inner + "┤")
    for r in results:
        status = "PASS" if r.status == "PASS" else "FAIL"
        print(line(r.script, r.command, status, r.detail))
        if r.note:
            print("│ " + " " * (width_script + width_cmd + width_status)
                  + r.note.ljust(width_detail) + "│")
    print("└" + "─" * inner + "┘")

    failed = [r for r in results if r.failed]
    print()
    print(f"{len(results) - len(failed)}/{len(results)} commandes OK, {len(failed)} en échec.")
    if failed:
        print()
        print("Échecs (commande · code · sortie) :")
        for r in failed:
            print(f"  - {r.script} {r.command} : {r.detail} [{r.note}]")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
