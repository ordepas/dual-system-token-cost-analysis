"""Bench A: costo E2E por caso, con y sin Jev, según cuánto lee el modelo.

F = tokens que el modelo leería sin Jev (todo el material del caso).
S = tokens que lee Jev (usage real de la API).
s = tokens que el modelo lee con Jev (lo que Jev le pasa).

sin Jev:  F * P_in + O * P_out
con Jev:  S * 0.042 + s * P_in + o * P_out

F y s se estiman con caracteres/4 (no hay tokenizer local del modelo); S es exacto.
O y o son supuestos calibrables con --salida y --salida-con (default 300 y 50).

Uso:  py -3 bench_e2e.py [--modelo opus|sonnet|haiku|fable] [--salida N] [--salida-con N]
      py -3 bench_e2e.py --self-check
"""

import json
import os
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

import browse  # noqa: E402
import compact_digest  # noqa: E402
import file_rank  # noqa: E402
import jev  # noqa: E402
import review_gate  # noqa: E402
import rule_coverage  # noqa: E402
import skill_pick  # noqa: E402
import spec_gate  # noqa: E402
from jev import PRECIO_JEV_MTOK, PRECIO_LLM_MTOK  # noqa: E402


def _tok(texto):
    """Mismo estimador para F y s; solo S es exacto."""
    return max(1, len(texto) // 4)


def _filas():
    try:
        with open(jev.COSTOS, encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]
    except (OSError, ValueError):
        return []


def _medir(caso, construir):
    """Corre el caso real y devuelve F, S (usage registrado) y s."""
    os.environ["JEV_RUN"] = f"bench:{caso}"
    antes = len(_filas())
    try:
        F, s = construir()
        S = sum(r.get("in", 0) for r in _filas()[antes:])
    except Exception as e:  # un caso sin dependencias no tumba la tabla
        return {"caso": caso, "error": f"{type(e).__name__}: {e}"}
    finally:
        os.environ.pop("JEV_RUN", None)
    return {"caso": caso, "F": _tok(F), "S": S, "s": _tok(s) if s else 0}


# --- artefactos fijos -------------------------------------------------------

def _file_rank():
    files = {}
    for i in range(30):
        tema = "validación de contraseñas y sesiones" if i == 7 else f"utilidad {i}: cálculo y formato"
        cuerpo = "\n".join(f"def f{i}_{j}(x):\n    # {tema}\n    return x + {j}" for j in range(14))
        files[f"src/mod{i:02d}.py"] = f'"""{tema}."""\n{cuerpo}\n'
    with tempfile.TemporaryDirectory() as d:
        for rel, body in files.items():
            p = os.path.join(d, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(body)
        res = file_rank.rank("dónde se validan contraseñas y sesiones", d, 30)
        F = "".join(files.values())
        s = "".join(files[r["path"]] for r in res[:3] if r["path"] in files)
    return F, s


def _skill_pick():
    skills = skill_pick.discover()
    F = "\n".join(f'{x["name"]}: {x["description"]}' for x in skills)
    skill_pick.pick("Dobla esta lección al español y sincroniza el audio con el video", skills)
    return F, ""  # cargar la skill elegida es común a ambos flujos y se cancela


def _browse():
    relleno = "Soporte técnico: guías, preguntas frecuentes y contacto. " * 300
    botones = "".join(f"<button>Sección {i}</button>" for i in range(59))
    html = f"""<body style="font-family:sans-serif">
<h2>Soporte</h2>
<button onclick="paso(1)">Ayuda</button>
{botones}
<p>{relleno}</p>
<script>
function paso(n) {{
  if (n === 1) document.body.innerHTML = '<h2>Formulario de devoluciones abierto</h2>';
}}
</script>
</body>"""
    r = browse.navegar("abrir el formulario de devoluciones", html=html)
    return html, json.dumps(r, ensure_ascii=False)  # el script hace clic; el modelo solo ve el resultado


def _review_gate():
    lineas = ["diff --git a/src/charge.py b/src/charge.py", "--- a/src/charge.py",
              "+++ b/src/charge.py", "@@ -1,80 +1,95 @@"]
    for i in range(60):
        lineas += [f"-def cobrar_{i}(monto):", "-    return gateway.send(monto)",
                   f"+def cobrar_{i}(monto):", "+    if monto <= 0:",
                   '+        raise ValueError("monto inválido")', "+    return gateway.send(monto)"]
    diff = "\n".join(lineas)
    verdicto = review_gate.gate(diff)
    return diff, json.dumps(verdicto[:2], ensure_ascii=False)


def _rule_coverage():
    specs = ("# Specs\n\n**Monto** — Todo cobro valida que el monto sea un entero positivo antes de enviarlo.\n\n"
             "**Credenciales** — Ninguna clave aparece literal; se lee de una variable de entorno.\n\n"
             "**Errores** — Todo catch registra el error y deja un fallback explicado.\n")
    tests = {}
    for i in range(4):
        bloque = (f"def test_monto_mod{i}():\n    with pytest.raises(ValueError):\n        cobrar(0)\n\n"
                  f"def test_credencial_mod{i}(monkeypatch):\n"
                  "    monkeypatch.setenv('API_KEY', 'x')\n    assert leer_clave() == 'x'\n\n"
                  f"def test_error_mod{i}(caplog):\n    cobrar(-1)\n    assert caplog.records\n\n")
        tests[f"tests/test_mod{i}.py"] = bloque * 3
    with tempfile.TemporaryDirectory() as d:
        sp = os.path.join(d, "specs.md")
        with open(sp, "w", encoding="utf-8") as f:
            f.write(specs)
        for rel, body in tests.items():
            p = os.path.join(d, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(body)
        rows = rule_coverage.coverage(d, rule_coverage.rules(sp))
        F = specs + "".join(tests.values())
        s = json.dumps([{k: r[k] for k in ("rule", "p")} for r in rows], ensure_ascii=False)
    return F, s


def _spec_gate():
    code = '"""Cobro."""\nimport os\n\nAPI_KEY = os.environ["API_KEY"]\n\n' + "\n\n".join(
        f'def cobrar_{i}(monto: int) -> int:\n    """Cobra {i}."""\n    if monto <= 0:\n'
        '        raise ValueError("monto inválido")\n    return gateway.send(monto)'
        for i in range(30))
    specs = open(os.path.join(AQUI, "specs.md"), encoding="utf-8").read()
    spec_gate.decidir(code, "bench/cobro.py", "Write")
    return specs, ""  # el modelo ya tiene su código; lo que leería sin Jev son las reglas


def _compact_digest():
    msgs = []
    for i in range(150):
        rol = "user" if i % 2 == 0 else "assistant"
        texto = (f"Mensaje {i}: decidimos mantener el cliente único y registrar los errores. "
                 + "Detalle operativo irrelevante. " * 6)[:390]
        msgs.append({"type": rol, "message": {"role": rol, "content": texto}})
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
        for m in msgs:
            f.write(json.dumps(m) + "\n")
        path = f.name
    try:
        keep = compact_digest.destilar(path)
        digest = compact_digest.instrucciones(keep)
    finally:
        os.unlink(path)
    F = "".join(m["message"]["content"] for m in msgs)
    # ponytail: la compactación sigue leyendo el transcript; el digest se suma.
    # Si el modelo solo hiciera la selección, s sería el digest y este caso ahorraría.
    return F, F + digest


CASOS = [("file_rank", _file_rank), ("skill_pick", _skill_pick), ("review_gate", _review_gate),
         ("rule_coverage", _rule_coverage), ("browse", _browse), ("spec_gate", _spec_gate),
         ("compact_digest", _compact_digest)]


# --- costos y reporte -------------------------------------------------------

def _costos(fila, modelo, salida, salida_con):
    p_in, p_out = PRECIO_LLM_MTOK[modelo]
    sin = (fila["F"] * p_in + salida * p_out) / 1e6
    con = (fila["S"] * PRECIO_JEV_MTOK + fila["s"] * p_in + salida_con * p_out) / 1e6
    return sin, con, (1 - con / sin) if sin else None


def _imprimir(filas, modelo, salida, salida_con):
    ok = [f for f in filas if "error" not in f]
    print(f"Sin Jev: {modelo} {PRECIO_LLM_MTOK[modelo][0]}/{PRECIO_LLM_MTOK[modelo][1]} USD/Mtok; "
          f"Jev {PRECIO_JEV_MTOK}/Mtok de entrada. Salida supuesta: {salida} tok sin Jev, "
          f"{salida_con} con Jev.\n")
    cab = f"{'caso':15} {'F_tok':>8} {'S_tok':>8} {'s_tok':>8} {'$sin':>9} {'$con':>9} {'ahorro':>7}"
    print(cab)
    t_sin = t_con = 0.0
    for f in ok:
        sin, con, ah = _costos(f, modelo, salida, salida_con)
        t_sin += sin
        t_con += con
        print(f"{f['caso']:15} {f['F']:8} {f['S']:8} {f['s']:8} {sin:9.5f} {con:9.5f} {ah * 100:6.1f}%")
    for f in filas:
        if "error" in f:
            print(f"{f['caso']:15} N/A  {f['error'][:70]}")
    ah_total = (1 - t_con / t_sin) if t_sin else None
    print(f"{'TOTAL':15} {sum(f['F'] for f in ok):8} {sum(f['S'] for f in ok):8} "
          f"{sum(f['s'] for f in ok):8} {t_sin:9.5f} {t_con:9.5f} "
          f"{ah_total * 100 if ah_total is not None else 0:6.1f}%")

    print("\nahorro por modelo (mismo F, S y s):")
    print(f"{'caso':15} " + " ".join(f"{m:>8}" for m in PRECIO_LLM_MTOK))
    for f in ok:
        ahorros = []
        for m in PRECIO_LLM_MTOK:
            _, _, ah = _costos(f, m, salida, salida_con)
            ahorros.append(f"{ah * 100:7.1f}%")
        print(f"{f['caso']:15} " + " ".join(ahorros))
    totales = []
    for m in PRECIO_LLM_MTOK:
        s = sum(_costos(f, m, salida, salida_con)[0] for f in ok)
        c = sum(_costos(f, m, salida, salida_con)[1] for f in ok)
        totales.append(f"{(1 - c / s) * 100:7.1f}%" if s else "      --")
    print(f"{'TOTAL':15} " + " ".join(totales))
    print("\nF y s son estimaciones (caracteres/4); S es el usage real de Jev. "
          "La salida es un supuesto calibrable; sin ella, el ahorro es mayor.")


def _self_check():
    f = {"F": 10_000, "S": 4_000, "s": 1_000}
    sin, con, ah = _costos(f, "opus", 0, 0)
    assert abs(sin - 10_000 * 4 / 1e6) < 1e-12, sin
    assert abs(con - (4_000 * PRECIO_JEV_MTOK + 1_000 * 4) / 1e6) < 1e-12, con
    assert abs(ah - (1 - con / sin)) < 1e-12, ah
    assert _costos(f, "haiku", 0, 0)[1] < _costos(f, "haiku", 0, 0)[0]
    assert _tok("12345678") == 2
    print("bench: matemática OK")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--self-check" in args:
        _self_check()
        sys.exit(0)
    if not jev.activo():
        sys.exit("Jev apagado: el bench necesita la API (py -3 jev.py --on).")
    i = args.index("--modelo") if "--modelo" in args else -1
    modelo = args[i + 1] if 0 <= i < len(args) - 1 else "opus"
    if modelo not in PRECIO_LLM_MTOK:
        sys.exit(f"modelo desconocido: {modelo} (usa {', '.join(PRECIO_LLM_MTOK)})")

    def _num(flag, default):
        j = args.index(flag) if flag in args else -1
        return int(args[j + 1]) if 0 <= j < len(args) - 1 else default

    filas = [_medir(nombre, fn) for nombre, fn in CASOS]
    _imprimir(filas, modelo, _num("--salida", 300), _num("--salida-con", 50))
