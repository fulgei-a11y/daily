"""
Rassegna stampa dell'Emilia-Romagna.

1. Legge i feed RSS delle testate locali e tiene solo le notizie delle ultime ore.
2. Elimina i doppioni e, per le notizie principali, scarica un estratto dell'articolo
   (non solo il sommario del feed): così la sintesi ha dati e nomi concreti.
3. Gemini scrive la rassegna in HTML. Le fonti sono indicate con numeri [n] che lo script
   trasforma in link veri: nessun indirizzo può essere inventato.
4. Salva edizioni/AAAA-MM-GG.html, edizioni/index.json (archivio) e index.json (ultima edizione).

Aggiornamenti delle 13 e delle 19 (python3 tools/fetch_and_analyze.py --slot 13):
legge solo le notizie uscite dopo l'ultima pubblicazione, scarta quelle già in rassegna e salva
edizioni/AAAA-MM-GG-13.html. L'edizione del mattino non viene mai toccata.
"""

import os
import re
import sys
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
MAX_PER_FEED_BO = int(os.environ.get("MAX_PER_FEED_BO", "40"))   # Bologna è il focus: dai suoi feed si leggono più notizie
MAX_AGE_HOURS = int(os.environ.get("MAX_AGE_HOURS", "36"))   # notizie più vecchie vengono scartate
MAX_FULLTEXT = int(os.environ.get("MAX_FULLTEXT", "120"))     # articoli di cui leggere l'estratto
MAX_ARTICLES = int(os.environ.get("MAX_ARTICLES", "440"))    # tetto alle notizie passate a Gemini

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
    ("ForlìToday", "Forlì-Cesena", "https://www.forlitoday.it/rss"),
    ("PiacenzaSera", "Piacenza", "https://www.piacenzasera.it/feed/"),
    ("Estense", "Ferrara", "https://www.estense.com/feed/"),
    # altre testate locali (feed verificati il 10/10/2026)
    ("CesenaToday", "Forlì-Cesena", "https://www.cesenatoday.it/rss"),
    ("FerraraToday", "Ferrara", "https://www.ferraratoday.it/rss"),
    ("IlPiacenza", "Piacenza", "https://www.ilpiacenza.it/rss"),
    ("Reggionline", "Reggio Emilia", "https://www.reggionline.com/feed/"),
    ("ReggioSera", "Reggio Emilia", "https://cdn.reggiosera.it/feed"),
    ("SulPanaro", "Modena", "https://www.sulpanaro.net/feed/"),
    ("RavennaNotizie", "Ravenna", "https://cdn.ravennanotizie.it/feed"),
    ("ParmaDaily", "Parma", "https://www.parmadaily.it/feed/"),
    ("AltaRimini", "Rimini", "https://www.altarimini.it/feed/"),
    # altre testate e tv locali (verificate il 14/10/2026)
    ("Teleromagna", "Forlì-Cesena", "https://www.teleromagna.it/feed"),
    ("Forlì24ore", "Forlì-Cesena", "https://www.forli24ore.it/feed/"),
    ("Ravenna&Dintorni", "Ravenna", "https://www.ravennaedintorni.it/feed/"),
    ("ReggioReport", "Reggio Emilia", "https://www.reggioreport.it/feed/"),
    ("Bologna2000", "Bologna", "https://www.bologna2000.com/feed/"),
    # area metropolitana di Bologna (feed verificati il 18/10/2026)
    ("Sabato Sera", "Bologna", "https://www.sabatosera.it/feed/"),          # Imola e circondario
    ("Leggilanotizia", "Bologna", "https://www.leggilanotizia.it/feed/"),    # Imola
    ("RenoNews", "Bologna", "https://www.renonews.it/feed/"),                # Casalecchio, valle del Reno, Reno Galliera
    ("Sassuolo2000", "Modena", "https://www.sassuolo2000.it/feed/"),
    ("Icaro TV", "Rimini", "https://www.icaro.tv/feed/"),
    ("Modena in diretta", "Modena", "https://www.modenaindiretta.it/feed/"),
    # Google News: riempie i vuoti su Regione e Protezione civile (i link portano all'articolo originale)
    ("Google News", "", "https://news.google.com/rss/search?q=%22Regione+Emilia-Romagna%22+when:1d&hl=it&gl=IT&ceid=IT:it"),
    ("Google News", "", "https://news.google.com/rss/search?q=allerta+meteo+Emilia-Romagna+when:1d&hl=it&gl=IT&ceid=IT:it"),
    ("Google News", "Reggio Emilia", "https://news.google.com/rss/search?q=Reggio+Emilia+when:1d&hl=it&gl=IT&ceid=IT:it"),
    # Google News per testata: i titoli dei giornali il cui feed non risponde ai server di GitHub
    ("Google News", "Parma", "https://news.google.com/rss/search?q=site:gazzettadiparma.it+when:1d&hl=it&gl=IT&ceid=IT:it"),
    ("Google News", "Piacenza", "https://news.google.com/rss/search?q=site:liberta.it+when:1d&hl=it&gl=IT&ceid=IT:it"),
    ("Google News", "", "https://news.google.com/rss/search?q=site:corriereromagna.it+when:1d&hl=it&gl=IT&ceid=IT:it"),
    ("Google News", "Bologna", "https://news.google.com/rss/search?q=site:corrieredibologna.corriere.it+when:1d&hl=it&gl=IT&ceid=IT:it"),
    ("Google News", "Bologna", "https://news.google.com/rss/search?q=site:bologna.repubblica.it+when:1d&hl=it&gl=IT&ceid=IT:it"),
    ("Google News", "Reggio Emilia", "https://news.google.com/rss/search?q=site:gazzettadireggio.it+when:1d&hl=it&gl=IT&ceid=IT:it"),
    ("Google News", "Modena", "https://news.google.com/rss/search?q=site:gazzettadimodena.it+when:1d&hl=it&gl=IT&ceid=IT:it"),
    ("Google News", "Ferrara", "https://news.google.com/rss/search?q=site:lanuovaferrara.it+when:1d&hl=it&gl=IT&ceid=IT:it"),
    ("Google News", "", "https://news.google.com/rss/search?q=site:dire.it+Emilia-Romagna+when:1d&hl=it&gl=IT&ceid=IT:it"),
    # fonti ufficiali (i loro siti non hanno feed utilizzabili: passano da Google News)
    ("Google News", "", "https://news.google.com/rss/search?q=site:notizie.regione.emilia-romagna.it+when:1d&hl=it&gl=IT&ceid=IT:it"),
    ("Google News", "", "https://news.google.com/rss/search?q=site:assemblea.emr.it+when:2d&hl=it&gl=IT&ceid=IT:it"),
    ("Google News", "Bologna", "https://news.google.com/rss/search?q=site:comune.bologna.it+when:2d&hl=it&gl=IT&ceid=IT:it"),
    ("Google News", "", "https://news.google.com/rss/search?q=site:rainews.it+%22Emilia-Romagna%22+OR+Bologna+OR+Modena+OR+Parma+OR+Rimini+when:1d&hl=it&gl=IT&ceid=IT:it"),
    ("Google News", "", "https://news.google.com/rss/search?q=site:questure.poliziadistato.it+(Bologna+OR+Modena+OR+Parma+OR+Reggio+OR+Ferrara+OR+Ravenna+OR+Forl%C3%AC+OR+Rimini+OR+Piacenza)+when:2d&hl=it&gl=IT&ceid=IT:it"),
    ("Google News", "", "https://news.google.com/rss/search?q=site:arpae.it+when:3d&hl=it&gl=IT&ceid=IT:it"),
    # Bologna e area metropolitana: canali dedicati (focus principale della rassegna)
    ("Google News", "Bologna", "https://news.google.com/rss/search?q=site:cittametropolitana.bo.it+when:3d&hl=it&gl=IT&ceid=IT:it"),
    ("Google News", "Bologna", "https://news.google.com/rss/search?q=site:magazine.unibo.it+when:3d&hl=it&gl=IT&ceid=IT:it"),
    ("Google News", "Bologna", "https://news.google.com/rss/search?q=Tper+OR+tram+OR+%22Passante+di+Bologna%22+Bologna+when:1d&hl=it&gl=IT&ceid=IT:it"),
    ("Google News", "Bologna", "https://news.google.com/rss/search?q=Bologna+-calcio+-Serie+when:1d&hl=it&gl=IT&ceid=IT:it"),
    ("Google News", "Bologna", "https://news.google.com/rss/search?q=Imola+when:1d&hl=it&gl=IT&ceid=IT:it"),
    ("Google News", "Bologna", "https://news.google.com/rss/search?q=site:nuovodiario.com+when:1d&hl=it&gl=IT&ceid=IT:it"),   # Il Nuovo Diario Messaggero, Imola: il feed non è leggibile dai server
    ("Google News", "Bologna", "https://news.google.com/rss/search?q=site:telesanterno.com+when:1d&hl=it&gl=IT&ceid=IT:it"),   # Telesanterno, Imola
    ("Google News", "Bologna", "https://news.google.com/rss/search?q=site:ausl.bologna.it+OR+site:aosp.bo.it+when:3d&hl=it&gl=IT&ceid=IT:it"),   # Ausl e Policlinico Sant'Orsola
    ("Google News", "Bologna", "https://news.google.com/rss/search?q=Casalecchio+OR+%22San+Lazzaro+di+Savena%22+OR+%22Zola+Predosa%22+OR+Valsamoggia+OR+Pianoro+-calcio+when:1d&hl=it&gl=IT&ceid=IT:it"),   # cintura
    ("Google News", "Bologna", "https://news.google.com/rss/search?q=%22San+Giovanni+in+Persiceto%22+OR+Budrio+OR+Molinella+OR+Castenaso+OR+%22Castel+Maggiore%22+OR+Medicina+Bologna+-calcio+when:1d&hl=it&gl=IT&ceid=IT:it"),   # pianura
    ("Google News", "Bologna", "https://news.google.com/rss/search?q=%22Appennino+bolognese%22+OR+Porretta+OR+Vergato+OR+%22Alto+Reno%22+OR+Monghidoro+-calcio+when:2d&hl=it&gl=IT&ceid=IT:it"),   # Appennino
    ("Google News", "Bologna", "https://news.google.com/rss/search?q=%22aeroporto+di+Bologna%22+OR+%22aeroporto+Marconi%22+OR+%22stazione+di+Bologna%22+when:1d&hl=it&gl=IT&ceid=IT:it"),   # aeroporto e stazione
    ("Google News", "Bologna", "https://news.google.com/rss/search?q=Bologna+(Comune+OR+Lepore+OR+%22consiglio+comunale%22)+-calcio+when:1d&hl=it&gl=IT&ceid=IT:it"),   # Comune e politica
    ("Google News", "Bologna", "https://news.google.com/rss/search?q=Bologna+(lavoro+OR+sindacati+OR+azienda+OR+sciopero)+-calcio+when:1d&hl=it&gl=IT&ceid=IT:it"),   # economia e lavoro
    ("Google News", "Bologna", "https://news.google.com/rss/search?q=site:bo.it+when:2d&hl=it&gl=IT&ceid=IT:it"),   # siti dei comuni dell'area metropolitana (comune.imola.bo.it, comune.casalecchio.bo.it...)
    ("Google News", "Bologna", "https://news.google.com/rss/search?q=%22consiglio+comunale%22+(Imola+OR+Casalecchio+OR+%22San+Lazzaro%22+OR+Valsamoggia+OR+Budrio+OR+Persiceto+OR+%22Castel+Maggiore%22+OR+Pianoro+OR+Zola+OR+Castenaso+OR+Molinella+OR+Medicina)+when:3d&hl=it&gl=IT&ceid=IT:it"),   # consigli comunali dell'area
    ("Google News", "Bologna", "https://news.google.com/rss/search?q=%22consiglio+comunale%22+Bologna+(%22ordine+del+giorno%22+OR+delibera+OR+approvato+OR+seduta)+when:2d&hl=it&gl=IT&ceid=IT:it"),   # consiglio comunale di Bologna
    ("Google News", "Bologna", "https://news.google.com/rss/search?q=%22consiglio+metropolitano%22+Bologna+when:3d&hl=it&gl=IT&ceid=IT:it"),   # Città metropolitana
    # riserva per le testate il cui feed blocca i server di GitHub (verificato il 18/10/2026)
    ("Google News", "Ferrara", "https://news.google.com/rss/search?q=site:ferraratoday.it+when:1d&hl=it&gl=IT&ceid=IT:it"),
    ("Google News", "Ravenna", "https://news.google.com/rss/search?q=site:ravennaedintorni.it+when:1d&hl=it&gl=IT&ceid=IT:it"),
    ("Google News", "Forlì-Cesena", "https://news.google.com/rss/search?q=site:forli24ore.it+when:1d&hl=it&gl=IT&ceid=IT:it"),
    ("Google News", "Rimini", "https://news.google.com/rss/search?q=site:icaro.tv+when:1d&hl=it&gl=IT&ceid=IT:it"),
    ("Google News", "Modena", "https://news.google.com/rss/search?q=site:modenaindiretta.it+when:1d&hl=it&gl=IT&ceid=IT:it"),
]

