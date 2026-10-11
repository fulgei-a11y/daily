"""
Ultim'ora della Rassegna ER: ogni 4 ore (8, 12, 16, 20, 24) le notizie più recenti
dalle sole agenzie di stampa, solo cronaca ed economia, solo Emilia-Romagna.

- Agenzie regionali (ANSA Emilia-Romagna): tutte le notizie.
- Agenzie nazionali (ANSA, AGI, Adnkronos, askanews, Italpress, Dire) e Dagospia: solo le notizie
  che nominano un comune dell'Emilia-Romagna (elenco in tools/comuni_er.txt).
- Per ogni agenzia ci sono più canali (feed diretto e Google News): se uno non risponde ai server
  di GitHub, si usa l'altro. In ultimora.json resta scritto quali canali hanno funzionato.
- Niente doppioni: si scartano le notizie già passate nell'Ultim'ora e quelle già nelle edizioni di oggi.
- Gemini tiene solo cronaca ed economia e scrive una riga per fatto.

Salva ultimora.json (le notizie delle ultime 36 ore; la pagina mostra le ultime 12).
"""
import datetime as dt
import html
import json
import os
import re
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote_plus

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_and_analyze as R  # noqa: E402  (stesse funzioni di lettura dei feed e di Gemini)

ROME = R.ROME
NOW = dt.datetime.now(ROME)
STORE = "ultimora.json"
KEEP_HOURS = 36          # quanto resta nel file
WINDOW_HOURS = 6         # notizie più vecchie di così non entrano (i doppioni li toglie comunque l'elenco "seen")
MAX_ITEMS_RUN = 25

ER_QUERY = ('("Emilia-Romagna" OR Bologna OR Modena OR Parma OR "Reggio Emilia" OR Ferrara OR Ravenna '
            'OR Rimini OR Forlì OR Cesena OR Piacenza OR Imola OR Carpi OR Faenza OR Sassuolo)')


def gnews(site):
    q = quote_plus(f"site:{site} {ER_QUERY} when:1d")
    return f"https://news.google.com/rss/search?q={q}&hl=it&gl=IT&ceid=IT:it"


# (agenzia, solo_regione_già_garantita, url)
AGENCY_FEEDS = [
    ("ANSA", True, "https://www.ansa.it/emiliaromagna/notizie/emiliaromagna_rss.xml"),
    ("ANSA", False, "https://www.ansa.it/sito/notizie/cronaca/cronaca_rss.xml"),
    ("ANSA", False, "https://www.ansa.it/sito/notizie/economia/economia_rss.xml"),
    ("AGI", False, "https://www.agi.it/cronaca/rss"),
    ("AGI", False, "https://www.agi.it/economia/rss"),
    ("AGI", False, gnews("agi.it")),
    ("Adnkronos", False, "https://www.adnkronos.com/RSS_Cronaca.xml"),
    ("Adnkronos", False, "https://www.adnkronos.com/RSS_Economia.xml"),
    ("Adnkronos", False, gnews("adnkronos.com")),
    ("askanews", False, "https://www.askanews.it/cronaca/feed/"),
    ("askanews", False, "https://www.askanews.it/economia/feed/"),
    ("askanews", False, gnews("askanews.it")),
    ("Italpress", False, "https://www.italpress.com/feed/"),
    ("Italpress", False, gnews("italpress.com")),
    ("Dire", False, "https://www.dire.it/feed/"),
    ("Dire", False, gnews("dire.it")),
    # Dagospia non è un'agenzia: aggiunta su richiesta, solo per le notizie sull'Emilia-Romagna
    ("Dagospia", False, gnews("dagospia.com")),
]

# nomi di comuni che sono anche parole comuni o cognomi: da soli non bastano
AMBIGUI = {"cento", "medicina", "ferriere", "bore", "bardi", "ottone", "gualtieri", "casina", "vetto",
           "zerba", "re", "romagna", "monte", "neviano", "sala", "granarolo", "galeata", "baiso", "verghereto"}


