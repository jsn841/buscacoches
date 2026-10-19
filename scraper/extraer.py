"""Extrae anuncios de coches de una página HTML de resultados.

Prueba tres caminos, de más fiable a menos:
1. Datos estructurados (JSON-LD de schema.org).
2. Datos JSON incrustados en la página (Next.js, estado inicial, etc.).
3. Texto visible de las tarjetas de anuncio (precio en €, km y año).
"""
import json
import re

from bs4 import BeautifulSoup

PRECIO_CLAVES = {"price", "precio", "cashprice", "pricecash", "finalprice", "saleprice",
                 "currentprice", "pricewithoutfinancing", "preciocontado", "contado",
                 "pricevalue", "priceamount", "totalprice", "sellprice"}
KM_CLAVES = {"km", "kms", "kilometers", "kilometres", "kilometros", "kilómetros", "mileage",
             "mileagefromodometer", "odometer", "kilometraje"}
ANO_CLAVES = {"year", "anio", "ano", "año", "registrationyear", "firstregistrationdate",
              "registrationdate", "vehiclemodeldate", "productiondate", "datevehiclefirstregistered",
              "fechamatriculacion", "matriculacion", "firstregistration", "modelyear", "registeryear"}
TITULO_CLAVES = {"make", "brand", "marca", "model", "modelo", "version", "versión", "title",
                 "titulo", "name", "subtitle", "trim", "acabado", "makename", "modelname", "versionname"}
CV_CLAVES = {"cv", "hp", "power", "potencia", "horsepower", "enginepower", "powercv", "powerhp", "ps"}
KW_CLAVES = {"kw", "powerkw", "potenciakw"}
COMB_CLAVES = {"fuel", "fueltype", "combustible", "carburante", "energy", "fuelname"}
CAMBIO_CLAVES = {"transmission", "gearbox", "cambio", "vehicletransmission", "transmissiontype"}
URL_CLAVES = {"url", "link", "href", "detailurl", "permalink", "slug", "id", "adid", "@id"}


