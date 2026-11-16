"""Caso 4: ranking de archivos candidatos con Jev.

1. Atajo por palabras clave (stdlib) -> ~30 candidatos.
2. Una pregunta Score por candidato, todas en un solo request.
3. Se abren solo los mejor valorados.

Uso:  py -3 file_rank.py "consulta" [raiz] [n]
"""

import os
import re
import sys

from jev import JevApagado, activo, ask

SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next", "site-packages"}
TEXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".md", ".json", ".yaml", ".yml", ".go", ".rs", ".java",
        ".kt", ".cs", ".sql", ".sh", ".ps1", ".html", ".css", ".toml", ".cfg", ".ini", ".txt",
        ".c", ".h", ".cpp", ".rb", ".php", ".swift"}

LEVELS = [
    "Sin relación: no trata el tema buscado ni lo menciona.",
    "Solo lo menciona de pasada, sin desarrollarlo.",
    "Trata el tema de forma parcial, o es un archivo vecino del que se busca.",
    "Es el archivo donde se define o implementa lo que la consulta busca.",
]


def candidates(query, root, limit=30):
    toks = set(re.findall(r"[a-z0-9_]{3,}", query.lower()))
    scored, seen = [], []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP and not d.startswith(".")]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() not in TEXT:
                continue
            p = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(p) > 2_000_000:
                    continue
                with open(p, encoding="utf-8", errors="ignore") as f:
                    head = "".join(f.readline() for _ in range(6))[:400].strip()
            except OSError:
                continue
            rel = os.path.relpath(p, root).replace("\\", "/")
            hits = sum((rel + "\n" + head).lower().count(t) for t in toks)
            item = {"path": rel, "head": head}
            scored.append((hits, rel, item))
            seen.append(item)
    scored.sort(key=lambda x: (-x[0], x[1]))
    # ponytail: si ninguna palabra clave aparece, se puntúa igual los primeros archivos
    return [i for h, _, i in scored[:limit]] or seen[:limit]


def rank(query, root, limit=30):
    cands = candidates(query, root, limit)
    if not cands:
        return []
    questions = {
        f"c{i}": {
            "type": "score",
            "instructions": f"¿Qué tan relevante es el archivo `candidates[{i}]` para lo que pide la consulta en `query`?",
            "criteria": LEVELS,
        }
        for i in range(len(cands))
    }
    try:
        ans = ask({"query": query, "candidates": cands}, questions)
    except JevApagado:
        # camino regular: el orden por palabras clave del primer paso
        return [{"path": c["path"], "relevance": None} for c in cands]
    out = [
        {"path": c["path"], "relevance": ans[f"c{i}"]["value"] / (len(LEVELS) - 1)}
        for i, c in enumerate(cands)
    ]
    out.sort(key=lambda x: -x["relevance"])
    return out


def _self_check():
    assert activo(), "Jev apagado: el check de ranking no aplica"
    import tempfile

    files = {
        "auth/login.py": "# Valida usuario, contraseña y token de sesión\n",
        "billing/invoice.py": "# Genera facturas en PDF a partir de la orden\n",
        "README.md": "# Proyecto de ejemplo\n\nNada que ver.\n",
        "utils/strings.py": "# Helpers para recortar y normalizar texto\n",
    }
    with tempfile.TemporaryDirectory() as d:
        for rel, body in files.items():
            p = os.path.join(d, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(body)
        r = rank("dónde se validan contraseñas y sesiones", d)
    for x in r:
        print(f"{x['relevance']:.2f}  {x['path']}" if x["relevance"] is not None else f"  --  {x['path']}")
    assert r[0]["path"] == "auth/login.py", r[:2]
    assert r[0]["relevance"] > r[-1]["relevance"]


if __name__ == "__main__":
    if len(sys.argv) == 1:
        _self_check()
        print("OK")
    else:
        q = sys.argv[1]
        root = sys.argv[2] if len(sys.argv) > 2 else "."
        n = int(sys.argv[3]) if len(sys.argv) > 3 else 3
        for x in rank(q, root)[:n]:
            print(f"{x['relevance']:.2f}  {x['path']}" if x["relevance"] is not None else f"  --  {x['path']}")
