# Specs de s1-s2

**Credenciales** — Ninguna clave, token ni ruta privada aparece literal en el código. Todo se lee de una variable de entorno (`os.environ`).

**Cliente único** — Todo acceso a TypeSafe pasa por `jev.ask()`. Ningún script arma su propio request HTTP contra `api.typesafe.ai`.

**Comentarios** — Los comentarios van en español neutro, explican el porqué y no usan voseo ("tenés", "fijate", "pegá", "podés").