# nessuna testata può occupare più di questa quota delle notizie passate a Gemini
# (prima il Resto del Carlino, con 9 feed, arrivava a metà della rassegna)
MAX_SHARE = float(os.environ.get("MAX_SHARE", "0.28"))
# quota delle notizie lette riservata a Bologna e area metropolitana (il resto va alle altre province)
BOLOGNA_SHARE = float(os.environ.get("BOLOGNA_SHARE", "0.55"))

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


def _loose_items(content):
    """Feed con XML rovinato (es. troncato o con caratteri non validi): recupera gli <item> uno per uno."""
    text = content.decode("utf-8", errors="replace")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    nodes = []
    for chunk in re.findall(r"<item\b.*?</item>", text, flags=re.S | re.I):
        try:
            nodes.append(ET.fromstring(chunk))
        except ET.ParseError:
            # ultima spiaggia: entità HTML non dichiarate (&nbsp; ecc.)
            try:
                nodes.append(ET.fromstring(re.sub(r"&(?!(amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)", "&amp;", chunk)))
            except ET.ParseError:
                pass
    return nodes


def read_feed(name, prov, url):
    content = None
    for attempt in range(2):  # un secondo tentativo per gli errori di rete momentanei
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                content = r.content
                break
            status = f"HTTP {r.status_code}"
        except Exception as e:
            status = f"errore: {type(e).__name__}"
        time.sleep(2)
    if content is None:
        return name, url, status, []

    try:
        root = ET.fromstring(content)
        nodes = (root.findall(".//item") or root.findall(".//atom:entry", NS)
                 or root.findall(".//rss1:item", NS))
    except ET.ParseError:
        nodes = _loose_items(content)
        if not nodes:
            return name, url, "XML non valido", []
    out = []
    for it in nodes[:MAX_PER_FEED_BO if prov == "Bologna" else MAX_PER_FEED]:
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


