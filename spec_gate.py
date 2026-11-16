"""Caso 7: gate de specs antes de escribir (PreToolUse de Claude Code).

Lee el JSON del hook en stdin. Primero los chequeos deterministas (archivo de gobierno,
credenciales por regex), y solo si pasan, una pregunta `noul` por regla de `specs.md`.

  >= 0.8  deny   la escritura no llega al disco
  >= 0.5  ask    se pregunta a la persona
  resto   abstención: la llamada sigue el flujo normal de permisos

Cada decisión se anota en `.jev_audit.jsonl` (al lado de este script).

Uso:  py -3 spec_gate.py --self-check   (o sin argumentos, como hook)
"""

import json
import os
import re
import sys
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

import jev  # noqa: E402
from jev import JevApagado, ask  # noqa: E402
from rule_coverage import rules as spec_rules  # noqa: E402

BLOCK, ASK = 0.8, 0.5
SPECS = os.path.join(AQUI, "specs.md")
AUDIT = os.path.join(AQUI, ".jev_audit.jsonl")
EXT = {e.strip() if e.strip().startswith(".") else "." + e.strip()
       for e in os.environ.get("JEV_EXT", ".py").split(",") if e.strip()}
GOBIERNO = ("specs.md", ".claude/settings.json")
MAX_CODE = 20000

# ponytail: un regex cubre las credenciales; si se necesitan más patrones, se suman aquí
SECRETOS = re.compile(
    r"sk_live_[A-Za-z0-9]{8,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY|password\s*=\s*['\"][^'\"]+['\"]"
)


def _log(entry):
    try:
        with open(AUDIT, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **entry},
                               ensure_ascii=False) + "\n")
    except OSError:
        pass


def _resultante(ti):
    """Para Edit: el archivo tal como quedará, recortado alrededor del cambio."""
    nuevo = ti.get("new_string") or ""
    viejo = ti.get("old_string") or ""
    try:
        with open(ti["file_path"], encoding="utf-8", errors="ignore") as f:
            base = f.read()
    except (OSError, KeyError):
        return nuevo[:MAX_CODE]
    if viejo and viejo in base:
        out = base.replace(viejo, nuevo, -1 if ti.get("replace_all") else 1)
    else:
        out = nuevo
    if len(out) <= MAX_CODE:
        return out
    i = out.find(nuevo) if nuevo else 0
    return out[max(0, i - 3000):max(0, i - 3000) + MAX_CODE]


def decidir(code, path, tool="Write", extra=None):
    """Devuelve dict de decisión o None para abstenerse."""
    entry = {"file": path, "tool": tool, **(extra or {})}

    if any(path.endswith("/" + g) for g in GOBIERNO):
        reason = "Archivo de gobierno: el agente no edita specs.md ni la configuración de hooks."
        _log({**entry, "decision": "deny", "rule": "gobierno", "p": 1.0})
        return {"permissionDecision": "deny", "permissionDecisionReason": reason}

    if SECRETOS.search(code):
        reason = ("Regla Credenciales: el bloque escribe una credencial literal. "
                  "Léela de una variable de entorno.")
        _log({**entry, "decision": "deny", "rule": "credenciales", "p": 1.0})
        return {"permissionDecision": "deny", "permissionDecisionReason": reason}

    rs = spec_rules(SPECS)
    if not rs:
        return None
    qs = {r["id"]: {"type": "noul", "instructions":
                    f"¿El código de `proposed_code` viola lo que manda la regla `rules[{i}]` "
                    f"({r['title']})?"}
          for i, r in enumerate(rs)}
    ans = ask({"file": path, "operation": tool, "proposed_code": code[:MAX_CODE], "rules": rs}, qs)
    hits = {k: v["value"] for k, v in ans.items()}
    top = max(hits, key=hits.get)
    regla = next((r for r in rs if r["id"] == top), {"title": top, "text": ""})
    decision = "deny" if hits[top] >= BLOCK else "ask" if hits[top] >= ASK else "abstain"
    _log({**entry, "decision": decision, "rule": regla["title"],
          "p": round(hits[top], 3), "model": jev.ULTIMO_MODELO})
    if decision == "abstain":
        return None
    texto = regla.get("text", "")[:300]
    return {"permissionDecision": decision,
            "permissionDecisionReason":
                f"Regla {regla['title']} (p={hits[top]:.2f}): {texto} "
                f"Reescribe el bloque para cumplirla."}


def _self_check():
    credencial = repr("sk_" + "live_" + "51H9xQ2fake")
    viola = "API_KEY = " + credencial + "\ndef cobrar():\n    return post(API_KEY)\n"
    limpio = ('def monto(texto: str) -> int:\n'
              '    """Convierte "12.50" en 1250 centavos, validando primero."""\n'
              '    if not texto.strip():\n'
              '        raise ValueError("monto vacío")\n'
              '    return round(float(texto) * 100)\n')
    duplicado = ("import urllib.request\n"
                 "def pedir(state, qs):\n"
                 "    req = urllib.request.Request('https://api.typesafe.ai/v1/systemone')\n"
                 "    return req\n")
    casos = [("credencial", viola, "src/demo.py", "deny"),
             ("limpio", limpio, "src/demo.py", None),
             ("http propio", duplicado, "src/demo.py", "deny"),
             ("gobierno", "x = 1\n", "C:/p/proj/specs.md", "deny")]
    malos = []
    for label, code, path, want in casos:
        d = decidir(code, path)
        got = d and d["permissionDecision"]
        print(f"{label:12} {str(got):5} {(d['permissionDecisionReason'][:55] if d else '')}")
        if got != want:
            malos.append((label, want, d))

    # un Edit que borra un control no puede pasar como "texto vacío"
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write("def cobrar(x):\n    if x <= 0:\n        raise ValueError\n    return x\n")
        path = f.name
    out = _resultante({"file_path": path, "old_string": "    if x <= 0:\n        raise ValueError\n",
                       "new_string": ""})
    os.unlink(path)
    print("resultante:", repr(out[:40]))
    assert "raise ValueError" not in out, out
    assert not malos, malos


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
        print("OK")
        sys.exit(0)
    datos = json.load(sys.stdin)
    ti = datos.get("tool_input", {})
    path = (ti.get("file_path") or "").replace("\\", "/")
    if any(path.endswith("/" + g) for g in GOBIERNO):
        # va antes del filtro de extensión: specs.md es .md y aun así se protege
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", **decidir("", path)}}))
        sys.exit(0)
    if os.path.splitext(path)[1] not in EXT:
        sys.exit(0)
    code = ti.get("content") if datos.get("tool_name") == "Write" else _resultante(ti)
    code = code or ""
    if not code.strip():
        sys.exit(0)
    try:
        out = decidir(code, path, datos.get("tool_name", "Write"),
                      {"session": datos.get("session_id")})
    except JevApagado as e:  # sin saldo: se avisa y se deja seguir
        print(json.dumps({"systemMessage": str(e).splitlines()[0]}))
        sys.exit(0)
    except Exception as e:  # fail-open: un blip de red no puede bloquear escrituras
        print(f"spec_gate: no se pudo evaluar ({e}); se deja pasar", file=sys.stderr)
        sys.exit(0)
    if out:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", **out}}))
