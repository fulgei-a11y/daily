"""
Rassegna stampa dell'Emilia-Romagna.

1. Legge i feed RSS delle testate locali e tiene solo le notizie delle ultime ore.
2. Elimina i doppioni e, per le notizie principali, scarica un estratto dell'articolo
   (non solo il sommario del feed): così la sintesi ha dati e nomi concreti.
3. Gemini scrive la rassegna in HTML. Le fonti sono indicate con numeri [n] che lo script
   trasforma in link veri: nessun indirizzo può essere inventato.
4. Salva edizioni/AAAA-MM-GG.html, edizioni/index.json (archivio) e index.json (ultima edizione).
"""

import os
import re
import json
import time
import html
import datetime as dt
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

import requests
from google import genai
from google.genai import types

try:
    import trafilatura
except ImportError:  # l'estratto degli articoli è facoltativo
    trafilatura = None

ROME = ZoneInfo("Europe/Rome")
NOW = dt.datetime.now(ROME)
TODAY = NOW.strftime("%Y-%m-%d")
OUTPUT_DIR = "edizioni"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, f"{TODAY}.html")

MAX_PER_FEED = int(os.environ.get("MAX_PER_FEED", "15"))
MAX_AGE_HOURS = int(os.environ.get("MAX_AGE_HOURS", "36"))   # notizie più vecchie vengono scartate
MAX_FULLTEXT = int(os.environ.get("MAX_FULLTEXT", "90"))     # articoli di cui leggere l'estratto
MAX_ARTICLES = int(os.environ.get("MAX_ARTICLES", "260"))    # tetto alle notizie passate a Gemini

# (nome della testata, provincia di riferimento o "", url del feed)
RSS_FEEDS = [
    ("Ansa", "", "https://www.ansa.it/emiliaromagna/notizie/emiliaromagna_rss.xml"),
    ("Il Resto del Carlino", "Bologna", "https://www.ilrestodelcarlino.it/bologna/rss"),
    ("Il Resto del Carlino", "Modena", "https://www.ilrestodelcarlino.it/modena/rss"),
    ("Il Resto del Carlino", "Reggio Emilia", "https://www.ilrestodelcarlino.it/reggio-emilia/rss"),
    ("Il Resto del Carlino", "Ferrara", "https://www.ilrestodelcarlino.it/ferrara/rss"),
    ("Il Resto del Carlino", "Ravenna", "https://www.ilrestodelcarlino.it/ravenna/rss"),
    ("Il Resto del Carlino", "Forlì-Cesena", "https://www.ilrestodelcarlino.it/forli/rss"),
    ("Il Resto del Carlino", "Forlì-Cesena", "https://www.ilrestodelcarlino.it/cesena/rss"),
    ("Il Resto del Carlino", "Rimini", "https://www.ilrestodelcarlino.it/rimini/rss"),
    ("Il Resto del Carlino", "Bologna", "https://www.ilrestodelcarlino.it/imola/rss"),
    ("BolognaToday", "Bologna", "https://www.bolognatoday.it/rss"),
    ("ModenaToday", "Modena", "https://www.modenatoday.it/rss"),
    ("RiminiToday", "Rimini", "https://www.riminitoday.it/rss"),
    ("RavennaToday", "Ravenna", "https://www.ravennatoday.it/rss"),
    ("ParmaToday", "Parma", "https://www.parmatoday.it/rss"),
    ("PiacenzaToday", "Piacenza", "https://www.piacenzatoday.it/rss"),
    ("ForlìToday", "Forlì-Cesena", "https://www.forlitoday.it/rss"),
    ("Gazzetta di Parma", "Parma", "https://www.gazzettadiparma.it/rss/"),
    ("PiacenzaSera", "Piacenza", "https://www.piacenzasera.it/feed/"),
    ("Corriere Romagna", "", "https://www.corriereromagna.it/feed/"),
    ("Estense", "Ferrara", "https://www.estense.com/feed/"),
    ("Il Sole 24 Ore", "", "https://www.ilsole24ore.com/rss/italia--emilia-romagna.xml"),
    # Google News: riempie i vuoti su Regione e Protezione civile (i link portano all'articolo originale)
    ("Google News", "", "https://news.google.com/rss/search?q=%22Regione+Emilia-Romagna%22+when:1d&hl=it&gl=IT&ceid=IT:it"),
    ("Google News", "", "https://news.google.com/rss/search?q=allerta+meteo+Emilia-Romagna+when:1d&hl=it&gl=IT&ceid=IT:it"),
    ("Google News", "", "https://news.google.com/rss/search?q=Reggio+Emilia+when:1d&hl=it&gl=IT&ceid=IT:it"),
]

