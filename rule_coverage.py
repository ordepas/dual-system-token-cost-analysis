"""Caso 2: ¿cada regla escrita tiene un test que la cubra?

Extrae las reglas de un specs.md (bloques en negrita dentro de una sección), busca
los tests más relacionados por palabras clave y pregunta una vez por regla.

Uso:  py -3 rule_coverage.py <repo> <specs.md> [sección ...]
"""

import os
import re
import sys

from jev import ask

STOP = {"the", "and", "for", "with", "that", "this", "from", "into", "when", "then", "than", "are",
        "not", "but", "its", "their", "they", "you", "your", "use", "uses", "must", "only", "each",
        "every", "any", "all", "one", "two", "out", "how", "who", "what", "does", "have", "has",
        "will", "can", "may", "via", "per", "under", "over", "also", "never", "always", "where"}
TEST_GLOB = re.compile(r"(^|[/\\])(__tests__|tests?)[/\\]|[._-](test|spec)\.[a-z]+$|[._-](test|spec)$")
LINT_GLOB = re.compile(r"(^|[/\\])eslint[/\\]|\.eslintrc|eslint\.config")
SKIP_DIRS = {"node_modules", ".git", "dist", "build", ".next", "coverage"}


def rules(md_path, section=None):
    """Bloques `**Título** — ...`, en `## section` o en todo el archivo si section es None."""
    text = md_path if "\n" in md_path else open(md_path, encoding="utf-8").read()
    if section:
        m = re.search(rf"^##\s+{re.escape(section)}.*?$", text, re.M)
        if not m:
            return []
        body = text[m.end():]
        end = re.search(r"^##\s+", body, re.M)
        body = body[: end.start()] if end else body
    else:
        body = text
    out = []
    lines = body.splitlines()
    i = 0
    while i < len(lines):
        if not lines[i].startswith("**"):
            i += 1
            continue
        block = [lines[i]]
        i += 1
        while i < len(lines) and not lines[i].startswith("**"):
            block.append(lines[i])
            i += 1
        title = re.match(r"\*\*(.+?)\*\*", block[0]).group(1).rstrip(" —-:")
        base = re.sub(r"\W+", "_", title.lower()).strip("_")[:34]
        # una cláusula por ítem numerado; si no hay, el bloque entero es la regla
        clauses, cur = [], None
        for line in block[1:]:
            num = re.match(r"\s*\d+\.\s+(.+)", line)
            if num:
                if cur:
                    clauses.append(cur)
                cur = [title, num.group(1)]
            elif cur:
                cur.append(line.strip())
        if cur:
            clauses.append(cur)
        if clauses:
            for n, (_, *rest) in enumerate(clauses, 1):
                out.append({"id": f"{base}_{n}", "title": f"{title} §{n}",
                            "text": " ".join(x for x in rest if x)[:1200]})
        else:
            out.append({"id": base, "title": title,
                        "text": " ".join(x.strip() for x in block if x.strip())[:1200]})
    return out


def _keywords(rule_text, n=24):
    toks = re.findall(r"[A-Za-z][A-Za-z0-9_]{3,}", rule_text.lower())
    seen, out = set(), []
    for t in toks:
        if t in STOP or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out[:n]


def _test_files(repo, limit_bytes=20000):
    """Corpus completo, una sola pasada: (ruta, contenido, 'test'|'lint')."""
    for dirpath, dirnames, filenames in os.walk(repo):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, repo).replace("\\", "/")
            kind = "test" if TEST_GLOB.search(fn) else "lint" if LINT_GLOB.search(rel) else None
            if not kind:
                continue
            try:
                with open(p, encoding="utf-8", errors="ignore") as f:
                    body = f.read(limit_bytes)
            except OSError:
                continue
            yield rel, body, kind


def shortlist(rule, corpus, kind, per=4):
    """Ranking por rareza: una palabra que aparece en todo el repo no distingue nada."""
    import math
    kws = _keywords(rule["text"])
    docs = [(p, b, (p + "\n" + b).lower()) for p, b, k in corpus if k == kind]
    n = len(docs) or 1
    counts, df = [], {kw: 0 for kw in kws}
    for path, _, low in docs:
        c = {kw: low.count(kw) for kw in kws}
        counts.append((path, c))
        for kw, v in c.items():
            if v:
                df[kw] += 1
    scored = []
    for path, c in counts:
        score = sum(v * math.log(n / df[kw]) for kw, v in c.items() if v)
        if score:
            scored.append((score, path))
    scored.sort(key=lambda x: (-x[0], x[1]))
    body_of = {p: (b, low) for p, b, low in docs}
    out = []
    for _, p in scored[:per]:
        body, low = body_of[p]
        pos = min((low.find(kw) for kw in kws if kw in low), default=0)
        start = max(0, pos - 150)
        out.append({"path": p, "snippet": body[start:start + 2000]})
    return out


def coverage(repo, rules_list, per=4):
    corpus = list(_test_files(repo))
    tests, lints, per_rule = {}, {}, {}
    for r in rules_list:
        t = shortlist(r, corpus, "test", per)
        l = shortlist(r, corpus, "lint", per)
        per_rule[r["id"]] = [x["path"] for x in t], [x["path"] for x in l]
        tests.update({x["path"]: x["snippet"] for x in t})
        lints.update({x["path"]: x["snippet"] for x in l})
    state = {"rules": rules_list, "test_files": tests, "lint_rules": lints}
    qs = {}
    for i, r in enumerate(rules_list):
        qs[f"{r['id']}_test"] = {"type": "noul", "instructions":
            f"¿Algún archivo de `test_files` tiene una aserción que falla si se viola lo que manda la regla "
            f"`rules[{i}]` ({r['title']})? Un test de la misma zona que no comprueba esa conducta no cuenta."}
        qs[f"{r['id']}_lint"] = {"type": "noul", "instructions":
            f"¿Algún archivo de `lint_rules` contiene una regla de lint que impone lo que manda "
            f"`rules[{i}]` ({r['title']})?"}
    ans = ask(state, qs)
    out = []
    for r in rules_list:
        t, l = ans[f"{r['id']}_test"]["value"], ans[f"{r['id']}_lint"]["value"]
        out.append({"rule": r["id"], "title": r["title"], "test": t, "lint": l,
                    "p": max(t, l), "checks": per_rule[r["id"]]})
    return out


def _self_check():
    md = """# X

## Non-negotiable

**Protocol** — versions are negotiated at handshake. Never npm semver.

**Copy** — says what it costs, not how it is built.

## Commands

**Build** — run make.
"""
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(md)
        path = f.name
    r = rules(path, "Non-negotiable")
    os.unlink(path)
    print([x["id"] for x in r])
    assert [x["id"] for x in r] == ["protocol", "copy"], r
    assert "npm semver" in r[0]["text"]


if __name__ == "__main__":
    if len(sys.argv) == 1:
        _self_check()
        print("OK")
    else:
        repo, specs = sys.argv[1], sys.argv[2]
        sections = sys.argv[3:] or ["Non-negotiable", "Type safety"]
        found = [x for s in sections for x in rules(specs, s)]
        for row in coverage(repo, found):
            mark = "cubierta   " if row["p"] >= 0.5 else "SIN CUBRIR "
            print(f"{mark} {row['p']:.2f}  test={row['test']:.2f} lint={row['lint']:.2f}  {row['title']}")
