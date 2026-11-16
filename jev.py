"""Cliente mínimo de Jev (TypeSafe System One) sobre stdlib.

ask(state, questions) -> {id: {"value", "confidence", "raw"}}
  noul   -> value = P(sí), 0..1        confidence = None
  choice -> value = opción elegida     confidence = p_max
  score  -> value = nivel esperado 0..N-1

Cada request anota sus tokens en `.jev_costos.jsonl`; `py -3 jev.py --costos`
muestra el costo E2E por corrida (una ejecución completa de un caso): lo real
con Jev contra los mismos tokens a tarifa de un LLM general. `JEV_RUN` agrupa
varios scripts en una sola corrida.

Sin saldo: un 401/402/403 escribe `.jev_off` y toda llamada lanza JevApagado;
cada script sigue por su camino regular. Se reactiva con `py -3 jev.py --on`.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://api.typesafe.ai/v1/systemone"
FLAG = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".jev_off")
APAGADO = {401, 402, 403}
AVISO = ("Jev está apagado ({detalle}). Se sigue por el camino regular.\n"
         "Recarga en https://console.typesafe.ai y ejecuta: py -3 jev.py --on")


ULTIMO_MODELO = None  # versión real informada por la API, para el log de auditoría

COSTOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".jev_costos.jsonl")
PRECIO_JEV_MTOK = 0.042  # USD por millón de tokens de entrada; la salida es gratis
PRECIO_LLM_MTOK = {  # (entrada, salida) en USD por millón, tarifa Anthropic 2026-11
    "sonnet": (2.00, 10.00),
    "opus": (4.00, 20.00),
    "haiku": (0.10, 0.50),
    "fable": (8.00, 40.00),
}


class JevApagado(RuntimeError):
    """Sin saldo, key inválida o apagado a mano."""


def activo():
    return not os.path.exists(FLAG)


def apagar(detalle):
    with open(FLAG, "w", encoding="utf-8") as f:
        f.write(detalle + "\n")


def encender():
    if os.path.exists(FLAG):
        os.remove(FLAG)


def _motivo():
    try:
        with open(FLAG, encoding="utf-8") as f:
            return f.read().strip() or "apagado a mano"
    except OSError:
        return "apagado a mano"


def _registrar_costo(usage):
    """Una fila por request con los tokens reales; los precios se aplican al reportar."""
    tin = int((usage or {}).get("input_tokens") or 0)
    tout = int((usage or {}).get("output_tokens") or 0)
    if not (tin or tout):
        return
    script = os.path.basename(sys.argv[0] or "python")
    fila = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "model": ULTIMO_MODELO,
            "run": os.environ.get("JEV_RUN") or f"{script}:{os.getpid()}",
            "script": script, "in": tin, "out": tout}
    try:
        with open(COSTOS, "a", encoding="utf-8") as f:
            f.write(json.dumps(fila) + "\n")
    except OSError:
        pass


def ask(state, questions, *, model="jev-latest", long_context=False, timeout=90):
    if not activo():
        raise JevApagado(AVISO.format(detalle=_motivo()))
    headers = {
        "Authorization": f"Bearer {os.environ['TYPESAFE_API_KEY']}",
        "Content-Type": "application/json",
    }
    if long_context:
        headers["TypeSafe-Danger-Zone-Long-Context"] = "true"
    body = json.dumps({"model": model, "state": state, "questions": questions}).encode()
    req = urllib.request.Request(API, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.load(r)
        global ULTIMO_MODELO
        ULTIMO_MODELO = out.get("model")
        _registrar_costo(out.get("usage"))
    except urllib.error.HTTPError as e:
        if e.code in APAGADO:
            detalle = f"HTTP {e.code} {e.reason}"
            apagar(detalle)
            raise JevApagado(AVISO.format(detalle=detalle)) from e
        raise
    return {
        qid: {"value": a.get(a["type"]), "confidence": a.get("confidence"), "raw": a}
        for qid, a in out["answers"].items()
    }


def _fila_costo(acc, modelo):
    p_in, p_out = PRECIO_LLM_MTOK[modelo]
    usd_jev = acc["in"] * PRECIO_JEV_MTOK / 1e6
    usd_llm = (acc["in"] * p_in + acc["out"] * p_out) / 1e6
    return {**acc, "usd_jev": usd_jev, "usd_llm": usd_llm,
            "factor": (usd_llm / usd_jev) if usd_jev else None}


def resumen(ruta=COSTOS, modelo="opus"):
    """Costo por corrida E2E, por script y total; `modelo` es la tarifa del camino sin Jev."""
    if modelo not in PRECIO_LLM_MTOK:
        raise SystemExit(f"modelo desconocido: {modelo} (usa {', '.join(PRECIO_LLM_MTOK)})")
    corridas, scripts = {}, {}
    try:
        with open(ruta, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                for grupo, clave in ((corridas, r.get("run")), (scripts, r.get("script"))):
                    acc = grupo.setdefault(clave, {"n": 0, "in": 0, "out": 0})
                    acc["n"] += 1
                    acc["in"] += r.get("in", 0)
                    acc["out"] += r.get("out", 0)
    except OSError:
        pass
    total = {k: sum(x[k] for x in corridas.values()) for k in ("n", "in", "out")}
    return {"corridas": {k: _fila_costo(v, modelo) for k, v in corridas.items()},
            "scripts": {k: _fila_costo(v, modelo) for k, v in scripts.items()},
            "total": _fila_costo(total, modelo)}


def _linea(nombre, x):
    factor = f"{x['factor']:.1f}x" if x["factor"] else "--"
    return (f"{str(nombre)[:34]:34} {x['n']:4} {x['in']:9} {x['out']:8} "
            f"{x['usd_jev']:10.6f} {x['usd_llm']:10.6f} {factor:>7}")


def _imprimir_costos(ruta=COSTOS, modelo="opus"):
    r = resumen(ruta, modelo)
    if not r["total"]["n"]:
        return print(f"Sin registros en {ruta}. Corre algún caso primero.")
    print(f"Sin Jev: {modelo} {PRECIO_LLM_MTOK[modelo][0]}/{PRECIO_LLM_MTOK[modelo][1]} USD por Mtok; "
          f"Jev {PRECIO_JEV_MTOK} USD por Mtok de entrada, salida gratis.\n")
    print(f"{'corrida':34} {'llam':>4} {'tok_in':>9} {'tok_out':>8} {'$jev':>10} {'$sin_jev':>10} {'factor':>7}")
    for k, x in sorted(r["corridas"].items(), key=lambda kv: -kv[1]["usd_llm"]):
        print(_linea(k, x))
    print("\npor script")
    for k, x in sorted(r["scripts"].items(), key=lambda kv: -kv[1]["usd_llm"]):
        print(_linea(k, x))
    print(f"\n{_linea('TOTAL', r['total'])}")


def _self_check_costos():
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
        for tin, tout in ((1_000_000, 0), (0, 1_000_000)):
            f.write(json.dumps({"run": "x:1", "script": "x.py", "model": "m",
                                "in": tin, "out": tout}) + "\n")
        ruta = f.name
    r = resumen(ruta, "sonnet")
    os.unlink(ruta)
    t = r["total"]
    assert t["n"] == 2 and t["in"] == 1_000_000 and t["out"] == 1_000_000, t
    assert abs(t["usd_jev"] - 0.042) < 1e-9, t        # la salida no se cobra
    assert abs(t["usd_llm"] - 12.0) < 1e-9, t          # 2 de entrada + 10 de salida
    assert abs(t["factor"] - 12.0 / 0.042) < 1e-6, t
    assert r["corridas"]["x:1"]["n"] == 2, r
    print("costos: matemática OK")


def _self_check():
    assert 402 in APAGADO and 401 in APAGADO and 429 not in APAGADO
    _self_check_costos()
    r = ask(
        "El usuario quiere que ordenes esta lista de archivos y luego la formatees.",
        {
            "coding": {"type": "noul", "instructions": "¿Pide modificar o crear código?"},
            "task": {
                "type": "choice",
                "instructions": "¿Qué pide el usuario?",
                "criteria": {"ordenar": "Ordenar o formatear datos", "otro": "Otra cosa"},
            },
            "effort": {
                "type": "score",
                "instructions": "¿Cuánto esfuerzo requiere?",
                "criteria": ["trivial", "moderado", "grande"],
            },
        },
    )
    print(r["coding"]["value"], r["task"]["value"], r["effort"]["value"])
    assert 0 <= r["coding"]["value"] <= 1
    assert r["task"]["value"] in ("ordenar", "otro")
    assert 0 <= r["effort"]["value"] <= 2


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--on" in args:
        encender()
        print("Jev activado: los caminos con Jev vuelven a correr.")
    elif "--off" in args:
        apagar("apagado a mano")
        print("Jev apagado: todo corre por el camino regular.")
    elif "--status" in args:
        print("activo" if activo() else f"APAGADO ({_motivo()})")
    elif "--costos" in args:
        i = args.index("--modelo") if "--modelo" in args else -1
        _imprimir_costos(modelo=args[i + 1] if 0 <= i < len(args) - 1 else "opus")
    else:
        _self_check()
        print("OK")