def link_key(url):
    return html.unescape(url).split("?")[0].rstrip("/")


def fetch_rss_articles(since=None, exclude=frozenset()):
    """since: solo le notizie pubblicate dopo questo momento (aggiornamenti);
    exclude: indirizzi già usati nelle pubblicazioni di oggi."""
    print(f"[{TODAY}] Lettura di {len(RSS_FEEDS)} feed...")
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(lambda f: read_feed(*f), RSS_FEEDS))
    for (name, prov, url), (_, _, status, items) in zip(RSS_FEEDS, results):
        FEED_REPORT.append((name, prov, status, len(items)))

    cutoff = since or NOW - dt.timedelta(hours=MAX_AGE_HOURS)
    articles, seen_links, seen_titles = [], set(), set()
    for name, url, status, items in results:
        for a in items:
            a["feed"] = url   # il turno nella scelta delle notizie è per feed (ogni edizione locale conta)
        kept = 0
        for a in items:
            if a["date"] and a["date"] < cutoff:
                continue
            if since and not a["date"]:
                continue  # negli aggiornamenti servono notizie di cui si sa che sono nuove
            key_t = re.sub(r"\W+", " ", a["title"].lower()).strip()[:90]
            key_l = link_key(a["link"])
            if key_l in seen_links or key_t in seen_titles or key_l in exclude:
                continue
            seen_links.add(key_l)
            seen_titles.add(key_t)
            articles.append(a)
            kept += 1
        print(f"  {'✅' if kept else '⚠️'} {name:22} {status:14} {kept:3} notizie  {url[:70]}")

    n0 = len(articles)
    articles = [a for a in articles if not is_sport(a)]
    if n0 != len(articles):
        print(f"   ⚽ Tolte {n0 - len(articles)} notizie sportive.")
    articles.sort(key=lambda a: a["date"] or NOW, reverse=True)
    articles = balance_sources(articles)
    print(f"Totale: {len(articles)} notizie uniche" + (f" uscite dopo le {since.astimezone(ROME):%H:%M}." if since else f" delle ultime {MAX_AGE_HOURS} ore."))
    return articles


