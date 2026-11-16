"""Caso 6: navegación de UI guiada por Jev (Playwright sobre Edge instalado).

Cada paso: se listan los elementos interactivos visibles, Jev decide si el objetivo
ya se cumple y, si no, cuál accionar. El código hace el clic.

Uso:  py -3 browse.py --self-check
      py -3 browse.py "<objetivo>" "<url>" [--visible]
"""

import sys

from jev import JevApagado, ask

JS_SNAPSHOT = """() => {
  const els = [...document.querySelectorAll('a,button,input,select,textarea,[role=button],[role=link]')];
  return els.filter(e => {
    const r = e.getBoundingClientRect();
    const s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  }).slice(0, 60).map((e, i) => {
    e.setAttribute('data-jev', String(i));
    const raw = e.innerText || e.value || e.getAttribute('aria-label') || e.name || '';
    return { i: String(i), tag: e.tagName.toLowerCase(),
             text: raw.trim().replace(/\\s+/g, ' ').slice(0, 80),
             href: (e.getAttribute('href') || '').slice(0, 60) };
  });
}"""

MAX_PASOS = 8
LOGRADO = 0.6


def _decidir(objetivo, url, texto, elementos):
    criterios = {e["i"]: f'{e["tag"]} "{e["text"]}"{(" -> " + e["href"]) if e["href"] else ""}'
                 for e in elementos}
    criterios["ninguno"] = "Ningún elemento se acerca al objetivo."
    ans = ask(
        {"objetivo": objetivo, "url": url, "texto_visible": texto, "elementos": elementos},
        {
            "logrado": {"type": "noul", "instructions":
                        "¿La página actual, tal como está, ya cumple lo que pide `objetivo`?"},
            "accion": {"type": "choice", "instructions":
                       "¿Qué elemento hay que accionar para acercarse a `objetivo`? Si ya no hace falta "
                       "ninguno, elige `ninguno`.",
                       "criteria": criterios},
        },
    )
    return ans["logrado"]["value"], ans["accion"]["value"]


def navegar(objetivo, url=None, html=None, visible=False, max_pasos=MAX_PASOS):
    from playwright.sync_api import sync_playwright

    pasos = []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", headless=not visible)
        pg = b.new_page()
        if html:
            pg.set_content(html)
        else:
            pg.goto(url, wait_until="domcontentloaded")
        try:
            for _ in range(max_pasos):
                elementos = pg.evaluate(JS_SNAPSHOT)
                texto = pg.inner_text("body")[:600]
                p_logrado, accion = _decidir(objetivo, pg.url, texto, elementos)
                if p_logrado >= LOGRADO:
                    return {"ok": True, "pasos": pasos, "url": pg.url, "texto": texto[:200]}
                if accion == "ninguno":
                    return {"ok": False, "motivo": "Jev no encontró elemento útil", "pasos": pasos,
                            "url": pg.url, "p_logrado": p_logrado}
                el = next((e for e in elementos if e["i"] == accion), None)
                if not el:
                    return {"ok": False, "motivo": f"índice {accion} inexistente", "pasos": pasos}
                pasos.append(f'{el["tag"]} "{el["text"]}"')
                pg.click(f'[data-jev="{accion}"]')
                pg.wait_for_timeout(400)
            return {"ok": False, "motivo": "se agotaron los pasos", "pasos": pasos, "url": pg.url}
        finally:
            b.close()


HTML_DEMO = """<body style="font-family:sans-serif">
<h2>Soporte</h2>
<button onclick="paso(1)">Ayuda</button>
<button>Productos</button>
<button>Contacto</button>
<script>
function paso(n) {
  if (n === 1) document.body.innerHTML =
    '<h2>Ayuda</h2><button onclick="paso(2)">Devoluciones</button><button>Envios</button>';
  if (n === 2) document.body.innerHTML = '<h2>Formulario de devoluciones abierto</h2>';
}
</script>
</body>"""


def _self_check():
    r = navegar("abrir el formulario de devoluciones", html=HTML_DEMO)
    print(r)
    assert r["ok"], r
    assert "Formulario de devoluciones" in r["texto"], r
    assert 1 <= len(r["pasos"]) <= 3, r["pasos"]


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
        print("OK")
    else:
        objetivo, url = sys.argv[1], sys.argv[2]
        try:
            r = navegar(objetivo, url=url, visible="--visible" in sys.argv)
        except JevApagado as e:
            sys.exit(str(e).splitlines()[0] + "\nSin Jev no hay guía: navega a mano.")
        print(r)
