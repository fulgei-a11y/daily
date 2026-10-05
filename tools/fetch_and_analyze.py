#!/usr/bin/env python3
"""
tools/fetch_and_analyze.py
--------------------------
Script definitivo per l'estrazione quotidiana di notizie dalle 9 province dell'Emilia-Romagna.
- Copertura equa di tutte e 9 le province (3 fonti per provincia).
- Filtro temporale (max 36 ore) e deduplicazione automatica.
- Blocco totale di sport, gossip e notizie riempitive.
- Estrazione full-text protetta con timeout e fallback su descrizione RSS.
- Formattazione HTML strutturata per la Web App via Gemini API.
"""

import os
import sys
import re
import time
from datetime import datetime, timedelta, timezone
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
import requests
import trafilatura
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# CONFIGURAZIONE GENERALE E DATE
# ---------------------------------------------------------------------------
NOW = datetime.now(timezone.utc)
TODAY_STR = NOW.strftime("%Y-%m-%d")
TODAY_HUMAN = NOW.strftime("%d %B %Y")
CUTOFF_TIME = NOW - timedelta(hours=36)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
}

# MAPPA DELLE PROVINCE E RELATIVI FEED RSS (3 Fonti dedicate per ciascuna provincia)
PROVINCIAL_FEEDS = {
    "Regionali/Economia": [
        {"url": "https://www.ansa.it/emiliaromagna/notizie/emiliaromagna_rss.xml", "source": "ANSA E-R"},
        {"url": "https://www.regione.emilia-romagna.it/notizie/RSS", "source": "Regione E-R"}
    ],
    "Bologna": [
        {"url": "https://www.ilrestodelcarlino.it/bologna/rss", "source": "Il Resto del Carlino Bologna"},
        {"url": "https://www.bolognatoday.it/rss", "source": "BolognaToday"},
        {"url": "https://www.ilrestodelcarlino.it/imola/rss", "source": "Il Resto del Carlino Imola"}
    ],
    "Modena": [
        {"url": "https://www.ilrestodelcarlino.it/modena/rss", "source": "Il Resto del Carlino Modena"},
        {"url": "https://www.modenatoday.it/rss", "source": "ModenaToday"}
    ],
    "Reggio Emilia": [
        {"url": "https://www.ilrestodelcarlino.it/reggio-emilia/rss", "source": "Il Resto del Carlino Reggio Emilia"},
        {"url": "https://www.reggiotoday.it/rss", "source": "ReggioToday"},
        {"url": "https://www.reggionline.com/feed/", "source": "Reggionline"}
    ],
    "Parma": [
        {"url": "https://www.gazzettadiparma.it/rss/", "source": "Gazzetta di Parma"},
        {"url": "https://www.parmatoday.it/rss", "source": "ParmaToday"}
    ],
    "Piacenza": [
        {"url": "https://www.liberta.it/feed/", "source": "Libertà Piacenza"},
        {"url": "https://www.piacenzatoday.it/rss", "source": "PiacenzaToday"},
        {"url": "https://www.piacenzasera.it/feed/", "source": "PiacenzaSera"}
    ],
    "Ferrara": [
        {"url": "https://www.ilrestodelcarlino.it/ferrara/rss", "source": "Il Resto del Carlino Ferrara"},
        {"url": "https://www.ferraratoday.it/rss", "source": "FerraraToday"},
        {"url": "https://www.estense.com/feed/", "source": "Estense.com"}
    ],
    "Ravenna": [
        {"url": "https://www.ilrestodelcarlino.it/ravenna/rss", "source": "Il Resto del Carlino Ravenna"},
        {"url": "https://www.ravennatoday.it/rss", "source": "RavennaToday"}
    ],
    "Forlì-Cesena": [
        {"url": "https://www.ilrestodelcarlino.it/forli/rss", "source": "Il Resto del Carlino Forlì"},
        {"url": "https://www.ilrestodelcarlino.it/cesena/rss", "source": "Il Resto del Carlino Cesena"},
        {"url": "https://www.forlitoday.it/rss", "source": "ForlìToday"}
    ],
    "Rimini": [
        {"url": "https://www.ilrestodelcarlino.it/rimini/rss", "source": "Il Resto del Carlino Rimini"},
        {"url": "https://www.riminitoday.it/rss", "source": "RiminiToday"}
    ]
}

