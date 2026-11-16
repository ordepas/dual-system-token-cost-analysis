"""Caso 1: destilar contexto antes de la compactación (PreCompact de Claude Code).

Lee el transcript, pregunta por mensaje qué merece sobrevivir y devuelve
instrucciones para el resumen. Nunca resume: selecciona, que es lo que Jev sabe hacer.

Uso:  py -3 compact_digest.py --self-check   (o sin argumentos, como hook)
"""

import json
import sys

from jev import JevApagado, ask

ULTIMOS = 150      # mensajes que se evalúan
RECORTE = 400      # caracteres por mensaje
MAX_SALIDA = 9000  # el hook corta a 10 000
UMBRAL = 0.5

PREGUNTA = ("¿El mensaje `msgs[{i}]` contiene algo que deba sobrevivir a la compactación: un acuerdo técnico, "
            "una decisión de arquitectura, una preferencia estable del usuario, o un error con su solución? "
            "Un saludo, una pregunta de paso o un resultado de herramienta no cuenta.")


def mensajes(path, limite=ULTIMOS):
    """Texto de los turnos de usuario y asistente, sin bloques de herramientas."""
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("type") not in ("user", "assistant"):
                continue
            if d.get("isSidechain"):
                continue
            c = (d.get("message") or {}).get("content")
            if isinstance(c, list):
                c = " ".join(b.get("text", "") for b in c if b.get("type") == "text")
            if not isinstance(c, str) or len(c.strip()) < 40:
                continue  # una confirmación ("dale", "B") no es contexto que rescatar
            out.append({"role": d["type"], "text": c.strip()[:RECORTE]})
    return out[-limite:]


def destilar(path):
    """Lista de (rol, p, texto) que sobreviven."""
    msgs = mensajes(path)
    if not msgs:
        return []
    qs = {f"m{i}": {"type": "noul", "instructions": PREGUNTA.format(i=i)} for i in range(len(msgs))}
    ans = ask({"msgs": msgs}, qs)
    keep = [(msgs[i]["role"], v["value"], msgs[i]["text"])
            for i, v in ((int(k[1:]), v) for k, v in ans.items())
            if v["value"] >= UMBRAL]
    keep.sort(key=lambda x: -x[1])
    return keep


def instrucciones(keep):
    if not keep:
        return ""
    lines = ["Al resumir esta conversación, conserva textualmente estos puntos (son los que el usuario "
             "o el trabajo posterior necesitan); el resto de detalles operativos se puede descartar:", ""]
    for rol, p, texto in keep:
        item = f"- ({rol}, p={p:.2f}) {texto}"
        if sum(len(x) + 1 for x in lines) + len(item) > MAX_SALIDA:
            break
        lines.append(item)
    return "\n".join(lines)


def _self_check():
    import os
    import tempfile

    lineas = [
        ("user", "Hola, ¿puedes revisar el repo?"),
        ("assistant", "Voy a revisar los archivos de configuración."),
        ("user", "Decidido: usamos Jev en vez de Gemini Decision 1 porque la API no tiene créditos. No volvamos a proponer Gemini."),
        ("assistant", "El test fallaba porque el frontmatter usa escalares plegados; lo arreglé parseando las líneas indentadas."),
        ("user", "ok corre los tests"),
    ]
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
        for rol, texto in lineas:
            f.write(json.dumps({"type": rol, "message": {"role": rol, "content": texto}}) + "\n")
        path = f.name
    keep = destilar(path)
    os.unlink(path)
    texto = instrucciones(keep).lower()
    print(instrucciones(keep)[:300])
    assert "jev" in texto, "no conservó la decisión"
    assert "frontmatter" in texto, "no conservó el error resuelto"


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
        print("\nOK")
        sys.exit(0)
    try:
        datos = json.load(sys.stdin)
        salida = instrucciones(destilar(datos["transcript_path"]))
    except JevApagado as e:  # sin saldo: la compactación sigue con el resumen normal
        print(str(e).splitlines()[0], file=sys.stderr)
        sys.exit(0)
    except Exception as e:  # fail-open: la compactación sigue aunque esto falle
        print(f"compact_digest: {e}", file=sys.stderr)
        sys.exit(0)
    if salida:
        print(salida)
