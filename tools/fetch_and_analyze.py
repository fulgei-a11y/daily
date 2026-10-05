#!/usr/bin/env python3
"""
tools/fetch_and_analyze.py
--------------------------
Script definitivo per l'estrazione quotidiana di notizie dai feed RSS dell'Emilia-Romagna,
filtro temporale sulle 24 ore, pulizia/deduplicazione e sintesi strutturata via Gemini API.
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
CUTOFF_TIME = NOW - timedelta(hours=36)  # Finestra di tolleranza max 36 ore per gli RSS

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Mappatura bilanciata dei feed RSS per garantire la copertura di tutte le 9 province
RSS_FEEDS = [
    # Regionali e Agenzie
    {"url": "https://www.ansa.it/emiliaromagna/notizie/emiliaromagna_rss.xml", "source": "ANSA Emilia-Romagna"},
    {"url": "https://www.regione.emilia-romagna.it/notizie/RSS", "source": "Regione E-R"},
    
    # Bologna / Imola
    {"url": "https://www.ilrestodelcarlino.it/bologna/rss", "source": "Il Resto del Carlino Bologna"},
    {"url": "https://bologna.repubblica.it/rss", "source": "La Repubblica Bologna"},
    {"url": "https://www.bolognatoday.it/rss", "source": "BolognaToday"},
    {"url": "https://www.ilrestodelcarlino.it/imola/rss", "source": "Il Resto del Carlino Imola"},

    # Modena
    {"url": "https://www.ilrestodelcarlino.it/modena/rss", "source": "Il Resto del Carlino Modena"},
    {"url": "https://www.modenatoday.it/rss", "source": "ModenaToday"},

    # Reggio Emilia
    {"url": "https://www.ilrestodelcarlino.it/reggio-emilia/rss", "source": "Il Resto del Carlino Reggio Emilia"},
    {"url": "https://www.reggionline.com/feed/", "source": "Reggionline"},

    # Parma
    {"url": "https://www.gazzettadiparma.it/rss/", "source": "Gazzetta di Parma"},
    {"url": "https://www.parmatoday.it/rss", "source": "ParmaToday"},

    # Piacenza
    {"url": "https://www.liberta.it/feed/", "source": "Libertà Piacenza"},
    {"url": "https://www.piacenzasera.it/feed/", "source": "PiacenzaSera"},

    # Ferrara
    {"url": "https://www.ilrestodelcarlino.it/ferrara/rss", "source": "Il Resto del Carlino Ferrara"},
    {"url": "https://www.estense.com/feed/", "source": "Estense.com"},

    # Ravenna
    {"url": "https://www.ilrestodelcarlino.it/ravenna/rss", "source": "Il Resto del Carlino Ravenna"},
    {"url": "https://www.ravennatoday.it/rss", "source": "RavennaToday"},

    # Forlì-Cesena
    {"url": "https://www.ilrestodelcarlino.it/forli/rss", "source": "Il Resto del Carlino Forlì"},
    {"url": "https://www.ilrestodelcarlino.it/cesena/rss", "source": "Il Resto del Carlino Cesena"},
    {"url": "https://www.forlitoday.it/rss", "source": "ForlìToday"},

    # Rimini
    {"url": "https://www.ilrestodelcarlino.it/rimini/rss", "source": "Il Resto del Carlino Rimini"},
    {"url": "https://www.riminitoday.it/rss", "source": "RiminiToday"}
]

# ---------------------------------------------------------------------------
# UTILITIES DI PARSING, DATA E SANITIZZAZIONE
# ---------------------------------------------------------------------------
def clean_xml_text(raw_bytes: bytes) -> str:
    """Rimuove caratteri di controllo ASCII non validi che corrompono il parser XML."""
    text = raw_bytes.decode('utf-8', errors='ignore')
    return re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]', '', text)

def parse_pub_date(date_str: str) -> datetime:
    """Converte le stringhe di data degli RSS in un oggetto datetime offset-aware."""
    if not date_str:
        return None
    try:
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None

def deduplicate_articles(articles: list) -> list:
    """Deduplica le notizie basandosi sui primi termini significativi del titolo."""
    unique_articles = []
    seen_keys = set()

    for art in articles:
        title = art.get('title', '').strip()
        if not title:
            continue
        
        norm_title = re.sub(r'\W+', ' ', title.lower()).strip()
        words = norm_title.split()
        if not words:
            continue
        
        short_key = " ".join(words[:5])
        if short_key not in seen_keys:
            seen_keys.add(short_key)
            unique_articles.append(art)

    return unique_articles

def fetch_rss_articles() -> list:
    """Scarica, filtra per data ed estrae i metadati essenziali dai feed RSS."""
    raw_articles = []
    print(f"[{TODAY_STR}] Avvio scansione di {len(RSS_FEEDS)} feed RSS dell'Emilia-Romagna...")

    for feed_info in RSS_FEEDS:
        feed_url = feed_info["url"]
        source_name = feed_info["source"]
        
        try:
            resp = requests.get(feed_url, headers=HEADERS, timeout=10)
            if resp.status_code != 200:
                continue

            cleaned_xml = clean_xml_text(resp.content)
            root = ET.fromstring(cleaned_xml)

            items = root.findall('.//item') or root.findall('.//{http://www.w3.org/2005/Atom}entry')

            for item in items[:8]:
                title = item.findtext('title') or item.findtext('{http://www.w3.org/2005/Atom}title') or ""
                link = item.findtext('link') or item.findtext('{http://www.w3.org/2005/Atom}href') or ""
                desc = item.findtext('description') or item.findtext('{http://www.w3.org/2005/Atom}summary') or ""
                pub_date_raw = item.findtext('pubDate') or item.findtext('{http://www.w3.org/2005/Atom}updated') or ""

                # Filtro di freschezza (solo notizie recenti)
                dt = parse_pub_date(pub_date_raw)
                if dt and dt < CUTOFF_TIME:
                    continue

                clean_desc = re.sub(r'<[^>]+>', '', desc).strip()

                if title.strip() and link.strip():
                    raw_articles.append({
                        'title': title.strip(),
                        'link': link.strip(),
                        'source': source_name,
                        'description': clean_desc
                    })
        except Exception:
            continue

    unique_raw = deduplicate_articles(raw_articles)
    print(f"Estratti {len(raw_articles)} articoli recenti -> Ridotti a {len(unique_raw)} articoli unici.")

    # Estrazione full-text tramite trafilatura
    full_articles = []
    print("Avvio estrazione Full-Text del contenuto per l'analisi...")
    
    for art in unique_raw[:40]:  # Cap a 40 articoli top per non saturare la finestra
        try:
            downloaded = trafilatura.fetch_url(art['link'])
            text = trafilatura.extract(downloaded, include_comments=False, include_tables=False) if downloaded else None
            
            final_text = text if text and len(text) > 150 else art['description']
            
            full_articles.append({
                'title': art['title'],
                'link': art['link'],
                'source': art['source'],
                'content': final_text[:2500]
            })
        except Exception:
            full_articles.append({
                'title': art['title'],
                'link': art['link'],
                'source': art['source'],
                'content': art['description']
            })

    return full_articles

# ---------------------------------------------------------------------------
# SINTESI ED ELABORAZIONE CON GEMINI API
# ---------------------------------------------------------------------------
def generate_executive_newsletter(articles: list) -> str:
    """Sottopone gli articoli a Gemini imponendo la struttura tassativa per le 9 province."""
    
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERRORE: Variabile d'ambiente GEMINI_API_KEY non impostata.")
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    articles_payload = ""
    for idx, art in enumerate(articles, 1):
        articles_payload += f"\n--- ARTICOLO {idx} ---\n"
        articles_payload += f"TITOLO: {art['title']}\n"
        articles_payload += f"TESTATA: {art['source']}\n"
        articles_payload += f"LINK: {art['link']}\n"
        articles_payload += f"TESTO: {art['content']}\n"

    system_instruction = """