# ---------------------------------------------------------------------------
# UTILITIES DI PARSING E DEDUPLICAZIONE
# ---------------------------------------------------------------------------
def clean_xml_text(raw_bytes: bytes) -> str:
    """Rimuove caratteri di controllo ASCII non validi per l'XML."""
    text = raw_bytes.decode('utf-8', errors='ignore')
    return re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]', '', text)

def parse_pub_date(date_str: str) -> datetime:
    """Parsing della data di pubblicazione dagli RSS."""
    if not date_str:
        return None
    try:
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None

def make_title_key(title: str) -> str:
    """Genera una chiave per la deduplicazione basata sulle prime 5 parole significative."""
    norm = re.sub(r'\W+', ' ', title.lower()).strip()
    words = norm.split()
    return " ".join(words[:5]) if words else ""

def fetch_rss_balanced() -> list:
    """Estrae articoli in modo equo garantendo copertura per ogni provincia."""
    selected_articles = []
    seen_keys = set()
    print(f"[{TODAY_STR}] Avvio estrazione bilanciata per le 9 province dell'Emilia-Romagna...")

    for category, feeds in PROVINCIAL_FEEDS.items():
        category_count = 0
        for feed_info in feeds:
            if category_count >= 3:
                break
            try:
                resp = requests.get(feed_info["url"], headers=HEADERS, timeout=8)
                if resp.status_code != 200:
                    continue

                cleaned_xml = clean_xml_text(resp.content)
                root = ET.fromstring(cleaned_xml)
                items = root.findall('.//item') or root.findall('.//{http://www.w3.org/2005/Atom}entry')

                for item in items[:6]:
                    if category_count >= 3:
                        break

                    title = item.findtext('title') or item.findtext('{http://www.w3.org/2005/Atom}title') or ""
                    link = item.findtext('link') or item.findtext('{http://www.w3.org/2005/Atom}href') or ""
                    desc = item.findtext('description') or item.findtext('{http://www.w3.org/2005/Atom}summary') or ""
                    pub_date_raw = item.findtext('pubDate') or item.findtext('{http://www.w3.org/2005/Atom}updated') or ""

                    dt = parse_pub_date(pub_date_raw)
                    if dt and dt < CUTOFF_TIME:
                        continue

                    title_clean = title.strip()
                    title_key = make_title_key(title_clean)
                    if not title_clean or not link.strip() or title_key in seen_keys:
                        continue

                    seen_keys.add(title_key)
                    clean_desc = re.sub(r'<[^>]+>', '', desc).strip()

                    selected_articles.append({
                        'province_cat': category,
                        'title': title_clean,
                        'link': link.strip(),
                        'source': feed_info["source"],
                        'description': clean_desc
                    })
                    category_count += 1
            except Exception:
                continue

    print(f"Estratti {len(selected_articles)} articoli unici e bilanciati su tutte le province.")

    # Estrazione del testo completo via HTTP + Trafilatura con fallback sicuro
    full_articles = []
    print("Avvio estrazione contenuto full-text con timeout di sicurezza...")
    for art in selected_articles:
        try:
            res = requests.get(art['link'], headers=HEADERS, timeout=5)
            if res.status_code == 200:
                text = trafilatura.extract(res.text, include_comments=False, include_tables=False)
                final_text = text if text and len(text) > 150 else art['description']
            else:
                final_text = art['description']
        except Exception:
            final_text = art['description']

        full_articles.append({
            'province_cat': art['province_cat'],
            'title': art['title'],
            'link': art['link'],
            'source': art['source'],
            'content': final_text[:2000]
        })

    return full_articles

