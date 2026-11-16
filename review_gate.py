"""Caso 5: gate de pre-revisión. Un diff, seis preguntas binarias, un veredicto.

aprobar  -> nada pasó de 0.5: cambio trivial o seguro, no necesita revisión profunda
escalar  -> alguna entre 0.5 y 0.8: revisión humana / agente
bloquear -> alguna >= 0.8: defecto concreto, se devuelve con el motivo

Uso:  py -3 review_gate.py [repo] [ref]
"""

import subprocess
import sys

from jev import JevApagado, ask
from rule_coverage import rules as spec_rules

QUESTIONS = {
    "bug_obvio": "¿El diff introduce un bug evidente: off-by-one, referencia a algo que no existe, "
                 "condición invertida, variable usada antes de asignarse, o un tipo que no corresponde?",
    "secretos": "¿El diff incluye credenciales, tokens, claves o URLs privadas en texto plano?",
    "debug": "¿El diff deja código de depuración (print, console.log, debugger, breakpoint, un TODO de prueba)? "
             "Registrar un error con console.error o un logger no cuenta como debug.",
    "error_silenciado": "¿El diff pierde una excepción en silencio: catch vacío, `except: pass`, o continuar "
                        "sin registrar el error ni dejarlo visible? Un catch que registra el error y sigue con "
                        "un fallback explicado NO cuenta.",
    "entrada_sin_validar": "¿El diff construye SQL, un comando de shell, HTML o una ruta de archivo con "
                           "entrada externa sin validar?",
    "regresion_visible": "¿El diff elimina o desactiva una validación, un manejo de error o un test existente?",
}

BLOCK, ASK = 0.8, 0.5


def gate(diff, specs=None, max_chars=60000):
    qs = {k: {"type": "noul", "instructions": v} for k, v in QUESTIONS.items()}
    state = {"kind": "code_change", "diff": diff[:max_chars]}
    if specs:
        rs = spec_rules(specs)[:12]
        state["rules"] = rs
        for i, r in enumerate(rs):
            qs[f"spec_{r['id']}"] = {"type": "noul", "instructions":
                f"¿El diff cambia la conducta que manda la regla `rules[{i}]` ({r['title']}) "
                f"y no agrega ni actualiza un test que la cubra?"}
    ans = ask(state, qs)
    hits = {k: v["value"] for k, v in ans.items()}
    top = max(hits, key=hits.get)
    verdict = "bloquear" if hits[top] >= BLOCK else "escalar" if hits[top] >= ASK else "aprobar"
    return verdict, top, hits


def _self_check():
    limpio = """diff --git a/src/amounts.py b/src/amounts.py
+def parse_amount(text: str) -> int:
+    \"\"\"Convierte '12.50' en 1250 centavos.\"\"\"
+    if not text.strip():
+        raise ValueError("monto vacío")
+    return round(float(text) * 100)
"""
    sucio = """diff --git a/src/charge.py b/src/charge.py
+API_KEY = "sk_live_51H9xQ2fake"
+def charge(amount):
+    print("charging", amount)
+    try:
+        return post("https://api.stripe.com/v1/charges", key=API_KEY, data=amount)
+    except Exception:
+        pass
"""
    cases = [("limpio", limpio, None, "aprobar"), ("sucio", sucio, None, "bloquear")]
    specs = """# Specs

**Monto mínimo** — Todo cobro valida que el monto sea un entero positivo y mayor a cero antes de enviarlo.

**Copy de error** — El mensaje que ve la persona no nombra al proveedor de pago ni el protocolo usado.
"""
    bad = []
    for label, diff, sp, want in cases:
        verdict, top, hits = gate(diff, sp)
        print(f"{label:13} {verdict:9} top={top} {hits[top]:.2f}")
        if verdict != want:
            bad.append((label, want, verdict, hits))
    cambio = """diff --git a/src/charge.py b/src/charge.py
-def charge(amount: int) -> str:
-    if amount <= 0:
-        raise ValueError("monto invalido")
+def charge(amount: int) -> str:
     return gateway.send(amount)
"""
    con_test = """diff --git a/src/charge_test.py b/src/charge_test.py
+def test_rechaza_monto_no_positivo():
+    with pytest.raises(ValueError):
+        charge(0)
"""
    for label, diff, want_spec in [("spec sin test", cambio, True), ("spec con test", con_test, False)]:
        verdict, top, hits = gate(diff, specs)
        spec_hits = {k: v for k, v in hits.items() if k.startswith("spec_")}
        top_spec = max(spec_hits.values()) if spec_hits else 0
        print(f"{label:13} {verdict:9} top_spec={top_spec:.2f}  " +
              " ".join(f"{k}={v:.2f}" for k, v in spec_hits.items()))
        if (top_spec >= ASK) != want_spec:
            bad.append((label, want_spec, top_spec, spec_hits))
    assert not bad, bad


if __name__ == "__main__":
    if len(sys.argv) == 1:
        _self_check()
        print("OK")
    else:
        repo = sys.argv[1]
        ref = sys.argv[2] if len(sys.argv) > 2 else "HEAD~1"
        specs = sys.argv[3] if len(sys.argv) > 3 else None
        diff = subprocess.run(["git", "-C", repo, "diff", ref], capture_output=True,
                              text=True, encoding="utf-8", errors="replace").stdout
        if not diff.strip():
            sys.exit(f"sin diff para {ref} en {repo}")
        try:
            verdict, top, hits = gate(diff, specs)
        except JevApagado as e:
            print(str(e).splitlines()[0])
            sys.exit("escalar: sin Jev, este diff va a revisión humana")
        print(f"{verdict}  ({len(diff)} chars)  top={top} {hits[top]:.2f}")
        for k, v in sorted(hits.items(), key=lambda kv: -kv[1]):
            print(f"  {v:.2f}  {k}")