PROVINCE = ["Bologna", "Modena", "Reggio Emilia", "Parma", "Piacenza",
            "Ferrara", "Ravenna", "Forlì-Cesena", "Rimini"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "it-IT,it;q=0.9",
}

MODELS_TO_TRY = ["gemini-2.5-flash", "gemini-3.5-flash", "gemini-2.5-pro", "gemini-3.5-flash-lite"]

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "rss1": "http://purl.org/rss/1.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
}


# ---------------------------------------------------------------------------
# 1. Lettura dei feed
# ---------------------------------------------------------------------------
def parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d


def clean(s, limit=None):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit] if limit else s


def read_feed(name, prov, url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return name, url, f"HTTP {r.status_code}", []
        root = ET.fromstring(r.content)
    except Exception as e:
        return name, url, f"errore: {type(e).__name__}", []

    nodes = (root.findall(".//item") or root.findall(".//atom:entry", NS)
             or root.findall(".//rss1:item", NS))
    out = []
    for it in nodes[:MAX_PER_FEED]:
        def txt(*tags):
            for t in tags:
                v = it.findtext(t, namespaces=NS)
                if v and v.strip():
                    return v.strip()
            return ""
        title = clean(txt("title", "atom:title", "rss1:title"))
        link = txt("link", "rss1:link")
        if not link:
            a = it.find("atom:link", NS)
            link = a.get("href", "") if a is not None else ""
        desc = clean(txt("description", "atom:summary", "atom:content", "rss1:description"), 400)
        when = parse_date(txt("pubDate", "atom:updated", "atom:published", "dc:date"))
        source = name
        if name == "Google News":
            # il titolo di Google News termina con " - Nome testata"
            m = re.match(r"^(.*)\s+-\s+([^-]{2,40})$", title)
            if m:
                title, source = m.group(1).strip(), m.group(2).strip()
            desc = ""
        if title and link.startswith("http"):
            out.append({"title": title, "link": link, "desc": desc, "date": when,
                        "source": source, "prov": prov})
    return name, url, "ok", out


def fetch_rss_articles():
    print(f"[{TODAY}] Lettura di {len(RSS_FEEDS)} feed...")
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(lambda f: read_feed(*f), RSS_FEEDS))
    for (name, prov, url), (_, _, status, items) in zip(RSS_FEEDS, results):
        FEED_REPORT.append((name, prov, status, len(items)))

    cutoff = NOW - dt.timedelta(hours=MAX_AGE_HOURS)
    articles, seen_links, seen_titles = [], set(), set()
    for name, url, status, items in results:
        kept = 0
        for a in items:
            if a["date"] and a["date"] < cutoff:
                continue
            key_t = re.sub(r"\W+", " ", a["title"].lower()).strip()[:90]
            key_l = a["link"].split("?")[0].rstrip("/")
            if key_l in seen_links or key_t in seen_titles:
                continue
            seen_links.add(key_l)
            seen_titles.add(key_t)
            articles.append(a)
            kept += 1
        print(f"  {'✅' if kept else '⚠️'} {name:22} {status:14} {kept:3} notizie  {url[:70]}")

    articles.sort(key=lambda a: a["date"] or NOW, reverse=True)
    articles = articles[:MAX_ARTICLES]
    print(f"Totale: {len(articles)} notizie uniche delle ultime {MAX_AGE_HOURS} ore.")
    return articles