def _norm(t):
    import unicodedata
    t = unicodedata.normalize("NFD", (t or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn").replace("’", "'")
    return " " + re.sub(r"[^a-z0-9]+", " ", t).strip() + " "


def _load_bologna_places():
    places = {"bologna", "bolognese", "imolese", "citta metropolitana", "appennino bolognese"}
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "comuni_er.txt")
    try:
        for line in open(path, encoding="utf-8"):
            if line.startswith("BO:"):
                places |= {_norm(c).strip() for c in line[3:].split("|")}
    except OSError:
        pass
    return [f" {p} " for p in places if len(p) > 3 and p not in ("medicina",)]


BO_PLACES = _load_bologna_places()


def is_bologna(a):
    """Notizia di Bologna o dell'area metropolitana: dal feed o dai comuni citati nel titolo e nel sommario."""
    prov = a.get("prov")
    if prov == "Bologna":
        return True
    if prov:   # feed di un'altra provincia: "direzione Bologna" o "come a Bologna" non la rendono di Bologna
        return False
    t = _norm(a.get("title", "") + " " + a.get("desc", ""))
    t = t.replace(" castel bolognese ", " ")   # è in provincia di Ravenna
    return any(p in t for p in BO_PLACES)


def source_key(name):
    """'Il Resto del Carlino' e 'Carlino Imola' contano come la stessa testata."""
    k = name.lower()
    if "carlino" in k:
        return "carlino"
    return re.sub(r"^(il|la|lo)\s+|^l'", "", k).strip()


def _round_robin(articles, limit):
    """A turno tra i FEED (la più recente di ciascuno, poi la seconda, ...), con un tetto per testata."""
    cap = max(12, int(limit * MAX_SHARE))
    groups = {}
    for a in articles:  # già in ordine dalla più recente
        groups.setdefault(a.get("feed") or source_key(a["source"]), []).append(a)
    kept, count, rnd = [], {}, 0
    while len(kept) < limit:
        added = False
        for lst in groups.values():
            if rnd < len(lst) and len(kept) < limit:
                a = lst[rnd]
                k = source_key(a["source"])
                if count.get(k, 0) < cap:
                    kept.append(a)
                    count[k] = count.get(k, 0) + 1
                    added = True
        if not added and all(rnd >= len(l) for l in groups.values()):
            break
        rnd += 1
    return kept, count


def balance_sources(articles):
    """Sceglie le notizie da passare a Gemini.
    - Metà dello spazio (BOLOGNA_SHARE) va a Bologna e area metropolitana, il focus della rassegna;
      quello che Bologna non usa passa alle altre province, e viceversa.
    - Dentro ciascuna parte si sceglie a turno tra i feed, così si coprono tutte le 36 ore e nessuna
      edizione locale resta schiacciata; nessuna testata supera MAX_SHARE della sua parte."""
    for a in articles:
        a["bo"] = is_bologna(a)
    bo_all = [a for a in articles if a["bo"]]
    er_all = [a for a in articles if not a["bo"]]
    bo, c1 = _round_robin(bo_all, int(MAX_ARTICLES * BOLOGNA_SHARE))
    er, c2 = _round_robin(er_all, MAX_ARTICLES - len(bo))
    if len(bo) + len(er) < MAX_ARTICLES and len(bo) < len(bo_all):   # spazio avanzato dalle altre province: torna a Bologna
        bo, c1 = _round_robin(bo_all, MAX_ARTICLES - len(er))
    kept = sorted(bo + er, key=lambda a: a["date"] or NOW, reverse=True)
    count = {k: c1.get(k, 0) + c2.get(k, 0) for k in set(c1) | set(c2)}
    top = sorted(count.items(), key=lambda kv: -kv[1])[:5]
    oldest = min((a["date"] for a in kept if a["date"]), default=None)
    print(f"Bologna e area metropolitana: {len(bo)} notizie (su {len(bo_all)} disponibili); altre province: {len(er)}")
    print("Testate più presenti: " + ", ".join(f"{k} {n}" for k, n in top))
    if oldest:
        print(f"Notizia più vecchia inclusa: {oldest.astimezone(ROME):%d/%m %H:%M}")
    return kept


# ---------------------------------------------------------------------------
# 2. Estratto del testo degli articoli
# ---------------------------------------------------------------------------
def add_fulltext(articles):
    if not trafilatura or MAX_FULLTEXT <= 0:
        return
    readable = [a for a in articles if "news.google.com" not in a["link"]]
    targets = ([a for a in readable if a.get("bo")] + [a for a in readable if not a.get("bo")])[:MAX_FULLTEXT]  # prima Bologna

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
USED_MODEL = None

BO_TEMI = ["Cronaca e sicurezza", "Comune e politica", "Economia e lavoro", "Mobilità, cantieri e trasporti",
           "Sanità, scuola e università", "Cultura ed eventi"]
ER_TEMI = ["Cronaca e giustizia", "Economia e lavoro", "Regione e istituzioni", "Ambiente, allerte e protezione civile"]

_COMMON = f"""
Scrivi in italiano giornalistico, asciutto e preciso: ogni notizia deve contenere i fatti concreti
(chi, cosa, dove, quando, cifre, nomi, ruoli). Niente frasi vaghe o commenti tuoi.
Usa SOLO le informazioni presenti nelle notizie fornite. Non inventare nulla.

FONTI
- Ogni notizia è numerata [n]. Alla fine di ogni notizia scrivi le fonti usate così: <cite>n</cite>,
  oppure <cite>n,m</cite> se più testate riportano la stessa notizia (citale tutte).
- Non scrivere mai URL o tag <a>: i link li inserisce il sistema a partire dai numeri.

UNIRE E SCEGLIERE
- Se più notizie parlano dello stesso fatto, scrivi UNA sola notizia che le combina e cita tutti i numeri.
- Ogni fatto compare UNA sola volta.
- Scarta sempre: sport (di ogni livello), gossip, oroscopi, pubblicità, notizie nazionali senza legame con la regione.

FORMATO (HTML, solo il frammento: niente <html>, <head>, <body>, <style>, <div>, <section>)
- <h2> per le sezioni, <h3> per i temi, <ul><li> per le notizie (una notizia per <li>), sempre dentro <ul>.
- Ogni <li> ha questa forma: <li><strong>Titolo breve e informativo</strong> — Luogo: testo di 1-3 frasi con i fatti. <cite>n</cite></li>
  Il luogo è il comune seguito dalla provincia tra parentesi ("Casalecchio di Reno (Bologna)", "Sassuolo (Modena)");
  per i capoluoghi basta il nome ("Bologna", "Forlì", "Reggio Emilia"); per i fatti di tutta la regione "Emilia-Romagna".
  Province: {", ".join(PROVINCE)}.
- Metti un tema solo se ha notizie. Dentro ogni tema, notizie in ordine di importanza.
- Restituisci solo il frammento HTML, senza blocchi di codice.
"""

AGENDA_RULES = f"""<h2>Da seguire oggi ({GIORNO})</h2>  (senza <h3>, una riga ciascuno, nella stessa forma delle notizie.
   SOLO cose che devono ancora accadere (oggi o nei prossimi giorni) e che servono al cittadino:
   scioperi, cantieri e strade chiuse, consigli comunali e metropolitani con i punti all'ordine del giorno,
   udienze e processi, scadenze, allerte meteo, decisioni attese.
   NO: sagre, feste, mercatini, concerti, mostre, presentazioni di libri, laboratori, gare sportive,
   eventi già passati, previsioni del tempo senza allerta, fatti già scritti nelle sezioni sopra. Se non c'è nulla, ometti la sezione.)"""

# L'edizione del mattino si scrive in tre passaggi: Bologna (solo notizie di Bologna e area metropolitana),
# il resto della regione, e infine Il punto del giorno dai titoli. Così Gemini dedica a Bologna tutta
# la sua attenzione e tutto lo spazio di risposta, invece di riassumere tutto insieme.
SYSTEM_BO = f"""
Sei il caporedattore della sezione BOLOGNA di una rassegna stampa quotidiana: Bologna città e i 55 comuni
dell'area metropolitana (Imola, Casalecchio di Reno, San Lazzaro di Savena, Castel Maggiore, Budrio,
San Giovanni in Persiceto, Valsamoggia, Appennino...). È la parte più importante della rassegna: deve essere
COMPLETA: DEVI scrivere ALMENO 50 notizie (meglio 60-80). Includi ogni fatto concreto di cronaca, politica
locale, economia, lavoro, mobilità, sanità, scuola e università; scarta solo ciò che è davvero irrilevante.
Obiettivi indicativi per tema: Cronaca e sicurezza 15-25 · Comune e politica 10-20 · Economia e lavoro 8-15 ·
Mobilità, cantieri e trasporti 5-10 · Sanità, scuola e università 5-10 · Cultura ed eventi al massimo 6.
Fatti diversi = notizie diverse: non accorpare in una sola notizia fatti distinti solo perché simili.
{_COMMON}
SEZIONI, in quest'ordine:
<h2>Bologna</h2>
{chr(10).join(f"<h3>{t}</h3>" for t in BO_TEMI)}
   - "Cronaca e sicurezza": incidenti, reati, arresti, indagini, processi, incendi, soccorsi, ordine pubblico.
   - "Comune e politica": decisioni e delibere del Comune di Bologna, della Città metropolitana e dei comuni dell'area;
     CONSIGLI COMUNALI (di Bologna e di tutti i comuni dell'area): quando la notizia lo riporta, elenca i
     punti principali all'ordine del giorno o le decisioni prese; partiti e scontri politici su temi concreti.
   - "Mobilità, cantieri e trasporti": tram, Passante, cantieri, chiusure di strade, Tper, treni, aeroporto, scioperi dei trasporti.
   - "Cultura ed eventi": solo gli eventi davvero rilevanti (grandi mostre, concerti, rassegne), al massimo 6.
     Niente sagre, feste di paese, mercatini, laboratori.
{AGENDA_RULES}
   (solo Bologna e area metropolitana, al massimo 14 righe)
"""

SYSTEM_ER = f"""
Sei il caporedattore della sezione EMILIA-ROMAGNA di una rassegna stampa quotidiana: copre il RESTO della
regione (Bologna e la sua area metropolitana hanno una sezione a parte, già scritta: non trattarle).
Di norma 40-60 notizie, SOLO sui temi qui sotto. NIENTE cultura, eventi, sagre, inaugurazioni minori, curiosità.
Copri tutte le province: un fatto importante di una provincia piccola non va trascurato.
{_COMMON}
SEZIONI, in quest'ordine:
<h2>Emilia-Romagna</h2>
{chr(10).join(f"<h3>{t}</h3>" for t in ER_TEMI)}
   - "Cronaca e giustizia": incidenti, reati, arresti, indagini, processi, incendi, soccorsi, scomparsi.
   - "Economia e lavoro": aziende, crisi, assunzioni e licenziamenti, investimenti, sindacati, scioperi, infortuni sul lavoro, prezzi.
   - "Regione e istituzioni": decisioni della Regione e dell'Assemblea legislativa, sanità regionale, fatti istituzionali rilevanti.
   - "Ambiente, allerte e protezione civile": allerte meteo, maltempo con danni, frane, alluvioni, inquinamento.
{AGENDA_RULES}
   (solo il resto della regione, al massimo 8 righe, solo appuntamenti importanti)
"""

SYSTEM_PUNTO = """
Sei il caporedattore di una rassegna stampa con il focus su Bologna. Ricevi i titoli già scritti della
sezione Bologna e della sezione Emilia-Romagna. Scrivi IL PUNTO DEL GIORNO: UN SOLO paragrafo di 4-5 frasi,
come l'apertura di un giornale radio: prima i fatti principali di Bologna, poi in una o due frasi i più
importanti del resto della regione. Solo fatti presenti nei titoli, niente commenti, niente <cite>.
Restituisci solo: <h2>Il punto del giorno</h2><p>...</p>
"""

SYSTEM_INSTRUCTION = SYSTEM_BO   # predefinito di call_gemini



def build_prompt(articles):
    lines = []
    for n, a in enumerate(articles, 1):
        when = a["date"].astimezone(ROME).strftime("%d/%m %H:%M") if a["date"] else "n.d."
        prov = f" | provincia: {a['prov']}" if a["prov"] else ""
        if a.get("bo"):
            prov += " | BOLOGNA"
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


def call_gemini(prompt, system=None, min_items=25, min_len=300):
    """Scrive la rassegna; se la risposta si interrompe per lunghezza, chiede di continuare."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY non impostata.")
    client = genai.Client(api_key=api_key)

    def config_for(model):
        kw = dict(system_instruction=system or SYSTEM_INSTRUCTION, temperature=0.25, max_output_tokens=60000)
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
                if len(text) < min_len:
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
                if n < min_items and model != MODELS_TO_TRY[-1]:
                    print("⚠️ Troppo poche notizie: provo il modello successivo.")
                    break
                global USED_MODEL
                USED_MODEL = model
                return text
            except Exception as e:
                print(f"⚠️ {model}: {e}")
                time.sleep(4)
    return None


def wrap_orphan_li(s):
    """Gemini a volte scrive le <li> senza la <ul> che le contiene: le notizie diventerebbero
    invisibili per la pagina e per l'audio (successo il 13/10 alle 13). Qui le racchiudiamo."""
    parts = re.split(r"(<ul\b[^>]*>|</ul>|<ol\b[^>]*>|</ol>)", s, flags=re.I)
    depth, out = 0, []
    for p in parts:
        if re.match(r"<(ul|ol)\b", p, flags=re.I):
            depth += 1
        elif re.match(r"</(ul|ol)>", p, flags=re.I):
            depth = max(0, depth - 1)
        elif depth == 0:
            p = re.sub(r"((?:\s*<li\b.*?</li>)+)", r"\n<ul>\1\n</ul>", p, flags=re.S | re.I)
        out.append(p)
    return "".join(out)


def wrap_bare_text(s):
    """Testo scritto fuori da ogni paragrafo (Gemini lo fa con Il punto del giorno): lo racchiude in <p>,
    altrimenti pagina e audio lo ignorano."""
    def fix(m):
        t = m.group(1)
        return f"\n<p>{t.strip()}</p>\n" if t.strip() else t
    return re.sub(r"(?<=</h2>)([^<]+)(?=<)", fix, s + "<").rstrip("<")


def cap_section(s, title_re, limit):
    """Tetto alle notizie di una sezione: a turno tra le province (<h3>), così nessuna resta tagliata."""
    m = re.search(rf"(<h2>{title_re}[^<]*</h2>)(.*?)(?=<h2>|$)", s, flags=re.S | re.I)
    if not m:
        return s
    body = m.group(2)
    lis = re.findall(r"<li\b.*?</li>", body, flags=re.S)
    if len(lis) <= limit:
        return s
    groups = [re.findall(r"<li\b.*?</li>", g, flags=re.S) for g in re.split(r"<h3>", body)]
    groups = [g for g in groups if g]
    keep, rnd = set(), 0
    while len(keep) < limit:
        added = False
        for g in groups:
            if rnd < len(g) and len(keep) < limit:
                keep.add(g[rnd]); added = True
        if not added:
            break
        rnd += 1
    for li in lis:
        if li not in keep:
            body = body.replace(li, "", 1)
    body = re.sub(r"<ul>\s*</ul>", "", body)
    body = re.sub(r"<h3>[^<]*</h3>\s*(?=<h3>|$)", "", body)
    print(f"   ✂️ {title_re}: tenute {limit} notizie su {len(lis)}, a turno tra le province.")
    return s[:m.start(2)] + body + s[m.end(2):]


def cap_h3(s, h2_title, h3_prefix, limit):
    """Tetto alle notizie di un tema (<h3>) dentro una sezione (<h2>): tiene le prime, che Gemini mette
    in ordine di importanza."""
    m = re.search(rf"<h2>{h2_title}</h2>(.*?)(?=<h2>|$)", s, flags=re.S)
    if not m:
        return s
    sec = m.group(1)
    t = re.search(rf"<h3>{h3_prefix}[^<]*</h3>\s*<ul>(.*?)</ul>", sec, flags=re.S)
    if not t:
        return s
    lis = re.findall(r"<li\b.*?</li>", t.group(1), flags=re.S)
    if len(lis) <= limit:
        return s
    new_ul = t.group(1)
    for li in lis[limit:]:
        new_ul = new_ul.replace(li, "", 1)
    sec2 = sec[:t.start(1)] + new_ul + sec[t.end(1):]
    print(f"   ✂️ {h2_title} / {h3_prefix}: tenute {limit} notizie su {len(lis)}.")
    return s[:m.start(1)] + sec2 + s[m.end(1):]


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
    s = wrap_orphan_li(s)
    s = wrap_bare_text(s)

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
def update_indexes(n_items, n_articles=0, n_sources=0):
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
    updated = dt.datetime.now(ROME).isoformat(timespec="minutes")
    # "updated" = quando è stata pubblicata l'edizione: la pagina lo mostra in alto
    editions[TODAY].update({"items": n_items, "updated": updated,
                            "articles": n_articles, "sources": n_sources})
    ordered = sorted(editions.values(), key=lambda e: e["date"], reverse=True)
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump(ordered, f, ensure_ascii=False, indent=1)
    with open("index.json", "w", encoding="utf-8") as f:
        json.dump({"latest": TODAY, "updated": updated}, f)


def write_status(n_articles, n_items, fallback, slot="mattina"):
    """stato.json: lo legge il controllo finale del workflow (avviso di errore) e la pagina."""
    feeds = [{"name": n, "prov": p, "status": st, "items": k} for n, p, st, k in FEED_REPORT]
    status = {
        "date": TODAY,
        "slot": slot,
        "generated": dt.datetime.now(ROME).isoformat(timespec="minutes"),
        "articles": n_articles,
        "items": n_items,
        "model": USED_MODEL,
        "fallback": fallback,
        "feeds_ok": sum(1 for f in feeds if f["status"] == "ok" and f["items"]),
        "feeds_total": len(feeds),
        "feeds": feeds,
    }
    with open("stato.json", "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=1)


def _split_agenda(s):
    """Separa la sezione 'Da seguire' dal resto; restituisce (resto, righe dell'agenda)."""
    m = re.search(r"<h2>\s*Da seguire[^<]*</h2>(.*?)(?=<h2>|$)", s, flags=re.S | re.I)
    if not m:
        return s, []
    return (s[:m.start()] + s[m.end():]).strip(), re.findall(r"<li\b.*?</li>", m.group(1), flags=re.S)


AGENDA_NO = re.compile(r"\b(sagr[ae]|fest[ae]\b|mercatin|concert|mostra|laborator|presentazion|libr[oi]\b|"
                       r"spettacol|teatro|gara|torneo|camminata|previsioni meteo|previsioni del tempo|degustazion)", re.I)


def clean_agenda(lis, sections):
    """Toglie dall'agenda gli eventi di svago e i fatti già scritti nelle sezioni (Gemini ignora i divieti)."""
    seen = {clean(t).lower() for t in re.findall(r"<strong>(.*?)</strong>", sections, flags=re.S)}
    out = []
    for li in lis:
        title = clean((re.search(r"<strong>(.*?)</strong>", li, flags=re.S) or [None, li])[1]).lower()
        text = clean(li)
        if title in seen or AGENDA_NO.search(text) and not re.search(r"allert|sciopero|chius", text, re.I):
            continue
        seen.add(title)
        out.append(li)
    return out


def complete_bologna(sec, bo):
    """Se la sezione Bologna è più corta del dovuto, chiede a Gemini le notizie rimaste fuori e le aggiunge
    ai temi giusti. Così la completezza non dipende da quanto Gemini decide di riassumere."""
    want = int(os.environ.get("MIN_BOLOGNA", "45"))
    have = len(re.findall(r"<li\b", sec))
    if have >= want:
        return sec
    written = "\n".join("- " + clean(t) for t in re.findall(r"<strong>(.*?)</strong>", sec, flags=re.S))
    print(f"   ➕ Sezione Bologna con {have} notizie: chiedo a Gemini quelle rimaste fuori...")
    prompt = (f"NOTIZIE GIÀ SCRITTE nella sezione Bologna (NON ripeterle):\n{written}\n\n" + build_prompt(bo) +
              "\nScrivi ADESSO SOLO le notizie di Bologna e area metropolitana che mancano: tutti i fatti concreti non "
              "ancora coperti (cronaca, Comune e politica, consigli comunali, economia e lavoro, mobilità, sanità, scuola). "
              "Stesso formato, con i <h3> dei temi, SENZA <h2> e senza la sezione Da seguire. "
              "Se non manca nulla di rilevante scrivi solo: NESSUNA")
    raw = call_gemini(prompt, system=SYSTEM_BO, min_items=0, min_len=6)
    if not raw or "<li" not in raw:
        return sec
    extra = finalize_html("<h2>x</h2>" + re.sub(r"</?h2[^>]*>", "", raw), bo)
    added = 0
    for m in re.finditer(r"<h3>([^<]*)</h3>\s*<ul>(.*?)</ul>", extra, flags=re.S):
        theme = next((t for t in BO_TEMI if _norm(t)[:8] == _norm(m.group(1))[:8]), None)
        lis = [li for li in re.findall(r"<li\b.*?</li>", m.group(2), flags=re.S)
               if clean((re.search(r"<strong>(.*?)</strong>", li, flags=re.S) or [None, li])[1]).lower()
               not in written.lower()]
        if not theme or not lis:
            continue
        block = re.search(rf"(<h3>{re.escape(theme)}</h3>\s*<ul>)(.*?)(</ul>)", sec, flags=re.S)
        if block:
            sec = sec[:block.end(2)] + "\n" + "\n".join(lis) + "\n" + sec[block.end(2):]
        else:   # tema nuovo: lo mette prima del successivo nell'ordine previsto, o in fondo
            after = BO_TEMI[BO_TEMI.index(theme) + 1:]
            nxt = next((re.search(rf"<h3>{re.escape(t)}</h3>", sec) for t in after if re.search(rf"<h3>{re.escape(t)}</h3>", sec)), None)
            new = f"<h3>{theme}</h3>\n<ul>\n" + "\n".join(lis) + "\n</ul>\n"
            sec = sec[:nxt.start()] + new + sec[nxt.start():] if nxt else sec + "\n" + new
        added += len(lis)
    print(f"   ➕ Aggiunte {added} notizie alla sezione Bologna.")
    return sec


def write_edition(articles):
    """Edizione del mattino in tre passaggi. Restituisce (html, True se almeno una parte è di Gemini)."""
    bo = [a for a in articles if a.get("bo")]
    er = [a for a in articles if not a.get("bo")]
    print(f"Sezione Bologna: {len(bo)} notizie a Gemini · resto della regione: {len(er)}")
    raw_bo = call_gemini(build_prompt(bo), system=SYSTEM_BO, min_items=30) if bo else None
    raw_er = call_gemini(build_prompt(er), system=SYSTEM_ER, min_items=20) if er else None
    if not raw_bo and not raw_er:
        return fallback_html(articles), False
    sec_bo, ag_bo = _split_agenda(finalize_html(raw_bo, bo)) if raw_bo else ("", [])
    sec_er, ag_er = _split_agenda(finalize_html(raw_er, er)) if raw_er else ("", [])
    if not raw_bo:
        sec_bo = fallback_html(bo).replace("<h2>Notizie del giorno</h2>", "<h2>Bologna</h2>")
    if not raw_er:
        sec_er = fallback_html(er).replace("<h2>Notizie del giorno</h2>", "<h2>Emilia-Romagna</h2>")
    if raw_bo:
        sec_bo = complete_bologna(sec_bo, bo)
    sec_bo = cap_h3(sec_bo, "Bologna", "Cultura", int(os.environ.get("MAX_CULTURA_BO", "6")))
    agenda = (clean_agenda(ag_bo, sec_bo + sec_er)[:int(os.environ.get("MAX_AGENDA_BO", "14"))]
              + clean_agenda(ag_er, sec_bo + sec_er)[:int(os.environ.get("MAX_AGENDA_ER", "8"))])

    # Il punto del giorno: dai titoli appena scritti (richiesta breve)
    titoli = lambda s: "\n".join("- " + clean(t) for t in re.findall(r"<strong>(.*?)</strong>", s, flags=re.S)[:40])
    punto = call_gemini(f"SEZIONE BOLOGNA:\n{titoli(sec_bo)}\n\nSEZIONE EMILIA-ROMAGNA:\n{titoli(sec_er)}",
                        system=SYSTEM_PUNTO, min_items=0, min_len=80)
    punto = re.sub(r"^```(?:html)?\s*|\s*```$", "", (punto or "").strip())
    m = re.search(r"<p>.*?</p>", punto, flags=re.S)
    parts = [f"<h2>Il punto del giorno</h2>\n{m.group(0)}"] if m else []
    parts += [sec_bo, sec_er]
    if agenda:
        parts.append(f"<h2>Da seguire oggi ({GIORNO})</h2>\n<ul>\n" + "\n".join(agenda) + "\n</ul>")
    return "\n\n".join(p for p in parts if p.strip()), True


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    articles = fetch_rss_articles()
    if not articles:
        print("❌ Nessuna notizia raccolta: interrompo.")
        write_status(0, 0, True)
        sys.exit(1)
    add_fulltext(articles)

    body, raw = write_edition(articles)
    body += "\n" + sources_note(articles)
    n_items = len(re.findall(r"<li\b", body))

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(f"<!-- Rassegna Emilia-Romagna {TODAY} - {len(articles)} notizie analizzate -->\n{body}\n")
    update_indexes(n_items, len(articles), len({a["source"] for a in articles}))
    write_status(len(articles), n_items, not raw)
    print(f"✅ {OUTPUT_FILE}: {n_items} notizie in rassegna.")


# ---------------------------------------------------------------------------
# 5. Aggiornamenti delle 13 e delle 19
# ---------------------------------------------------------------------------
SLOTS = ("13", "19")
MAX_UPDATE_ITEMS = int(os.environ.get("MAX_UPDATE_ITEMS", "35"))


TEMI = ["Bologna", "Cronaca in regione", "Economia in regione", "Regione e allerte"]

# Sport: fuori dagli aggiornamenti e dall'Ultim'ora (filtro prima di Gemini, poi Gemini scarta il resto)
SPORT_URL = re.compile(r"/(sport|sports|calcio|basket|volley|pallavolo|motori|ciclismo|rugby|tennis|motogp|formula-?1)(/|-|\.)", re.I)
SPORT_TITLE = re.compile(
    # solo parole quasi sempre sportive: "curva", "tifosi", "stadio" restano (possono essere cronaca)
    r"\b(serie [abcd]|calcio|calciomercato|campionato|gol|goal|pareggio|derby|playoff|play-off|allenatore|"
    r"basket|pallavolo|volley|rugby|tennis|motogp|formula 1|ciclismo|"
    r"prima categoria|seconda categoria|terza categoria|under \d+)\b", re.I)


def is_sport(a):
    return bool(SPORT_URL.search(a.get("link", "")) or SPORT_TITLE.search(a.get("title", "")))


def update_system(slot):
    temi = "\n".join(f"<h3>{t}</h3>" for t in TEMI)
    return f"""
Sei il caporedattore di una rassegna stampa sull'Emilia-Romagna. Stai scrivendo l'AGGIORNAMENTO DELLE {slot}
di {GIORNO}: va letto da chi ha già letto l'edizione del mattino{" e l'aggiornamento delle 13" if slot == "19" else ""}.
Scrivi in italiano giornalistico, asciutto e preciso, con i fatti concreti (chi, cosa, dove, quando, cifre, nomi).
Usa SOLO le informazioni presenti nelle notizie fornite. Non inventare nulla.

COSA METTERE (la rassegna ha il FOCUS PRINCIPALE SU BOLOGNA; le notizie di Bologna e area metropolitana sono marcate "| BOLOGNA")
- Bologna: TUTTO ciò che conta a Bologna e nell'area metropolitana (Imola, Casalecchio, San Lazzaro...): cronaca,
  Comune e politica, economia e lavoro, mobilità e cantieri (tram, Passante, Tper, strade chiuse, scioperi), sanità,
  scuola e università. Le notizie di Bologna vanno SEMPRE prima e sono la parte più ricca.
- Cronaca in regione: per le altre province solo incidenti, reati, arresti, indagini, processi, incendi, soccorsi, scomparsi.
- Economia in regione: aziende, crisi, assunzioni e licenziamenti, investimenti, sindacati, scioperi, infortuni sul lavoro, prezzi.
- Regione e allerte: decisioni della Regione, sanità regionale, allerte meteo, maltempo con danni, frane.

SCARTA SEMPRE: sport di ogni livello (anche Serie A); per le province diverse da Bologna anche cultura, spettacoli, mostre, libri, premi, sagre e feste,
eventi e inaugurazioni minori, aperture di negozi, curiosità, gossip, notizie nazionali senza legame con la regione.
Nel dubbio, scarta: meglio 10 notizie importanti che 30 minori.

REGOLE
- Solo fatti NUOVI rispetto ai titoli già pubblicati oggi (elenco A).
- Se una notizia è lo sviluppo di un fatto già pubblicato, includila solo se aggiunge fatti nuovi
  (un arresto, una sentenza, un dato) e comincia il testo con "Sviluppi:".
- Se più notizie parlano dello stesso fatto, scrivine UNA che le combina e cita tutti i numeri.
- Ogni fatto compare UNA sola volta.
- Per il resto della regione: se una provincia ha un fatto importante di cronaca o economia, non trascurarlo.

FONTI
- Ogni notizia nuova è numerata [n]. Alla fine di ogni notizia scrivi <cite>n</cite> o <cite>n,m</cite>.
- Non scrivere mai URL o tag <a>.

FORMATO (solo il frammento HTML, senza blocchi di codice)
<h2>Aggiornamento delle {slot}</h2>
poi, solo per i temi che hanno notizie e in quest'ordine, un <h3> seguito da <ul>:
{temi}
<li><strong>Titolo breve e informativo</strong> — Luogo: testo di 1-3 frasi con i fatti. <cite>n</cite></li>
- Dentro ogni tema, notizie in ordine di importanza; al massimo 30 notizie in tutto.
- Il luogo è il comune seguito dalla provincia tra parentesi ("Sassuolo (Modena)"); per i capoluoghi basta
  il nome; per i fatti di tutta la regione scrivi "Emilia-Romagna". Province: {", ".join(PROVINCE)}.
- Se non c'è nessuna novità rilevante scrivi solo:
<h2>Aggiornamento delle {slot}</h2>
<p class="note">Nessuna novità rilevante rispetto a quanto già pubblicato oggi.</p>
"""


def published_today(upto_slot):
    """Indirizzi e titoli già pubblicati oggi (mattino ed eventuali aggiornamenti precedenti)."""
    files = [f"{TODAY}.html"] + [f"{TODAY}-{s}.html" for s in SLOTS if s < upto_slot]
    links, titles = set(), []
    for name in files:
        path = os.path.join(OUTPUT_DIR, name)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            txt = f.read()
        links |= {link_key(h) for h in re.findall(r'href="([^"]+)"', txt)}
        titles += [clean(t) for t in re.findall(r"<li>\s*<strong>(.*?)</strong>", txt, flags=re.S)]
    # anche le notizie già passate oggi nell'Ultim'ora (solo agenzie, ogni 4 ore)
    try:
        with open("ultimora.json", encoding="utf-8") as f:
            for it in json.load(f).get("items", []):
                if it.get("t", "").startswith(TODAY):
                    links |= set(it.get("links", []))
                    titles.append(it.get("title", ""))
    except Exception:
        pass
    return links, titles


def last_publication(upto_slot):
    """Momento dell'ultima pubblicazione di oggi prima di questo aggiornamento."""
    try:
        with open(os.path.join(OUTPUT_DIR, "index.json"), encoding="utf-8") as f:
            today = next((e for e in json.load(f) if e.get("date") == TODAY), {})
    except Exception:
        today = {}
    times = [today.get("updated")] + [u.get("updated") for u in today.get("updates", []) if u.get("slot", "") < upto_slot]
    times = [dt.datetime.fromisoformat(t) for t in times if t]
    if not times:
        return NOW - dt.timedelta(hours=7)
    # piccolo margine: alcune testate datano gli articoli qualche minuto prima di metterli in linea
    return max(max(times) - dt.timedelta(minutes=30), NOW - dt.timedelta(hours=14))


def register_update(slot, n_items, n_articles):
    idx_path = os.path.join(OUTPUT_DIR, "index.json")
    with open(idx_path, encoding="utf-8") as f:
        editions = json.load(f)
    updated = dt.datetime.now(ROME).isoformat(timespec="minutes")
    for e in editions:
        if e.get("date") == TODAY:
            ups = [u for u in e.get("updates", []) if u.get("slot") != slot]
            ups.append({"slot": slot, "updated": updated, "items": n_items, "articles": n_articles})
            e["updates"] = sorted(ups, key=lambda u: u["slot"])
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump(editions, f, ensure_ascii=False, indent=1)
    with open("index.json", "w", encoding="utf-8") as f:
        json.dump({"latest": TODAY, "updated": updated}, f)


def main_update(slot):
    if not os.path.exists(OUTPUT_FILE):
        # senza l'edizione del mattino non c'è niente da aggiornare: si fa l'edizione completa
        print(f"⚠️ Manca l'edizione del mattino di {TODAY}: genero l'edizione completa.")
        return main()
    since = last_publication(slot)
    links, titles = published_today(slot)
    print(f"Aggiornamento delle {slot}: notizie dopo le {since.astimezone(ROME):%H:%M}, "
          f"{len(titles)} titoli già pubblicati oggi.")
    articles = fetch_rss_articles(since=since, exclude=links)
    n0 = len(articles)
    articles = [a for a in articles if not is_sport(a)]
    if n0 != len(articles):
        print(f"   ⚽ Tolte {n0 - len(articles)} notizie sportive prima di Gemini.")
    out_file = os.path.join(OUTPUT_DIR, f"{TODAY}-{slot}.html")
    raw = None
    if articles:
        add_fulltext(articles)
        known = "\n".join(f"- {t}" for t in titles[:400]) or "- (nessuno)"
        prompt = (f"A) Titoli già pubblicati oggi (NON ripeterli):\n{known}\n\n"
                  + build_prompt(articles).replace("Notizie raccolte per l'edizione del",
                                                   "B) Notizie nuove uscite dopo l'ultima pubblicazione,"))
        raw = call_gemini(prompt, system=update_system(slot), min_items=0, min_len=40)
    if raw:
        body = finalize_html(raw, articles)
        # niente doppioni: stesso titolo = stessa notizia
        seen_t = set()
        for li in re.findall(r"<li\b.*?</li>", body, flags=re.S):
            t = re.sub(r"\W+", " ", clean((re.search(r"<strong>(.*?)</strong>", li, flags=re.S) or [None, li])[1]).lower()).strip()
            if t in seen_t:
                body = body.replace(li, "", 1)
            seen_t.add(t)
        body = re.sub(r"<ul>\s*</ul>", "", body)
        body = re.sub(r"<h3>[^<]*</h3>\s*(?=<h[23]|$)", "", body)
        # tetto fisso: Gemini a volte ne scrive più del richiesto
        lis = re.findall(r"<li\b.*?</li>", body, flags=re.S)
        if len(lis) > MAX_UPDATE_ITEMS:
            for extra in lis[MAX_UPDATE_ITEMS:]:
                body = body.replace(extra, "", 1)
            print(f"   ✂️ Tenute le prime {MAX_UPDATE_ITEMS} notizie su {len(lis)}.")
    elif articles:
        body = (f"<h2>Aggiornamento delle {slot}</h2>\n<ul>\n" + "\n".join(
            f'<li><strong>{html.escape(a["title"])}</strong> — {html.escape(a["desc"][:200])} '
            f'<span class="src">Fonte: <a href="{html.escape(a["link"], quote=True)}" target="_blank" '
            f'rel="noopener">{html.escape(a["source"])}</a></span></li>' for a in articles[:25]) + "\n</ul>")
    else:
        body = (f"<h2>Aggiornamento delle {slot}</h2>\n"
                '<p class="note">Nessuna nuova notizia dalle testate dopo l\'ultima pubblicazione.</p>')
    n_items = len(re.findall(r"<li\b", body))
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(f"<!-- Rassegna Emilia-Romagna {TODAY} - aggiornamento delle {slot} - "
                f"{len(articles)} notizie nuove analizzate -->\n{body}\n")
    register_update(slot, n_items, len(articles))
    write_status(len(articles), n_items, bool(articles) and raw is None, slot=slot)
    print(f"✅ {out_file}: {n_items} notizie nell'aggiornamento.")


if __name__ == "__main__":
    if "--slot" in sys.argv:
        slot = sys.argv[sys.argv.index("--slot") + 1]
        if slot in SLOTS:
            main_update(slot)
        else:
            main()
    else:
        main()
