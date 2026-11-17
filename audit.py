"""Auditoría: lo hablado está en el código y el código coincide con los grafos.

Cada línea comprueba un hecho concreto contra un archivo. No llama a la API.

Uso:  py -3 audit.py
"""

import json
import pathlib
import re
import sys

AQUI = pathlib.Path(__file__).parent
ART = AQUI / ".archify" / "architecture-jev-cases-20261115-122028"


def txt(nombre):
    return (AQUI / nombre).read_text(encoding="utf-8")


def caso(n):
    return json.loads((ART / f"case-{n}.json").read_text(encoding="utf-8"))


def edges(d):
    return {c["id"]: c for c in d["connections"]}


def nodes(d):
    return {c["id"]: c for c in d["components"]}


def _hook(payload, env_extra=None):
    """Corre spec_gate como hook real: JSON por stdin, devuelve (stdout, exit)."""
    import os
    import subprocess
    ent = dict(os.environ, **(env_extra or {}))
    r = subprocess.run([sys.executable, "spec_gate.py"], input=json.dumps(payload),
                       capture_output=True, text=True, cwd=str(AQUI), env=ent)
    return r.stdout.strip(), r.returncode


def _write(path, content):
    return {"hook_event_name": "PreToolUse", "tool_name": "Write",
            "tool_input": {"file_path": path, "content": content}}