Sei un Senior Editor e Analyst per la Pubblica Amministrazione e il Mondo Imprenditoriale dell'Emilia-Romagna.
Il tuo compito è produrre la RASSEGNA MATTUTINA DELL'EMILIA-ROMAGNA analizzando esclusivamente il materiale fornito.

REGOLE TASSATIVE DI FILTRAGGIO E CONTENUTO:
1. BLOCCO TOTALE DELLO SPORT:
   - È RIGOROSAMENTE VIETATO inserire partite di calcio, risultati, pagelle, calciomercato, gare podistiche o sport minori.
   - UNICA ECCEZIONE: Inchieste giudiarie/penali o vertenze finanziarie di rilievo riguardanti società sportive.
2. NO GOSSIP E NO CRONACA MINIMA:
   - Ometti notizie di colore, gossip o bollettini meteo ordinari (accetta solo allerte ufficiali di Protezione Civile).
3. FOCUS ESCLUSIVO SU CRONACA ED ECONOMIA REALE:
   - CRONACA: Incidenti gravi, delitti, operazioni di FFOO/GdF, processi, allerte idrogeologiche, decisioni comunali/regionali.
   - ECONOMIA: Crisi aziendali, M&A, occupazione, vertenze, liste d'attesa sanitarie, infrastrutture, turismo e agricoltura.
