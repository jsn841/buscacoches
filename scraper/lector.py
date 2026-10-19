#!/usr/bin/env python3
"""Lector nocturno de Buscacoches.

Lee anuncios de coches de ocasión de portales y webs oficiales de marca, asigna cada
anuncio a un modelo y motorización del catálogo, quita repetidos entre webs y guarda
un archivo por modelo en datos/ocasion/. Respeta robots.txt y va despacio.

Uso:
  python scraper/lector.py --modo prueba     # pocos modelos y páginas, guarda muestras HTML
  python scraper/lector.py --modo completo   # todos los modelos
  python scraper/lector.py --modelos "Kia|Ceed" "BYD|Atto 2"
"""
import argparse
import collections
import datetime as dt
import json
import pathlib
import random
import re
import sys
import threading
import time
import unicodedata
import urllib.parse
import urllib.robotparser

import requests

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from extraer import extraer  # noqa: E402

RAIZ = pathlib.Path(__file__).resolve().parent.parent
DATOS = RAIZ / "datos"
SALIDA = DATOS / "ocasion"
DEBUG = RAIZ / "debug"
UA = "Mozilla/5.0 (compatible; BuscacochesBot/0.2; +https://github.com/jsn841/buscacoches)"
UA_TOKEN = "BuscacochesBot"


def slug(s):
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def norm(s):
    s = (s or "").replace("'", "").replace("’", "")
    return " " + slug(s).replace("-", " ") + " "


# ---------------------------------------------------------------- webs

def _q(url, **kw):
    return url + ("&" if "?" in url else "?") + urllib.parse.urlencode(kw)


def variantes_modelo(modelo):
    s = slug(modelo)
    vs = [s, s.replace("-", "")]
    if s.startswith("clase-"):
        vs.append(s[6:])
    if s.endswith("-e-tech"):
        vs.append(s[:-7])
    out = []
    for v in vs:
        if v and v not in out:
            out.append(v)
    return out


def variantes_marca(marca, web):
    out = []
    for v in (slug(marca), web, slug(marca).split("-")[0]):
        if v and v not in out:
            out.append(v)
    return out


WEBS = {
    "motor.es": {
        "tipo": "portal",
        "url": lambda ma, mo, p: f"https://www.motor.es/segunda-mano/{ma}/{mo}/" + (f"?pagina={p}" if p > 1 else ""),
    },
    "coches.com": {
        "tipo": "portal",
        "url": lambda ma, mo, p: f"https://www.coches.com/coches-segunda-mano/{ma}-{mo}.htm" + (f"?page={p}" if p > 1 else ""),
    },
    "coches.net": {
        "tipo": "portal",
        "url": lambda ma, mo, p: f"https://www.coches.net/{ma}/{mo}/segunda-mano/" + (f"?pg={p}" if p > 1 else ""),
    },
    "flexicar": {
        "tipo": "portal",
        "url": lambda ma, mo, p: f"https://www.flexicar.es/{ma}/{mo}/segunda-mano/" + (f"?page={p}" if p > 1 else ""),
    },
    "BMW Premium Selection": {
        "tipo": "oficial", "marcas": ["BMW"],
        "url": lambda ma, mo, p: f"https://www.bmwpremiumselection.es/coches-segunda-mano/{mo}/" + (f"?pagina={p}" if p > 1 else ""),
    },
    "Spoticar": {
        "tipo": "oficial", "marcas": ["Peugeot", "Citroën", "Opel"],
        "url": lambda ma, mo, p: f"https://www.spoticar.es/comprar-coches-de-ocasion/{ma}/{mo}" + (f"?page={p}" if p > 1 else ""),
    },
    "Renew": {
        "tipo": "oficial", "marcas": ["Renault", "Dacia"], "etiqueta": True,
        "url": lambda ma, mo, p: ("https://es.renew.auto/vehiculos.html?"
                                  + urllib.parse.urlencode({"brand.label.raw": ma, "model.label.raw": mo})
                                  + (f"&page={p}" if p > 1 else "")),
    },
}


# ---------------------------------------------------------------- red