def numero(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        m = re.search(r"\d[\d.\s ,]*", s)
        if not m:
            return None
        t = m.group(0).replace(" ", "").replace(" ", "")
        # 19.990 / 19,990 son miles; 19990.50 decimales
        if re.fullmatch(r"\d{1,3}([.,]\d{3})+", t):
            t = re.sub(r"[.,]", "", t)
        else:
            t = t.replace(",", ".")
            if t.count(".") > 1:
                t = t.replace(".", "")
        try:
            return float(t)
        except ValueError:
            return None
    if isinstance(v, dict):
        for k in ("amount", "value", "valor", "cash", "price"):
            if k in v:
                return numero(v[k])
    return None


def ano_de(v):
    if v is None:
        return None
    m = re.search(r"\b(19[89]\d|20[0-3]\d)\b", str(v))
    return int(m.group(1)) if m else None


def _norm(k):
    return re.sub(r"[^a-záéíóúñ@]", "", str(k).lower())


def aplanar(d, prefijo=(), prof=0, out=None):
    """Lista de (ruta_de_claves, valor) con hijos dict hasta profundidad 2. No entra en listas."""
    if out is None:
        out = []
    for k, v in d.items():
        ruta = prefijo + (_norm(k),)
        if isinstance(v, dict) and prof < 2:
            aplanar(v, ruta, prof + 1, out)
        elif not isinstance(v, list):
            out.append((ruta, v))
    return out


def anuncio_de_dict(d):
    campos = aplanar(d)
    precio = km = ano = cv = None
    titulo, comb, cambio, url = [], None, None, None
    for ruta, v in campos:
        ult = ruta[-1]
        prev = ruta[-2] if len(ruta) > 1 else ""
        if precio is None and (ult in PRECIO_CLAVES or (ult in ("amount", "value") and prev in PRECIO_CLAVES)):
            n = numero(v)
            if n and 500 <= n <= 600000:
                precio = n
        elif km is None and (ult in KM_CLAVES or (ult in ("value", "amount") and prev in KM_CLAVES)):
            n = numero(v)
            if n is not None and 0 <= n <= 1500000:
                km = n
        elif ano is None and ult in ANO_CLAVES:
            ano = ano_de(v)
        elif ult in TITULO_CLAVES or (ult == "name" and prev in TITULO_CLAVES):
            if isinstance(v, str) and 0 < len(v) < 140 and not v.startswith("http"):
                titulo.append(v)
        elif cv is None and (ult in CV_CLAVES or (ult in ("value",) and prev in CV_CLAVES)):
            n = numero(v)
            if n and 40 <= n <= 1600:
                cv = n
        elif cv is None and ult in KW_CLAVES:
            n = numero(v)
            if n and 30 <= n <= 1200:
                cv = round(n * 1.36)
        elif comb is None and (ult in COMB_CLAVES or (ult == "name" and prev in COMB_CLAVES)):
            if isinstance(v, str):
                comb = v
        elif cambio is None and (ult in CAMBIO_CLAVES or (ult == "name" and prev in CAMBIO_CLAVES)):
            if isinstance(v, str):
                cambio = v
        elif url is None and ult in URL_CLAVES and isinstance(v, (str, int)):
            url = str(v)
    if precio is None or (km is None and ano is None) or not titulo:
        return None
    vistos, t = set(), []
    for x in titulo:
        if x.lower() not in vistos:
            vistos.add(x.lower())
            t.append(x)
    return {"titulo": " ".join(t), "precio": precio, "km": km, "ano": ano, "cv": cv,
            "combustible": comb, "cambio": cambio, "url": url, "via": "json"}


def _json_balanceado(t, i):
    prof, en_cad, esc, q = 0, False, False, ""
    for j in range(i, min(len(t), i + 5_000_000)):
        c = t[j]
        if en_cad:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == q:
                en_cad = False
        elif c == '"':
            en_cad, q = True, c
        elif c in "{[":
            prof += 1
        elif c in "}]":
            prof -= 1
            if prof == 0:
                return t[i:j + 1]
    return None


def bloques_json(soup):
    for sc in soup.find_all("script"):
        t = sc.string or sc.get_text() or ""
        if not t.strip():
            continue
        tipo = (sc.get("type") or "").lower()
        if "json" in tipo:
            try:
                yield json.loads(t)
            except ValueError:
                pass
            continue
        if len(t) < 300:
            continue
        for m in re.finditer(r"JSON\.parse\((\"|')(.*?)(?<!\\)\1\)", t, re.S):
            q, s = m.group(1), m.group(2)
            try:
                if q == "'":
                    s = s.replace("\\'", "'").replace('"', '\\"')
                yield json.loads(json.loads('"' + s + '"'))
            except ValueError:
                pass
        n = 0
        for m in re.finditer(r"=\s*([\[{])", t):
            n += 1
            if n > 30:
                break
            bloque = _json_balanceado(t, m.start(1))
            if bloque and len(bloque) > 200:
                try:
                    yield json.loads(bloque)
                except ValueError:
                    pass


def recorrer(o, out, prof=0):
    if prof > 60:
        return
    if isinstance(o, dict):
        a = anuncio_de_dict(o)
        if a:
            out.append(a)
            return
        for v in o.values():
            recorrer(v, out, prof + 1)
    elif isinstance(o, list):
        for v in o:
            recorrer(v, out, prof + 1)


RE_PRECIO = re.compile(r"(\d{1,3}(?:[.\s ]\d{3})+|\d{4,6})\s*(?:€|eur)", re.I)
RE_KM = re.compile(r"(\d{1,3}(?:[.\s ]\d{3})+|\d{1,7})\s*km\b", re.I)
RE_ANO = re.compile(r"\b(19[89]\d|20[0-3]\d)\b")


def desde_texto(soup):
    candidatos = []
    for el in soup.find_all(["article", "li", "div", "a", "section"]):
        t = el.get_text(" ", strip=True)
        if not (25 <= len(t) <= 900):
            continue
        if not RE_PRECIO.search(t) or not (RE_KM.search(t) or RE_ANO.search(t)):
            continue
        candidatos.append(el)
    ids = {id(c) for c in candidatos}
    hojas = []
    for c in candidatos:
        if any(id(h) in ids for h in c.find_all(["article", "li", "div", "a", "section"])):
            continue
        hojas.append(c)
    out = []
    for el in hojas:
        t = el.get_text(" ", strip=True)
        precios = [numero(p) for p in RE_PRECIO.findall(t)]
        precios = [p for p in precios if p and 500 <= p <= 600000]
        if not precios:
            continue
        mc = re.search(r"contado[^0-9]{0,40}" + RE_PRECIO.pattern, t, re.I)
        precio = numero(mc.group(1)) if mc else precios[0]
        mk = RE_KM.search(t)
        km = numero(mk.group(1)) if mk else None
        anos = [int(a) for a in RE_ANO.findall(t)]
        enlace = el.get("href") if el.name == "a" else (el.find("a").get("href") if el.find("a") else None)
        titulo_el = el.find(["h2", "h3", "h4"]) or el
        titulo = titulo_el.get_text(" ", strip=True)[:160]
        out.append({"titulo": titulo if titulo_el is not el else t[:160], "texto": t[:400], "precio": precio, "km": km,
                    "ano": anos[0] if anos else None, "cv": None, "combustible": None, "cambio": None,
                    "url": enlace, "via": "texto"})
    return out


def extraer(html):
    soup = BeautifulSoup(html, "lxml")
    anuncios = []
    for b in bloques_json(soup):
        recorrer(b, anuncios)
    via = "json"
    if len(anuncios) < 3:
        texto = desde_texto(soup)
        if len(texto) > len(anuncios):
            anuncios, via = texto, "texto"
    vistos, unicos = set(), []
    for a in anuncios:
        clave = a.get("url") or (a["titulo"][:60], a["precio"], a["km"], a["ano"])
        if clave in vistos:
            continue
        vistos.add(clave)
        unicos.append(a)
    return unicos, via