def norm(t):
    t = unicodedata.normalize("NFD", t.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn").replace("’", "'")
    return " " + re.sub(r"[^a-z0-9]+", " ", t).strip() + " "


def load_places():
    places = {"emilia romagna", "emiliano romagnolo", "emiliano romagnola", "riviera romagnola",
              "bolognese", "modenese", "parmense", "reggiano", "piacentino", "ferrarese", "ravennate",
              "forlivese", "cesenate", "riminese"}
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "comuni_er.txt")
    with open(path, encoding="utf-8") as f:
        for line in f:
            if ":" in line and not line.startswith("#"):
                for c in line.split(":", 1)[1].split("|"):
                    k = norm(c).strip()
                    if len(k) > 2 and k not in AMBIGUI:
                        places.add(k)
    return [f" {p} " for p in places]


PLACES = load_places()


def about_er(text):
    t = norm(text)
    return any(p in t for p in PLACES)


# ---------------------------------------------------------------------------
def load_store():
    try:
        with open(STORE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"items": [], "seen": {}}


def published_today():
    """Indirizzi e titoli già nelle edizioni di oggi (mattino e aggiornamenti)."""
    today = NOW.strftime("%Y-%m-%d")
    links, titles = set(), []
    for name in [f"{today}.html", f"{today}-13.html", f"{today}-19.html"]:
        path = os.path.join("edizioni", name)
        if os.path.exists(path):
            txt = open(path, encoding="utf-8").read()
            links |= {R.link_key(h) for h in re.findall(r'href="([^"]+)"', txt)}
            titles += [R.clean(t) for t in re.findall(r"<li>\s*<strong>(.*?)</strong>", txt, flags=re.S)]
    return links, titles


SYSTEM = f"""
Sei il redattore dell'ULTIM'ORA di una rassegna stampa sull'Emilia-Romagna. Ricevi lanci di agenzia numerati [n].

TIENI SOLO notizie che riguardano l'Emilia-Romagna e che sono:
- CRONACA: incidenti, reati, arresti, indagini, processi e sentenze, incendi, soccorsi, persone scomparse,
  maltempo o emergenze con danni o disagi concreti;
- ECONOMIA: aziende, lavoro, licenziamenti e assunzioni, crisi industriali, investimenti, sindacati e scioperi,
  infortuni sul lavoro, dati economici, prezzi, banche, agricoltura e turismo come attività economiche.
SCARTA tutto il resto: politica, sport, cultura, spettacolo, gossip, eventi, meteo senza danni,
notizie che non riguardano l'Emilia-Romagna, e i fatti già pubblicati oggi (elenco A).
Se più lanci parlano dello stesso fatto, scrivi UNA sola notizia che cita tutti i numeri.

FORMATO: solo righe <li>, dalla più recente, al massimo {MAX_ITEMS_RUN}:
<li data-cat="Cronaca"><strong>Titolo breve e informativo</strong> — Luogo (Provincia): una o due frasi con i fatti. <cite>n</cite></li>
- data-cat vale "Cronaca" oppure "Economia".
- Il luogo è il comune con la provincia tra parentesi; per i capoluoghi basta il nome. Province: {", ".join(R.PROVINCE)}.
- Usa SOLO le informazioni dei lanci; non scrivere mai URL o tag <a>.
Se non resta nessuna notizia scrivi solo: NESSUNA
"""


def next_run_label():
    for h in (8, 12, 16, 20, 24):
        if NOW.hour < h:
            return "alle 24" if h == 24 else f"alle {h}"
    return "alle 8"


