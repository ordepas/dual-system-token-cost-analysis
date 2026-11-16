"""Caso 3: elegir una sola habilidad (o ninguna) con Jev.

Descubre las skills de disco, las manda como opciones de un Choice y devuelve la elegida.

Uso:  py -3 skill_pick.py "pedido del usuario"
"""

import glob
import os
import sys

from jev import JevApagado, ask

ROOTS = [
    os.path.expanduser("~/.claude/skills/*/SKILL.md"),
    os.path.expanduser("~/.claude/plugins/cache/*/*/*/skills/*/SKILL.md"),
]


def _front(path):
    """Frontmatter YAML mínimo: pares `clave: valor` y escalares plegados (`>` / `|`)."""
    with open(path, encoding="utf-8") as f:
        lines = f.read(4000).splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    data, key, buf = {}, None, []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line[:1] in (" ", "\t") and key:
            buf.append(line.strip())
            continue
        if key:
            data[key] = " ".join(buf).strip()
            key, buf = None, []
        k, sep, v = line.partition(":")
        if not sep:
            continue
        k, v = k.strip(), v.strip()
        if v in ("", ">", ">-", ">+", "|", "|-", "|+"):
            key, buf = k, []
        else:
            data[k] = v
    if key:
        data[key] = " ".join(buf).strip()
    name, desc = data.get("name"), data.get("description")
    return (name, desc) if name and desc else None


def discover():
    found = {}
    for root in ROOTS:
        for path in glob.glob(root):
            f = _front(path)
            if not f:
                continue
            name, desc = f
            if "plugins" in path:  # cache/<marketplace>/<plugin>/<ver>/skills/<skill>/SKILL.md
                parts = path.split(os.sep)
                plugin = parts[len(parts) - 5]
                name = f"{plugin}:{name}"
            found[name] = desc
    return [{"name": n, "description": d} for n, d in sorted(found.items())]


CONF_MIN = 0.55    # por debajo, el código no acepta la elección de Jev
MARGEN_MIN = 0.10  # si las dos primeras están más cerca, el código lo trata como empate


def _politica(choice, conf, probs):
    """La decisión es del código; Jev solo propone. Devuelve (decisión, motivo)."""
    orden = sorted(probs.items(), key=lambda kv: -kv[1])
    if conf < CONF_MIN:
        return "ninguna", f"confianza {conf:.2f} < {CONF_MIN}"
    if len(orden) > 1 and orden[0][1] - orden[1][1] < MARGEN_MIN:
        return "ninguna", f"empate {orden[0][0]} vs {orden[1][0]}"
    return choice, "elegida"


def pick(prompt, skills=None):
    skills = skills or discover()
    criteria = {s["name"]: s["description"] for s in skills}
    criteria["ninguna"] = "Ninguna habilidad corresponde a este pedido."
    ans = ask(
        {"request": prompt},
        {
            "skill": {
                "type": "choice",
                "instructions": (
                    "Elige la única habilidad que corresponde a lo que pide `request`. "
                    "Prefiere `ninguna` antes que una habilidad que solo se parezca en el tema."
                ),
                "criteria": criteria,
            }
        },
    )
    a = ans["skill"]
    decision, motivo = _politica(a["value"], a["confidence"], a["raw"]["probabilities"])
    return decision, a["confidence"], a["raw"]["probabilities"], motivo


def _self_check():
    # la política es del código: Jev propone, esto decide
    assert _politica("a", 0.90, {"a": 0.90, "b": 0.05, "ninguna": 0.05})[0] == "a"
    assert _politica("a", 0.40, {"a": 0.40, "b": 0.35, "ninguna": 0.25})[0] == "ninguna"
    assert _politica("a", 0.60, {"a": 0.60, "b": 0.45, "ninguna": 0.05})[0] == "a"
    assert _politica("a", 0.56, {"a": 0.56, "b": 0.50, "ninguna": 0.04})[0] == "ninguna"
    print("política: 4 casos OK")
    skills = discover()
    print(f"{len(skills)} skills")
    cases = [
        ("Necesito doblar esta lección de academy al español y que el audio calce con el video", "academy-es-dub"),
        ("Escríbeme un post de LinkedIn con gancho sobre mi experiencia migrando a TypeScript", "linkedin-agent:li-post"),
        ("¿Cuál es la capital de Francia?", "ninguna"),
    ]
    bad = []
    for prompt, want in cases:
        got, conf, probs, motivo = pick(prompt, skills)
        print(f"{conf:.2f}  {got:<28} esperado {want:<12} ({motivo})")
        if got != want:
            bad.append((prompt, want, got, sorted(probs.items(), key=lambda kv: -kv[1])[:3]))
    assert not bad, bad


if __name__ == "__main__":
    if len(sys.argv) == 1:
        _self_check()
        print("OK")
    else:
        try:
            got, conf, probs, motivo = pick(sys.argv[1])
        except JevApagado as e:
            sys.exit(str(e).splitlines()[0] + "\nSin Jev no hay selector: elige la skill a mano.")
        print(f"{conf:.2f}  {got}   ({motivo})")