class Cliente:
    def __init__(self, nombre, pausa):
        self.nombre = nombre
        self.pausa = pausa
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "es-ES,es;q=0.9",
                               "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"})
        self.robots = {}
        self.ultimo = 0.0
        self.peticiones = 0
        self.errores = collections.Counter()
        self.bloqueos_seguidos = 0
        self.bloqueada = False

    def permitido(self, url):
        p = urllib.parse.urlsplit(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self.robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self.s.get(base + "/robots.txt", timeout=20)
                if r.status_code in (401, 403):
                    rp.parse(["User-agent: *", "Disallow: /"])
                elif r.status_code >= 400:
                    rp.parse([])
                else:
                    rp.parse(r.text.splitlines())
            except requests.RequestException:
                rp.parse([])
            self.robots[base] = rp
        return self.robots[base].can_fetch(UA_TOKEN, url)

    def get(self, url):
        if self.bloqueada:
            return None, "web bloqueada"
        if not self.permitido(url):
            self.errores["robots"] += 1
            return None, "robots.txt no lo permite"
        for intento in range(2):
            espera = self.ultimo + self.pausa + random.uniform(0, self.pausa / 2) - time.time()
            if espera > 0:
                time.sleep(espera)
            self.ultimo = time.time()
            self.peticiones += 1
            try:
                r = self.s.get(url, timeout=30)
            except requests.RequestException as e:
                self.errores[type(e).__name__] += 1
                time.sleep(5)
                continue
            if r.status_code == 200:
                self.bloqueos_seguidos = 0
                return r.text, None
            self.errores[str(r.status_code)] += 1
            if r.status_code in (403, 429):
                self.bloqueos_seguidos += 1
                if self.bloqueos_seguidos >= 5:
                    self.bloqueada = True
                    return None, f"bloqueada tras {r.status_code} seguidos"
                time.sleep(20)
                continue
            if r.status_code == 404:
                return None, "404"
            time.sleep(5)
        return None, "error"


# ---------------------------------------------------------------- normalizar y asignar

def combustible_de(texto, campo=None):
    t = " " + (str(campo or "") + " " + (texto or "")).lower() + " "
    if re.search(r"enchuf|phev|plug.?in|dm-?i|e-?hybrid|tfsi ?e\b|recharge|\b\d{2,3}e\b|xdrive\d{2}e|e-?tech h[ií]brido ench", t):
        return "híbrido enchufable"
    if re.search(r"el[eé]ctric|\bbev\b|\bev\b|kwh|e-?tron|\bid\.|\beq[abcesv]|\bë-|\be-\d{3,4}\b", t):
        return "eléctrico"
    if re.search(r"\bglp\b|\blpg\b|eco-?g\b|bifuel", t):
        return "GLP"
    if re.search(r"mhev|mild|micro.?h[ií]brid|48 ?v|\betsi\b|hybrid 1[14]5|\bmicro", t):
        return "microhíbrido"
    if re.search(r"h[ií]brid|hybrid|\bhev\b|full hybrid|e-?tech", t):
        return "híbrido"
    if re.search(r"di[eé]sel|\btdi\b|crdi|\bdci\b|hdi|bluehdi|\b\d{2,3} ?d\b|\b\d{2,3}d\b|d4d|\bjtd|\bcdi\b|multijet", t):
        return "diésel"
    return "gasolina"


def cv_de(texto):
    t = (texto or "").lower()
    m = re.search(r"(\d{2,4})\s*(?:cv|ps|hp)\b", t)
    if m and 40 <= int(m.group(1)) <= 1600:
        return int(m.group(1))
    m = re.search(r"(\d{2,3})\s*kw\b", t)
    if m and 30 <= int(m.group(1)) <= 1200:
        return round(int(m.group(1)) * 1.36)
    return None


def cambio_de(texto, campo=None):
    t = (str(campo or "") + " " + (texto or "")).lower()
    if re.search(r"autom|\bdct\b|\bdsg\b|\bedc\b|\bat\b|steptronic|tiptronic|s tronic|cvt|e-?cvt|\bauto\b|\bdct7|\beat8|eat\b", t):
        return "Automático"
    if re.search(r"manual|\bmt\b|\bimt\b", t):
        return "Manual"
    return None


COMPAT = {
    "gasolina": {"gasolina", "microhíbrido"},
    "diésel": {"diésel", "microhíbrido"},
    "microhíbrido": {"microhíbrido", "gasolina", "diésel", "híbrido"},
    "híbrido": {"híbrido", "microhíbrido"},
    "híbrido enchufable": {"híbrido enchufable"},
    "eléctrico": {"eléctrico"},
    "GLP": {"GLP", "gasolina"},
    "hidrógeno": {"hidrógeno"},
}


def cilindrada(texto):
    m = re.search(r"(?<![\d.])([0-6][.,]\d)(?![\d])", texto or "")
    return m.group(1).replace(",", ".") if m else None


def asignar_motor(motores, cv, comb, cil=None, titulo=None):
    """Devuelve (clave, etiqueta, nuevo). nuevo=True si no está en el catálogo."""
    cands = [m for m in motores if m["combustible"] in COMPAT.get(comb, {comb})
             and not (cil and cilindrada(m["clave"]) and cilindrada(m["clave"]) != cil)]
    if cv:
        mejor = None
        for m in cands:
            if m["cv"] is None:
                continue
            d = abs(m["cv"] - cv)
            if d <= 5 and (mejor is None or (d, m["combustible"] != comb) < mejor[0]):
                mejor = ((d, m["combustible"] != comb), m)
        if mejor:
            return mejor[1]["clave"], mejor[1]["etiqueta"], False
        pre = f"{cil} " if cil else ""
        return f"{pre}{comb} {cv} CV", f"{pre}{cv} CV · {comb} (solo ocasión)", True
    if titulo:
        t = norm(titulo)
        por_nombre = [m for m in motores if len(m["clave"]) >= 3 and norm(m["clave"]) in t]
        if por_nombre:
            m = max(por_nombre, key=lambda m: len(m["clave"]))
            return m["clave"], m["etiqueta"], False
    exactos = [m for m in cands if m["combustible"] == comb]
    if len(exactos) == 1:
        return exactos[0]["clave"], exactos[0]["etiqueta"], False
    return "", "", False


def modelo_del_titulo(titulo, modelos_marca):
    """Modelo más largo de la marca que aparece en el título (evita confundir Atto 3 con Atto 3 Evo)."""
    t = norm(titulo)
    mejor = None
    for m in modelos_marca:
        n = norm(m)
        if n in t and (mejor is None or len(n) > len(norm(mejor))):
            mejor = m
    return mejor


# ---------------------------------------------------------------- lectura por web

def leer_modelo_en_web(cli, web, cfg, marca, info_marca, modelo, info_modelo, modelos_marca, max_pag, slugs, muestras):
    """Devuelve (anuncios, nota)."""
    if cfg.get("etiqueta"):
        combos = [(marca.upper(), info_modelo.get("etiqueta_oficial") or modelo.upper())]
    elif web == "BMW Premium Selection":
        combos = [(None, v) for v in variantes_modelo(modelo)]
    else:
        combos = [(a, b) for a in variantes_marca(marca, info_marca["web"]) for b in variantes_modelo(modelo)]
    clave_slug = f"{web}|{marca}|{modelo}"
    if clave_slug in slugs:
        combos = [tuple(slugs[clave_slug])] + [c for c in combos if list(c) != slugs[clave_slug]]
    combos = combos[:4]

    for ma, mo in combos:
        vistos, buenos, paginas = set(), [], 0
        for p in range(1, max_pag + 1):
            url = cfg["url"](ma, mo, p)
            html, err = cli.get(url)
            if html is None:
                if p == 1:
                    break
                return buenos, f"paginas={paginas} ({err})"
            paginas += 1
            anuncios, via = extraer(html)
            if muestras is not None and p == 1 and len(muestras.get(web, [])) < 2:
                ejemplo = [f"{x['titulo'][:50]} | {x['precio']} | {x['km']} | {x['ano']}" for x in anuncios[:3]]
                muestras.setdefault(web, []).append((f"{slug(marca)}--{slug(modelo)}", url, html, len(anuncios), via, ejemplo))
            nuevos = 0
            otros = sum(1 for a in anuncios if (modelo_del_titulo(a["titulo"], modelos_marca) not in (None, modelo)))
            for a in anuncios:
                mt = modelo_del_titulo(a["titulo"], modelos_marca)
                if mt != modelo and not (mt is None and otros == 0):
                    continue
                k = a.get("url") or (a["titulo"][:60], a["precio"], a["km"], a["ano"])
                if k in vistos:
                    continue
                vistos.add(k)
                nuevos += 1
                buenos.append(a)
            if nuevos == 0:
                break
        if buenos:
            slugs[clave_slug] = [ma, mo]
            return buenos, f"paginas={paginas}"
    return [], "sin anuncios"


def hilo_web(web, cfg, tareas, catalogo, max_pag, limite, resultados, informe, slugs, muestras, pausa):
    cli = Cliente(web, pausa)
    n_mod = n_anun = 0
    notas = collections.Counter()
    for marca, modelo in tareas:
        if time.time() > limite:
            notas["sin tiempo"] += 1
            continue
        if cfg["tipo"] == "oficial" and marca not in cfg["marcas"]:
            continue
        info_marca = catalogo[marca]
        modelos_marca = list(info_marca["modelos"].keys())
        try:
            ans, nota = leer_modelo_en_web(cli, web, cfg, marca, info_marca, modelo, info_marca["modelos"][modelo],
                                           modelos_marca, max_pag, slugs, muestras)
        except Exception as e:  # un fallo en un modelo no debe parar el resto
            ans, nota = [], f"error {type(e).__name__}: {e}"[:200]
        notas[nota.split(" ")[0] if nota.startswith(("error", "sin")) else "ok"] += 1
        if ans:
            n_mod += 1
            n_anun += len(ans)
            resultados[(marca, modelo)][web] = ans
        if cli.bloqueada:
            notas["bloqueada"] += 1
            break
    informe[web] = {"tipo": cfg["tipo"], "peticiones": cli.peticiones, "modelos_con_anuncios": n_mod,
                    "anuncios": n_anun, "errores_http": dict(cli.errores), "resumen": dict(notas),
                    "bloqueada": cli.bloqueada}


# ---------------------------------------------------------------- unir y guardar

def normalizar(a, motores, ano_actual):
    texto = " ".join(x for x in (a.get("titulo"), a.get("texto"), a.get("combustible"), a.get("cambio")) if x)
    cv = a.get("cv") or cv_de(texto)
    cv = int(round(cv)) if cv else None
    comb = combustible_de(texto, a.get("combustible"))
    clave, etiqueta, nuevo = asignar_motor(motores, cv, comb, cilindrada(a.get("titulo")), a.get("titulo"))
    km = a.get("km")
    ano = a.get("ano")
    if km is None:
        if ano and ano >= ano_actual - 1:
            km = 0  # stock de concesionario sin kilómetros: casi nuevo
        else:
            return None
    return {"motor": clave, "etiqueta": etiqueta, "nuevo": nuevo, "precio": int(round(a["precio"])),
            "km": int(km), "ano": ano or ano_actual, "cambio": cambio_de(texto, a.get("cambio")),
            "cv": cv, "combustible": comb}


def quitar_repetidos(por_web):
    """Un coche anunciado en varias webs cuenta una vez. Coches de stock iguales (0 km) se conservan."""
    grupos = collections.defaultdict(lambda: collections.Counter())
    datos = {}
    for web, lista in por_web.items():
        for c in lista:
            k = (c["motor"], c["precio"] // 10, (c["km"] // 100) if c["km"] > 100 else 0, c["ano"] if c["km"] > 100 else None)
            grupos[k][web] += 1
            datos.setdefault(k, c)
    out = []
    for k, cnt in grupos.items():
        c = datos[k]
        veces = max(cnt.values()) if k[2] == 0 else 1
        for _ in range(veces):
            out.append([c["motor"], c["precio"], c["km"], c["ano"], c["cambio"], "/".join(sorted(cnt))])
    return out


def construir(marca, modelo, info_modelo, por_web, ano_actual, fecha):
    motores = info_modelo["motores"]
    bloques = {"oficial": {}, "portal": {}}
    extra = {}
    for web, lista in por_web.items():
        tipo = WEBS[web]["tipo"]
        norm_l = []
        for a in lista:
            c = normalizar(a, motores, ano_actual)
            if c is None:
                continue
            norm_l.append(c)
            if c["nuevo"]:
                extra[c["motor"]] = [c["etiqueta"], ["Automático"] if c["combustible"] in ("eléctrico", "híbrido", "híbrido enchufable") else ["Manual", "Automático"]]
        bloques[tipo][web] = norm_l
    res = {"fecha": fecha, "marca": marca, "modelo": modelo, "motores_extra": extra}
    for tipo, pw in bloques.items():
        leidos = sum(len(v) for v in pw.values())
        res[tipo] = {"webs": sorted(w for w, v in pw.items() if v), "leidos": leidos,
                     "coches": quitar_repetidos(pw) if leidos else []}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modo", choices=["prueba", "completo"], default="completo")
    ap.add_argument("--modelos", nargs="*", help='p. ej. "Kia|Ceed"')
    ap.add_argument("--webs", nargs="*")
    ap.add_argument("--max-paginas", type=int)
    ap.add_argument("--minutos", type=int, default=300)
    ap.add_argument("--pausa", type=float, default=1.5)
    args = ap.parse_args()

    catalogo = json.loads((DATOS / "catalogo.json").read_text())
    if args.modelos:
        tareas = [tuple(m.split("|", 1)) for m in args.modelos]
    elif args.modo == "prueba":
        tareas = [("Kia", "Ceed"), ("BYD", "Atto 2"), ("BMW", "Serie 3"), ("Renault", "Captur")]
    else:
        tareas = [(ma, mo) for ma, info in catalogo.items() for mo in info["modelos"]]
    max_pag = args.max_paginas or (2 if args.modo == "prueba" else 10)
    webs = {k: v for k, v in WEBS.items() if not args.webs or k in args.webs}
    limite = time.time() + args.minutos * 60
    hoy = dt.date.today()
    fecha = hoy.isoformat()

    SALIDA.mkdir(parents=True, exist_ok=True)
    slugs_f = DATOS / "slugs_webs.json"
    slugs = json.loads(slugs_f.read_text()) if slugs_f.exists() else {}
    resultados = collections.defaultdict(dict)
    informe = {}
    muestras = {} if args.modo == "prueba" or args.modelos else None

    hilos = [threading.Thread(target=hilo_web, args=(w, cfg, tareas, catalogo, max_pag, limite, resultados, informe,
                                                     slugs, muestras, args.pausa), daemon=True)
             for w, cfg in webs.items()]
    t0 = time.time()
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()

    escritos = 0
    indice = {}
    idx_f = SALIDA / "indice.json"
    if idx_f.exists():
        indice = json.loads(idx_f.read_text()).get("modelos", {})
    for (marca, modelo), por_web in resultados.items():
        res = construir(marca, modelo, catalogo[marca]["modelos"][modelo], por_web, hoy.year, fecha)
        n = len(res["oficial"]["coches"]) + len(res["portal"]["coches"])
        if n == 0:
            continue
        f = SALIDA / f"{slug(marca)}--{slug(modelo)}.json"
        f.write_text(json.dumps(res, ensure_ascii=False, separators=(",", ":")))
        indice[f"{marca}|{modelo}"] = {"fecha": fecha, "oficial": len(res["oficial"]["coches"]),
                                       "portal": len(res["portal"]["coches"])}
        escritos += 1
    idx_f.write_text(json.dumps({"actualizado": fecha, "modelos": indice}, ensure_ascii=False, indent=0))
    slugs_f.write_text(json.dumps(slugs, ensure_ascii=False, indent=0, sort_keys=True))

    inf = {"fecha": fecha, "modo": args.modo, "minutos": round((time.time() - t0) / 60, 1),
           "modelos_pedidos": len(tareas), "modelos_con_datos": escritos, "webs": informe}
    (DATOS / "informe.json").write_text(json.dumps(inf, ensure_ascii=False, indent=1))

    if muestras is not None:
        DEBUG.mkdir(exist_ok=True)
        for f in DEBUG.glob("*"):
            f.unlink()
        resumen = []
        for web, lista in muestras.items():
            for nombre, url, html, n, via, ejemplo in lista:
                fn = f"{slug(web)}__{nombre}.html"
                (DEBUG / fn).write_text(html[:1_500_000])
                resumen.append({"web": web, "url": url, "archivo": fn, "anuncios_extraidos": n, "via": via,
                                "bytes": len(html), "scripts": html.count("<script"), "ejemplos": ejemplo})
        (DEBUG / "muestras.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=1))
    print(json.dumps(inf, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