4. COPERTURA RIGIDA DI TUTTE LE 9 PROVINCE:
   - DEVI OBBLIGATORIAMENTE includere le sezioni per tutte le 9 province nel blocco Cronaca.
   - Se per una provincia NON ci sono notizie tra i testi forniti, scrivi esattamente:
     "<p>Nessun fatto straordinario di cronaca segnalato nelle ultime 24 ore.</p>"
5. PRECISIONE DELLE CITAZIONI:
   - Usa sempre la TESTATA fornita e inserisci il link completo nel formato:
     Fonte: <a target="_blank" rel="noopener" href="LINK">TESTATA</a>

FORMATO HTML RICHIESTO (Restituisci SOLO il codice HTML interno, senza tag ```html):

<h2>In evidenza</h2>
<div class="evid">
  <ol>
    <li><strong>Titolo notizia</strong> — descrizione circostanziata con cifre e fatti. Fonte: <a target="_blank" rel="noopener" href="LINK">TESTATA</a></li>
  </ol>
</div>

<h2>Cronaca</h2>
<h3>Bologna (e Imola)</h3>
<p><strong>Titolo</strong> — comune (BO): fatto circostanziato. Fonte: <a target="_blank" rel="noopener" href="LINK">TESTATA</a></p>

<h3>Modena</h3>
<p><strong>Titolo</strong> — comune (MO): fatto circostanziato. Fonte: <a target="_blank" rel="noopener" href="LINK">TESTATA</a></p>

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

    prompt = f"Data di oggi: {TODAY_HUMAN}\n\nElenco articoli estratti da analizzare:\n{articles_payload}"

    print("Invio richiesta a Gemini API (modello: gemini-2.5-flash)...")
    
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.1,  # Bassa temperatura per garantire massima aderenza ai dati ed evitare allucinazioni
            max_output_tokens=8192
        )
    )

    return response.text

# ---------------------------------------------------------------------------
# MAIN EXECUTION
# ---------------------------------------------------------------------------
def main():
    start_time = time.time()
    
    # 1. Parsing ed estrazione articoli
    articles = fetch_rss_articles()
    if not articles:
        print("Nessun articolo estratto dai feed nelle ultime 24 ore. Interruzione script.")
        sys.exit(1)

    # 2. Generazione con Gemini API
    html_output = generate_executive_newsletter(articles)

    # Clean-up eventuale wrapper markdown
    clean_html = re.sub(r'^```html\s*', '', html_output, flags=re.MULTILINE)
    clean_html = re.sub(r'```$', '', clean_html, flags=re.MULTILINE).strip()

    # 3. Salvataggio su file
    out_dir = "edizioni"
    os.makedirs(out_dir, exist_ok=True)
    out_filepath = os.path.join(out_dir, f"{TODAY_STR}.html")

    with open(out_filepath, "w", encoding="utf-8") as f:
        f.write(clean_html)

    elapsed = round(time.time() - start_time, 2)
    print(f"[{TODAY_STR}] Rassegna generata con successo in {out_filepath} in {elapsed}s.")

if __name__ == "__main__":
    main()