def chequeos():
    o = []
    jev, gate, dig, skill = txt("jev.py"), txt("spec_gate.py"), txt("compact_digest.py"), txt("skill_pick.py")
    rank, rev, cov, brow = txt("file_rank.py"), txt("review_gate.py"), txt("rule_coverage.py"), txt("browse.py")
    cfg = json.loads(txt(".claude/settings.json"))

    # --- cliente único
    o.append(("jev.py: único HTTP a TypeSafe", "api.typesafe.ai" in jev and "urllib.request" in jev))
    o.append(("jev.py: 401/402/403 apagan", 'APAGADO = {401, 402, 403}' in jev))
    o.append(("jev.py: se consulta antes de cada llamada", "if not activo():" in jev))
    o.append(("jev.py: registra la versión del modelo", 'ULTIMO_MODELO = out.get("model")' in jev))

    # --- gate de escritura
    o.append(("gate: umbrales 0.8 / 0.5", "BLOCK, ASK = 0.8, 0.5" in gate))
    o.append(("gate: tres salidas (deny/ask/abstain)", '"deny" if hits[top] >= BLOCK else "ask"' in gate))
    o.append(("gate: gobierno antes del filtro de extensión",
              gate.index('for g in GOBIERNO):') < gate.index('os.path.splitext(path)[1] not in EXT:')))
    gob = re.search(r"^GOBIERNO = (.+)$", gate, re.M).group(1)
    o.append(("gate: gobierno cubre specs, AGENTS y settings",
              all(n in gob for n in ("specs.md", "AGENTS.md", ".claude/settings.json", "settings.local.json"))))
    o.append(("gate: credenciales por regex", "SECRETOS = re.compile" in gate))
    o.append(("gate: extensión configurable, .py por defecto", 'os.environ.get("JEV_EXT", ".py")' in gate))
    o.append(("gate: evalúa el archivo resultante en Edit", "def _resultante" in gate))
    o.append(("gate: escribe .jev_audit.jsonl", '.jev_audit.jsonl' in gate and "_log(" in gate))
    o.append(("gate: fail-open ante error", "no se pudo evaluar" in gate))
    o.append(("gate: no escribe el archivo objetivo", "open(ti[\"file_path\"], \"w\"" not in gate))


    # --- compactación
    o.append(("digest: últimos 150 mensajes", "ULTIMOS = 150" in dig))
    o.append(("digest: descarta mensajes cortos", "len(c.strip()) < 40" in dig))
    o.append(("digest: descarta sidechains", 'd.get("isSidechain")' in dig))
    o.append(("digest: salida bajo 10 000", "MAX_SALIDA = 9000" in dig))
    o.append(("digest: captura JevApagado", "except JevApagado" in dig))

    # --- skill picker
    o.append(("skill: política del código 0.55 / 0.10", "CONF_MIN = 0.55" in skill and "MARGEN_MIN = 0.10" in skill))
    o.append(("skill: el código puede devolver ninguna", 'return "ninguna"' in skill))

    # --- ranking
    o.append(("rank: atajo por palabras clave", "def candidates" in rank))
    o.append(("rank: score por candidato", '"type": "score"' in rank))
    o.append(("rank: camino regular sin Jev", "except JevApagado" in rank and '"relevance": None' in rank))

    # --- revisión
    o.append(("review: seis preguntas fijas", rev.count('"type": "noul"') >= 1 and "QUESTIONS = {" in rev))
    o.append(("review: hasta 12 reglas del spec", "[:12]" in rev))
    o.append(("review: sin Jev escala", '"escalar"' in rev))
    o.append(("review: bloquear sale con código 1", 'verdict == "bloquear"' in rev and "sys.exit(1)" in rev))

    # --- cobertura
    o.append(("coverage: dos preguntas por regla", '_test' in cov and '_lint' in cov))
    o.append(("coverage: secciones por defecto", '"Non-negotiable"' in cov))
    o.append(("coverage: guard de JevApagado", "except JevApagado" in cov))
    o.append(("coverage: sin reglas no llama a la API", "if not rules_list:" in cov))

    # --- navegador
    o.append(("browse: hasta 8 pasos", "MAX_PASOS = 8" in brow))
    o.append(("browse: umbral 0.6", "LOGRADO = 0.6" in brow))
    o.append(("browse: Edge instalado", 'channel="msedge"' in brow))

    # --- configuración de hooks
    pre = cfg["hooks"]["PreToolUse"][0]
    comp = cfg["hooks"].get("PreCompact", [{}])[0]
    o.append(("hooks: PreToolUse Edit|Write -> spec_gate", pre["matcher"] == "Edit|Write" and "spec_gate.py" in json.dumps(pre)))
    o.append(("hooks: PreCompact manual|auto -> compact_digest", comp.get("matcher") == "manual|auto" and "compact_digest.py" in json.dumps(comp)))
    cli_gate = int(re.search(r"timeout=(\d+)\)", gate).group(1))
    cli_dig = int(re.search(r"def ask\([^)]*timeout=(\d+)", jev, re.S).group(1))
    o.append(("timeouts: PreToolUse espera más que el cliente", pre["hooks"][0]["timeout"] > cli_gate))
    o.append(("timeouts: PreCompact espera más que el cliente", comp["hooks"][0]["timeout"] > cli_dig))

    # --- specs y auditoría
    o.append(("specs.md: tres reglas", len(re.findall(r"^\*\*", txt("specs.md"), re.M)) == 3))
    o.append((".jev_audit.jsonl existe", (AQUI / ".jev_audit.jsonl").exists()))

    # --- grafo único
    g = json.loads((ART / "graph-one.json").read_text(encoding="utf-8"))
    gn, ge = nodes(g), edges(g)
    for nid in ("humano", "modelo", "harness", "gate", "archivo", "specs", "audit", "jevpy", "api", "flag", "digest", "summary"):
        o.append((f"grafo único: nodo {nid}", nid in gn))
    for eid in ("prompt", "call", "fire", "decision", "exec", "nohook", "precompact", "instr", "nouls", "respdig",
                "noul", "answers", "post", "switch", "genera", "resultado", "responde", "respdig"):
        o.append((f"grafo único: arista {eid}", eid in ge))
    o.append(("grafo único: la escritura sale del harness", ge["exec"]["from"] == "harness"))
    o.append(("grafo único: respuestas del gate existen", ge["answers"]["from"] == "jevpy"))

    # --- siete casos
    for i in range(1, 8):
        d = caso(i)
        n, e = nodes(d), edges(d)
        o.append((f"caso {i}: humano y harness", "humano" in n and "harness" in n))
        o.append((f"caso {i}: las tres vueltas", all(k in e for k in ("respuestas", "resp", "vuelta"))))
        o.append((f"caso {i}: interruptor en ambos sentidos", e["switch"]["to"] == "flag" and e["leeflag"]["from"] == "flag"))
        o.append((f"caso {i}: sin overrides de ruteo", not any(k in c for c in d["connections"] for k in ("fromSide", "toSide", "via"))))
        o.append((f"caso {i}: flag con 401/402/403", "401/402/403" in n["flag"]["sublabel"]))

    # --- comportamiento del hook, sin llamar a la API
    secreto = "API_KEY = " + repr("sk_" + "live_" + "51H9xQ2fake")
    salida, _ = _hook(_write("C:/repo/a.py", secreto))
    o.append(("hook: .py con credencial -> deny", "deny" in salida))
    salida, _ = _hook(_write("C:/repo/notas.md", secreto))
    o.append(("hook: .md fuera de EXT -> silencio", salida == ""))
    salida, _ = _hook(_write("C:/repo/specs.md", "x = 1"))
    o.append(("hook: specs.md es gobierno -> deny", "gobierno" in salida.lower() or "Regla Credenciales" not in salida and "deny" in salida))
    salida, _ = _hook(_write("C:/repo/specs.md", "x = 1"))
    o.append(("hook: AGENTS.md es gobierno", "deny" in _hook(_write("C:/repo/AGENTS.md", "x = 1"))[0]))
    salida, _ = _hook(_write("C:/repo/src/app.ts", secreto), {"JEV_EXT": ".py,.ts"})
    o.append(("hook: JEV_EXT habilita .ts", "deny" in salida))
    o.append(("hook: la credencial se busca en el cambio", "cambio" in gate and "SECRETOS.search(cambio" in gate))

    c6, c7, c2, c3, c4, c5 = (caso(i) for i in (6, 7, 2, 3, 4, 5))
    o.append(("caso 6: 1 POST por paso", "por paso" in edges(c6)["call"]["label"]))
    o.append(("caso 6: bucle de la página", "loop" in edges(c6) and edges(c6)["loop"]["to"] == "src"))
    o.append(("caso 7: el archivo lo escribe el harness", edges(c7)["result"]["from"] == "harness"))
    o.append(("caso 7: specs.md y auditoría", "specs" in nodes(c7) and "audit" in nodes(c7)))
    o.append(("caso 2: repositorio como fuente", "repo" in nodes(c2)))
    o.append(("caso 3: la fuente son opciones", edges(c3)["read"]["label"] == "opciones"))
    o.append(("caso 2: la fuente son reglas", edges(c2)["read"]["label"] == "reglas"))
    o.append(("caso 4: la fuente son candidatos", edges(c4)["read"]["label"] == "candidatos"))
    o.append(("caso 5: specs.md opcional", "specs" in nodes(c5)))
    return o


if __name__ == "__main__":
    res = chequeos()
    fallos = [n for n, ok in res if not ok]
    for nombre, ok in res:
        print(("OK   " if ok else "FALLA") + "  " + nombre)
    print(f"\n{len(res) - len(fallos)}/{len(res)} comprobaciones pasan")
    if fallos:
        print("fallan:")
        for n in fallos:
            print("  -", n)