# ---------------------------------------------------------------------------
# 2. Estratto del testo degli articoli
# ---------------------------------------------------------------------------
def add_fulltext(articles):
    if not trafilatura or MAX_FULLTEXT <= 0:
        return
    targets = [a for a in articles if "news.google.com" not in a["link"]][:MAX_FULLTEXT]

    def grab(a):
        try:
            r = requests.get(a["link"], headers=HEADERS, timeout=10)
            if r.status_code == 200:
                text = trafilatura.extract(r.text, include_comments=False, include_tables=False) or ""
                a["text"] = clean(text, 1200)
        except Exception:
            pass

    t0 = time.time()
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(grab, targets))
    got = sum(1 for a in targets if a.get("text"))
    print(f"Estratti letti: {got}/{len(targets)} in {time.time() - t0:.0f}s")


# ---------------------------------------------------------------------------
# 3. Scrittura della rassegna con Gemini
# ---------------------------------------------------------------------------
GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
MESI = ["", "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
        "agosto", "settembre", "ottobre", "novembre", "dicembre"]
GIORNO = f"{GIORNI[NOW.weekday()]} {NOW.day} {MESI[NOW.month]}"
FEED_REPORT = []

SYSTEM_INSTRUCTION = f"""
Sei il caporedattore di una rassegna stampa quotidiana sull'Emilia-Romagna.
Scrivi in italiano giornalistico, asciutto e preciso: ogni notizia deve contenere i fatti concreti
(chi, cosa, dove, quando, cifre, nomi, ruoli). Niente frasi vaghe o commenti tuoi.
Usa SOLO le informazioni presenti nelle notizie fornite. Non inventare nulla.

FONTI
- Ogni notizia è numerata [n]. Alla fine di ogni notizia scrivi le fonti usate così: <cite>n</cite>,
  oppure <cite>n,m</cite> se più testate riportano la stessa notizia.
- Non scrivere mai URL o tag <a>: i link li inserisce il sistema a partire dai numeri.

UNIRE E SCEGLIERE
- Se più notizie parlano dello stesso fatto, scrivi UNA sola notizia che le combina e cita tutti i numeri.
- Ogni fatto compare UNA sola volta in tutta la rassegna.
- Scarta gossip, sport minore, oroscopi, pubblicità, notizie nazionali senza legame con la regione.

FORMATO (HTML, solo il frammento: niente <html>, <head>, <body>, <style>, <div>, <section>)
- <h2> per le sezioni, <h3> per la provincia, <ul><li> per le notizie (una notizia per <li>).
- Ogni <li> ha questa forma: <li><strong>Titolo breve e informativo</strong> — Luogo: testo di 1-3 frasi con i fatti. <cite>n</cite></li>
  (il luogo è il comune; per le notizie di "In evidenza" è utile anche la provincia)
- Le province vanno scritte esattamente così: {", ".join(PROVINCE)}; per notizie di tutta la regione usa <h3>Emilia-Romagna</h3>.
- Metti una provincia solo se ha notizie: niente righe tipo "nessuna notizia".

SEZIONI, in quest'ordine (ometti una sezione se è vuota):
<h2>In evidenza</h2>  (le 5-7 notizie più importanti della giornata, senza <h3>, poi NON ripeterle sotto)
<h2>Politica e istituzioni</h2>
<h2>Economia, lavoro e imprese</h2>
<h2>Sanità, scuola e sociale</h2>
<h2>Cronaca e giustizia</h2>
<h2>Ambiente, territorio e protezione civile</h2>  (allerte meteo, alluvioni, frane, inquinamento, infrastrutture)
<h2>Cultura ed eventi</h2>  (solo eventi rilevanti, al massimo 8 notizie)
<h2>Da seguire oggi ({GIORNO})</h2>  (senza <h3>: appuntamenti, scioperi, udienze, consigli comunali, scadenze,
   strade chiuse, allerte e eventi di oggi e dei prossimi giorni ricavati dalle notizie; una riga ciascuno)

COMPLETEZZA
- La rassegna deve essere completa e ricca: di norma 70-120 notizie in tutto, con tutte le province
  che hanno notizie. Non fermarti alle notizie principali.

Restituisci solo il frammento HTML, senza blocchi di codice.
"""