# ---------------------------------------------------------------------------
# GENERAZIONE RASSEGNA VIA GEMINI API
# ---------------------------------------------------------------------------
def generate_executive_newsletter(articles: list) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERRORE: GEMINI_API_KEY non trovata nell'ambiente.")
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    articles_payload = ""
    for idx, art in enumerate(articles, 1):
        articles_payload += f"\n--- ARTICOLO {idx} [Area: {art['province_cat']}] ---\n"
        articles_payload += f"TITOLO: {art['title']}\n"
        articles_payload += f"TESTATA: {art['source']}\n"
        articles_payload += f"LINK: {art['link']}\n"
        articles_payload += f"TESTO: {art['content']}\n"

    system_instruction = """
Sei un Senior Editor e Analyst. Il tuo compito è produrre la RASSEGNA STAMPA DELL'EMILIA-ROMAGNA analizzando ESCLUSIVAMENTE gli articoli forniti.

REGOLE TASSATIVE:
1. RIGOROSAMENTE VIETATO LO SPORT:
   - Escludi calcio, basket, sport dilettantistico, gare podistiche, pagelle o calciomercato.
2. NO GOSSIP E NO METEO ORDINARIO:
   - Mantieni un profilo executive. Includi solo allerte ufficiali della Protezione Civile, cronaca vera ed economia reale.
3. STRUTTURA OBBLIGATORIA PER TUTTE LE 9 PROVINCE:
   Nel blocco Cronaca DEVI INCLUDERE OBBLIGATORIAMENTE TUTTI E 9 GLI INTESTAZIONI H3 NELL'ORDINE ESATTO:
   - Bologna (e Imola)
   - Modena
   - Reggio Emilia
   - Parma
   - Piacenza
   - Ferrara
   - Ravenna
   - Forlì-Cesena
   - Rimini

   Se per una provincia non ci sono notizie tra gli articoli forniti, scrivi tassativamente:
   "<p>Nessun fatto straordinario di cronaca segnalato nelle ultime 24 ore.</p>"

4. CITAZIONI E LINK:
   Usa sempre la TESTATA fornita e formatta i link esaminati come segue:
   Fonte: <a target="_blank" rel="noopener" href="URL">TESTATA</a>

FORMATO HTML RICHIESTO (Restituisci SOLO il codice HTML senza blocchi ```html):

<h2>In evidenza</h2>
<div class="evid">
  <ol>
    <li><strong>Titolo</strong> — sintesi con fatti e cifre. Fonte: <a target="_blank" rel="noopener" href="URL">TESTATA</a></li>
  </ol>
</div>

<h2>Cronaca</h2>
<h3>Bologna (e Imola)</h3>
<p><strong>Titolo</strong> — comune: fatto circostanziato. Fonte: <a target="_blank" rel="noopener" href="URL">TESTATA</a></p>

<h3>Modena</h3>
<p>...</p>

<h3>Reggio Emilia</h3>
<p>...</p>

<h3>Parma</h3>
<p>...</p>

<h3>Piacenza</h3>
<p>...</p>

<h3>Ferrara</h3>
<p>...</p>

<h3>Ravenna</h3>
<p>...</p>

<h3>Forlì-Cesena</h3>
<p>...</p>

<h3>Rimini</h3>
<p>...</p>

<h2>Economia e lavoro</h2>
<h3>Imprese e vertenze</h3>
<p>...</p>
<h3>Dati e congiuntura</h3>
<p>...</p>
<h3>Regione e istituzioni</h3>
<p>...</p>
<h3>Infrastrutture, agricoltura, turismo</h3>
<p>...</p>

<h2>Politica e amministrazione</h2>
<p>...</p>

<h2>Da seguire oggi</h2>
<ul>
  <li>...</li>
</ul>
"""

    prompt = f"Data di oggi: {TODAY_HUMAN}\n\nArticoli estratti da analizzare:\n{articles_payload}"

    print("Generazione rassegna con Gemini API (gemini-2.5-flash)...")
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.1,
            max_output_tokens=8192
        )
    )

    return response.text

# ---------------------------------------------------------------------------
# MAIN EXECUTION
# ---------------------------------------------------------------------------
def main():
    start_time = time.time()
    articles = fetch_rss_balanced()
    if not articles:
        print("Nessun articolo estratto dai feed. Interruzione script.")
        sys.exit(1)

    html_output = generate_executive_newsletter(articles)
    
    # Pulizia rigorosa da qualsiasi blocco di codice markdown (```html / ```)
    clean_html = re.sub(r'^```[a-z]*\s*', '', html_output, flags=re.MULTILINE)
    clean_html = re.sub(r'```$', '', clean_html, flags=re.MULTILINE).strip()

    out_dir = "edizioni"
    os.makedirs(out_dir, exist_ok=True)
    out_filepath = os.path.join(out_dir, f"{TODAY_STR}.html")

    with open(out_filepath, "w", encoding="utf-8") as f:
        f.write(clean_html)

    elapsed = round(time.time() - start_time, 2)
    print(f"[{TODAY_STR}] Rassegna completa generata con successo in {out_filepath} in {elapsed}s.")

if __name__ == "__main__":
    main()