def main():
    store = load_store()
    # pulizia: via le notizie e i "già visti" più vecchi di KEEP_HOURS
    limit = NOW - dt.timedelta(hours=KEEP_HOURS)
    store["items"] = [i for i in store.get("items", []) if dt.datetime.fromisoformat(i["t"]) >= limit]
    store["seen"] = {k: v for k, v in store.get("seen", {}).items() if dt.datetime.fromisoformat(v) >= limit}

    pub_links, pub_titles = published_today()
    seen = set(store["seen"]) | pub_links
    for it in store["items"]:
        seen |= set(it.get("links", []))
    known_titles = pub_titles + [it.get("title", "") for it in store["items"]]

    print(f"[{NOW:%Y-%m-%d %H:%M}] Ultim'ora: lettura di {len(AGENCY_FEEDS)} canali delle agenzie...")
    R.MAX_PER_FEED = 60   # i feed nazionali hanno molte notizie: quelle sulla regione sono poche
    with ThreadPoolExecutor(8) as ex:
        # "Google News" come nome: read_feed toglie dal titolo il " - Testata" finale
        results = list(ex.map(lambda f: R.read_feed("Google News" if "news.google.com" in f[2] else f[0], "", f[2]),
                              AGENCY_FEEDS))

    cutoff = NOW - dt.timedelta(hours=WINDOW_HOURS)
    report, articles, seen_t = [], [], set()
    for (agency, regional, url), (_, _, status, items) in zip(AGENCY_FEEDS, results):
        kept = 0
        for a in items:
            if not a["date"] or a["date"] < cutoff:
                continue
            k = R.link_key(a["link"])
            tk = re.sub(r"\W+", " ", a["title"].lower()).strip()[:90]
            if k in seen or tk in seen_t:
                continue
            if not regional and not about_er(a["title"] + " " + a.get("desc", "")):
                continue
            if R.is_sport(a):
                continue
            a["source"] = agency
            seen_t.add(tk)
            articles.append(a)
            kept += 1
        channel = "Google News" if "news.google.com" in url else "feed diretto"
        report.append({"agency": agency, "channel": channel, "status": status, "items": len(items), "kept": kept})
        print(f"  {'✅' if status == 'ok' else '⚠️'} {agency:10} {channel:12} {status:14} {len(items):3} letti {kept:3} nuovi")

    articles.sort(key=lambda a: a["date"], reverse=True)
    articles = articles[:120]
    for a in articles:
        store["seen"][R.link_key(a["link"])] = NOW.isoformat(timespec="minutes")
    print(f"Lanci nuovi sull'Emilia-Romagna: {len(articles)}")

    new_items, fallback = [], False
    if articles:
        R.add_fulltext(articles)
        known = "\n".join(f"- {t}" for t in known_titles[-300:]) or "- (nessuno)"
        lines = []
        for n, a in enumerate(articles, 1):
            when = a["date"].astimezone(ROME).strftime("%d/%m %H:%M")
            lines.append(f"[{n}] {a['source']} | {when}\nTitolo: {a['title']}")
            if a.get("desc"):
                lines.append(f"Sommario: {a['desc']}")
            if a.get("text"):
                lines.append(f"Estratto: {a['text'][:700]}")
            lines.append("")
        prompt = f"A) Fatti già pubblicati oggi (NON ripeterli):\n{known}\n\nB) Lanci di agenzia:\n\n" + "\n".join(lines)
        raw = R.call_gemini(prompt, system=SYSTEM, min_items=0, min_len=6)
        if raw is None:
            fallback = True
        elif "<li" in raw:
            body = R.finalize_html(raw, articles)
            found = list(re.finditer(r'<li(?:\s+data-cat="([^"]*)")?\s*>(.*?)</li>', body, flags=re.S))
            for m in found[:MAX_ITEMS_RUN]:
                cat = (m.group(1) or "").strip().capitalize()
                inner = m.group(2).strip()
                title = R.clean((re.search(r"<strong>(.*?)</strong>", inner, flags=re.S) or [None, inner[:80]])[1])
                links = [R.link_key(h) for h in re.findall(r'href="([^"]+)"', inner)]
                new_items.append({"t": NOW.isoformat(timespec="minutes"),
                                  "cat": cat if cat in ("Cronaca", "Economia") else "",
                                  "title": title, "links": links, "html": inner})

    store["items"] = new_items + store["items"]
    store["updated"] = NOW.isoformat(timespec="minutes")
    store["next"] = next_run_label()
    store["last_run"] = {"at": store["updated"], "articles": len(articles), "items": len(new_items),
                         "model": R.USED_MODEL, "fallback": fallback, "feeds": report}
    with open(STORE, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=1)
    print(f"✅ Ultim'ora: {len(new_items)} notizie nuove ({len(store['items'])} nelle ultime {KEEP_HOURS} ore).")


if __name__ == "__main__":
    main()