def build_prompt(articles):
    lines = []
    for n, a in enumerate(articles, 1):
        when = a["date"].astimezone(ROME).strftime("%d/%m %H:%M") if a["date"] else "n.d."
        prov = f" | provincia: {a['prov']}" if a["prov"] else ""
        lines.append(f"[{n}] {a['source']}{prov} | {when}\nTitolo: {a['title']}")
        if a.get("desc"):
            lines.append(f"Sommario: {a['desc']}")
        if a.get("text"):
            lines.append(f"Estratto: {a['text']}")
        lines.append("")
    return f"Notizie raccolte per l'edizione del {TODAY}:\n\n" + "\n".join(lines) + "\nScrivi la rassegna."


def _finish_reason(resp):
    try:
        return str(resp.candidates[0].finish_reason or "")
    except Exception:
        return ""


def call_gemini(prompt):
    """Scrive la rassegna; se la risposta si interrompe per lunghezza, chiede di continuare."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY non impostata.")
    client = genai.Client(api_key=api_key)

    def config_for(model):
        kw = dict(system_instruction=SYSTEM_INSTRUCTION, temperature=0.25, max_output_tokens=60000)
        # il "ragionamento" interno consuma lo stesso spazio della risposta: lo limitiamo
        if "flash" in model or "pro" in model:
            try:
                kw["thinking_config"] = types.ThinkingConfig(thinking_budget=2048 if "pro" in model else 1024)
            except Exception:
                pass
        return types.GenerateContentConfig(**kw)

    for model in MODELS_TO_TRY:
        for attempt in range(2):
            try:
                print(f"Gemini: {model} (tentativo {attempt + 1})...")
                cfg = config_for(model)
                resp = client.models.generate_content(model=model, contents=prompt, config=cfg)
                text = (resp.text or "").strip()
                if len(text) < 300:
                    print(f"⚠️ {model}: risposta troppo corta ({len(text)} caratteri)")
                    continue
                # continuazioni se il testo è stato troncato
                for part in range(4):
                    reason = _finish_reason(resp)
                    if "MAX_TOKENS" not in reason:
                        break
                    print(f"   ↪️ Risposta interrotta per lunghezza: chiedo di continuare ({part + 1})...")
                    contents = [
                        types.Content(role="user", parts=[types.Part(text=prompt)]),
                        types.Content(role="model", parts=[types.Part(text=text)]),
                        types.Content(role="user", parts=[types.Part(text=(
                            "Continua esattamente dal punto in cui ti sei interrotto, senza ripetere nulla "
                            "e senza commenti, fino a completare tutte le sezioni."))]),
                    ]
                    resp = client.models.generate_content(model=model, contents=contents, config=cfg)
                    text += (resp.text or "")
                n = len(re.findall(r"<li\b", text))
                print(f"✅ Rassegna scritta con {model}: {n} notizie, {len(text)} caratteri")
                if n < 25 and model != MODELS_TO_TRY[-1]:
                    print("⚠️ Troppo poche notizie: provo il modello successivo.")
                    break
                return text
            except Exception as e:
                print(f"⚠️ {model}: {e}")
                time.sleep(4)
    return None


def finalize_html(raw, articles):
    """Pulisce l'HTML del modello e trasforma <cite>n</cite> in link alle fonti."""
    s = re.sub(r"^```(?:html)?\s*|\s*```$", "", raw.strip())
    s = re.sub(r"<style.*?</style>", "", s, flags=re.S | re.I)
    s = re.sub(r"</?(html|head|body|section|div|article|main)[^>]*>", "", s, flags=re.I)
    # tiene il testo di eventuali link scritti dal modello, ma toglie l'indirizzo
    s = re.sub(r"<a\b[^>]*>(.*?)</a>", r"\1", s, flags=re.S | re.I)
    # toglie eventuali preamboli prima del primo titolo
    i = s.find("<h2")
    if i > 0:
        s = s[i:]

    def repl(m):
        nums = []
        for x in re.findall(r"\d+", m.group(1)):
            k = int(x)
            if 1 <= k <= len(articles) and k not in nums:
                nums.append(k)
        if not nums:
            return ""
        links, used = [], set()
        for k in nums:
            a = articles[k - 1]
            if a["source"] in used:
                continue
            used.add(a["source"])
            links.append(f'<a href="{html.escape(a["link"], quote=True)}" target="_blank" '
                         f'rel="noopener">{html.escape(a["source"])}</a>')
        label = "Fonte" if len(links) == 1 else "Fonti"
        return f'<span class="src">{label}: {", ".join(links)}</span>'

    s = re.sub(r"<cite>(.*?)</cite>", repl, s, flags=re.S | re.I)
    # elimina eventuali voci vuote
    s = re.sub(r"<li>\s*</li>", "", s)
    s = re.sub(r"<h3>[^<]*</h3>\s*(?=<h[23]|$)", "", s)
    return s.strip()


def sources_note(articles):
    """Nota finale: quante testate sono state lette e quali feed oggi non rispondevano."""
    testate = sorted({a["source"] for a in articles})
    multi = {n for n, *_ in FEED_REPORT if sum(1 for m, *_ in FEED_REPORT if m == n) > 1}
    ko = sorted({(f"{name} ({prov})" if name in multi and prov else name)
                 for name, prov, status, n in FEED_REPORT if status != "ok" or n == 0})
    txt = (f"<strong>Nota sulle fonti.</strong> Notizie analizzate: {len(articles)}, "
           f"da {len(testate)} testate, pubblicate nelle ultime {MAX_AGE_HOURS} ore.")
    if ko:
        txt += " Oggi non hanno fornito notizie: " + ", ".join(html.escape(k) for k in ko) + "."
    return f'<div class="foot"><p>{txt}</p></div>'


def fallback_html(articles):
    """Se Gemini non risponde: elenco semplice per provincia, senza ripetizioni."""
    by = {}
    for a in articles[:120]:
        by.setdefault(a["prov"] or "Emilia-Romagna", []).append(a)
    parts = ["<h2>Notizie del giorno</h2>",
             "<p class=\"note\">Rassegna automatica non disponibile oggi: elenco dei titoli.</p>"]
    for prov in ["Emilia-Romagna"] + PROVINCE:
        if prov not in by:
            continue
        parts.append(f"<h3>{prov}</h3><ul>")
        for a in by[prov]:
            parts.append(f'<li><strong>{html.escape(a["title"])}</strong> — {html.escape(a["desc"][:240])} '
                         f'<span class="src">Fonte: <a href="{html.escape(a["link"], quote=True)}" '
                         f'target="_blank" rel="noopener">{html.escape(a["source"])}</a></span></li>')
        parts.append("</ul>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 4. Salvataggio e archivio
# ---------------------------------------------------------------------------
def update_indexes(n_items):
    idx_path = os.path.join(OUTPUT_DIR, "index.json")
    editions = {}
    for name in os.listdir(OUTPUT_DIR):
        m = re.match(r"^(\d{4}-\d{2}-\d{2})\.html$", name)
        if m:
            editions[m.group(1)] = {"date": m.group(1)}
    try:
        with open(idx_path, encoding="utf-8") as f:
            for e in json.load(f):
                if e.get("date") in editions:
                    editions[e["date"]].update(e)
    except Exception:
        pass
    editions[TODAY]["items"] = n_items
    ordered = sorted(editions.values(), key=lambda e: e["date"], reverse=True)
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump(ordered, f, ensure_ascii=False, indent=1)
    with open("index.json", "w", encoding="utf-8") as f:
        json.dump({"latest": TODAY}, f)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    articles = fetch_rss_articles()
    if not articles:
        print("Nessuna notizia raccolta: interrompo.")
        return
    add_fulltext(articles)

    raw = call_gemini(build_prompt(articles))
    body = finalize_html(raw, articles) if raw else fallback_html(articles)
    body += "\n" + sources_note(articles)
    n_items = len(re.findall(r"<li\b", body))

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(f"<!-- Rassegna Emilia-Romagna {TODAY} - {len(articles)} notizie analizzate -->\n{body}\n")
    update_indexes(n_items)
    print(f"✅ {OUTPUT_FILE}: {n_items} notizie in rassegna.")


if __name__ == "__main__":
    main()
