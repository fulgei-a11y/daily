#!/usr/bin/env python3
"""
tools/fetch_and_analyze.py
--------------------------
Rassegna Stampa & Strategic Analysis dell'Emilia-Romagna.
Combina 25+ fonti locali e regionali con estrazione Full-Text,
intelligence strategica (Gemini API) e layout HTML/CSS avanzato.
"""

import os
import re
import sys
import time
import datetime
import requests
import xml.etree.ElementTree as ET
import trafilatura
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# 1. CONFIGURAZIONE E LISTA FONTI RSS (TUTTE LE TUE FONTI + FALLBACK)
# ---------------------------------------------------------------------------
TODAY = datetime.date.today().strftime('%Y-%m-%d')
OUTPUT_DIR = "edizioni"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, f"{TODAY}.html")

# LISTA COMPLETA DELLE TUE FONTI
RSS_FEEDS = [
    # Regione & Protezione Civile
    "https://www.regione.emilia-romagna.it/notizie/RSS",
    "https://allertameteo.regione.emilia-romagna.it/notizie-rss",
    
    # ANSA Regionali
    "https://www.ansa.it/emiliaromagna/notizie/emiliaromagna_rss.xml",
    
    # Resto del Carlino (Capillare sulle province)
    "https://www.ilrestodelcarlino.it/bologna/rss",
    "https://www.ilrestodelcarlino.it/modena/rss",
    "https://www.ilrestodelcarlino.it/reggio-emilia/rss",
    "https://www.ilrestodelcarlino.it/ferrara/rss",
    "https://www.ilrestodelcarlino.it/ravenna/rss",
    "https://www.ilrestodelcarlino.it/forli/rss",
    "https://www.ilrestodelcarlino.it/cesena/rss",
    "https://www.ilrestodelcarlino.it/rimini/rss",
    "https://www.ilrestodelcarlino.it/imola/rss",
    
    # Network "Today" (Citynews)
    "https://www.bolognatoday.it/rss",
    "https://www.modenatoday.it/rss",
    "https://www.riminitoday.it/rss",
    "https://www.ravennatoday.it/rss",
    "https://www.parmatoday.it/rss",
    "https://www.piacenzatoday.it/rss",
    "https://www.forlitoday.it/rss",
    
    # Testate locali e Gazzette
    "https://www.gazzettadiparma.it/rss/",
    "https://www.piacenzasera.it/feed/",
    "https://www.corriereromagna.it/feed/",
    "https://www.estense.com/feed/",
    
    # Economia & Imprese
    "https://www.ilsole24ore.com/rss/italia--emilia-romagna.xml",

    # Google News Backup (per evitare vuoti se i server bloccassero alcuni IP)
    "https://news.google.com/rss/search?q=Emilia+Romagna+cronaca+economia&hl=it&gl=IT&ceid=IT:it"
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
}

# ---------------------------------------------------------------------------
# 2. SCRAPING DEI FEED RSS & FULL-TEXT EXTRACTION ROBUSTA
# ---------------------------------------------------------------------------
def clean_xml_text(raw_bytes: bytes) -> str:
    text = raw_bytes.decode('utf-8', errors='ignore')
    return re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]', '', text)

def fetch_rss_articles():
    raw_articles = []
    seen_titles = set()
    print(f"[{TODAY}] Avvio estrazione feed RSS da {len(RSS_FEEDS)} fonti...")
    
    for feed_url in RSS_FEEDS:
        try:
            # Timeout ridotto a 5 secondi per non bloccare mai la pipeline
            response = requests.get(feed_url, headers=HEADERS, timeout=5)
            if response.status_code != 200:
                continue
            
            cleaned_xml = clean_xml_text(response.content)
            root = ET.fromstring(cleaned_xml)
            items = root.findall('.//item') or root.findall('.//{http://www.w3.org/2005/Atom}entry')
            
            for item in items[:5]:
                title = item.findtext('title') or item.findtext('{http://www.w3.org/2005/Atom}title') or ""
                link = item.findtext('link') or item.findtext('{http://www.w3.org/2005/Atom}href') or ""
                description = item.findtext('description') or item.findtext('{http://www.w3.org/2005/Atom}summary') or ""
                
                clean_title = re.sub(r'<[^>]+>', '', title).strip()
                clean_desc = re.sub(r'<[^>]+>', '', description).strip()
                
                # Anti-duplicati basato sul titolo
                t_key = clean_title.lower()[:30]
                if clean_title and link and t_key not in seen_titles:
                    seen_titles.add(t_key)
                    raw_articles.append({
                        'title': clean_title,
                        'link': link.strip(),
                        'description': clean_desc
                    })
        except Exception:
            continue

    print(f"Estratti {len(raw_articles)} articoli unici. Avvio Full-Text Extraction...")
    
    full_articles = []
    # Analizziamo fino ai 45 articoli più rilevanti
    for idx, art in enumerate(raw_articles[:45]):
        try:
            downloaded = trafilatura.fetch_url(art['link'])
            text = trafilatura.extract(downloaded, include_comments=False, include_tables=False) if downloaded else None
            
            final_content = text if text and len(text) > 200 else art['description']
            
            full_articles.append({
                'title': art['title'],
                'link': art['link'],
                'content': final_content[:2500]
            })
            print(f" [{idx+1}/{min(45, len(raw_articles))}] Estratto: {art['title'][:40]}...")
        except Exception:
            full_articles.append({
                'title': art['title'],
                'link': art['link'],
                'content': art['description']
            })

    return full_articles

# ---------------------------------------------------------------------------
# 3. GENERAZIONE REPORT CON GEMINI API
# ---------------------------------------------------------------------------
def generate_rassegna_body(articles):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("ERRORE CRITICO: GEMINI_API_KEY non è impostata nell'ambiente.")

    client = genai.Client(api_key=api_key)

    raw_text = "\n\n".join([f"=== ARTICOLO ===\nTitolo: {a['title']}\nLink: {a['link']}\nTesto:\n{a['content']}" for a in articles])

    system_instruction = f"""
Sei il Caporedattore e Chief Analyst di un'agenzia d'intelligence e analisi strategica per dirigenti e istituzioni dell'Emilia-Romagna.
Produci un REPORT DI SCENARIO ED ANALISI STRATEGICA sulla giornata di oggi ({TODAY}).

CRITERI RIGIDI DI FILTRAGGIO:
- ESCLUDI TASSATIVAMENTE la micro-cronaca nera e gli incidenti minori (nessun furto, rissa o incidente isolato).
- CONCENTRATI SU TEMI DI SISTEMA: Politica regionale e locale, infrastrutture, nodi sanitari, industria, distretti, turismo, transizione ecologica e allerte meteo.

STRUTTURA DELL'OUTPUT HTML (Restituisci SOLO il codice HTML del corpo, senza ```html):

1. BOX EXECUTIVE SUMMARY & METRICHE STRATEGICHE:
   - <div class="executive-box">
     * <div class="trend-bar">Sintesi del clima della giornata con emoticon</div>
     * <h3>I 3 Fatti Chiave di Oggi</h3> con elenco puntato e implicazioni.
     * <div class="key-figures-grid"> con 3-4 <div class="figure-card"><span class="number">Cifra</span><span class="label">Descrizione</span></div></div>
     * <div class="swot-box">⚠️ <strong>Rischio di Sistema:</strong> ... | 💡 <strong>Opportunità:</strong> ...</div>
     * <div class="quote-box">Frase del Giorno (se presente nei testi)</div>
   </div>

2. INDICE DI NAVIGAZIONE RAPIDA (TOC):
   - <div class="toc-box">
     <a href="#sec1">🏛️ Politica & Infrastrutture</a>
     <a href="#sec2">📈 Economia & Turismo</a>
     <a href="#sec3">🏥 Sanità & Sociale</a>
     <a href="#sec4">🌿 Ambiente & Risorse</a>
     <a href="#sec5">🗓️ Agenda & Prossimi Passaggi</a>
     </div>

3. SEZIONI DI ANALISI APPROFONDITA:
   - BADGE TERRITORIALI OBLIGATORI: Inserisci <span class="city-tag">BOLOGNA</span>, <span class="city-tag">MODENA</span>, <span class="city-tag">PARMA</span>, ecc. all'inizio dei paragrafi.
   - Usa paragrafi ampi e discorsivi nelle sezioni 1-4.
   - Inserisci SEMPRE il link alla fonte: <a href="URL" target="_blank">(Fonte: Nome)</a>.

SEZIONI OBBLIGATORIE:
- <h2 id="sec1">1. POLITICA REGIONALE, GOVERNABILITÀ ED INFRASTRUTTURE</h2>
- <h2 id="sec2">2. ECONOMIA, DISTRETTI INDUSTRIALI E BRAND TURISMO</h2>
- <h2 id="sec3">3. SANITÀ, SCUOLA E POLITICHE SOCIALI SUL TERRITORIO</h2>
- <h2 id="sec4">4. PROTEZIONE CIVILE, AMBIENTE E PIANIFICAZIONE TERRITORIALE</h2>
- <h2 id="sec5">5. AGENDA & PROSSIMI PASSAGGI ISTITUZIONALI</h2>
  * Elenco puntato di appuntamenti, scioperi, scadenze, tavoli tecnici.
"""

    prompt = f"Ecco gli articoli estratti oggi in Emilia-Romagna:\n\n{raw_text}\n\nGenera il Report Strategico:"

    models_to_try = [
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-2.0-flash",
        "gemini-1.5-flash"
    ]
    
    for model_name in models_to_try:
        try:
            print(f"Invocazione Gemini con modello {model_name}...")
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.2,
                    max_output_tokens=8192
                )
            )
            if response and response.text:
                clean_html = re.sub(r'^```[a-z]*\s*', '', response.text.strip(), flags=re.MULTILINE)
                clean_html = re.sub(r'```$', '', clean_html.strip(), flags=re.MULTILINE)
                if len(clean_html) > 300:
                    return clean_html
        except Exception as e:
            print(f"Avviso: Errore con {model_name}: {e}")
            time.sleep(3)

    raise RuntimeError("Impossibile generare la rassegna con i modelli configurati.")

# ---------------------------------------------------------------------------
# 4. SALVATAGGIO FILE HTML E CSS AVANZATO
# ---------------------------------------------------------------------------
def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    articles = fetch_rss_articles()
    if not articles:
        print("Nessun articolo estratto. Interruzione.")
        sys.exit(1)

    body_content = generate_rassegna_body(articles)

    styled_html = f"""<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Rassegna Stampa Emilia-Romagna - {TODAY}</title>
    <style>
        @import url('[https://fonts.googleapis.com/css2?family=Merriweather:ital,wght@0,300;0,400;0,700;1,300&family=Open+Sans:wght@400;600;700&display=swap](https://fonts.googleapis.com/css2?family=Merriweather:ital,wght@0,300;0,400;0,700;1,300&family=Open+Sans:wght@400;600;700&display=swap)');
        
        body {{
            background-color: #f4f6f9;
            margin: 0;
            padding: 20px;
        }}
        .rassegna-container {{
            font-family: 'Open Sans', -apple-system, BlinkMacSystemFont, sans-serif;
            line-height: 1.8;
            color: #2c3e50;
            max-width: 900px;
            margin: 0 auto;
            padding: 30px;
            background: #ffffff;
            border-radius: 8px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.05);
        }}
        .rassegna-header {{
            border-bottom: 4px solid #004085;
            padding-bottom: 15px;
            margin-bottom: 25px;
        }}
        .rassegna-header h1 {{
            font-family: 'Merriweather', serif;
            font-size: 28px;
            color: #004085;
            margin: 0 0 5px 0;
        }}
        
        /* Box Executive Summary & Cifre */
        .executive-box {{
            background-color: #f8f9fa;
            border: 1px solid #e9ecef;
            border-left: 6px solid #004085;
            padding: 20px;
            border-radius: 6px;
            margin-bottom: 25px;
        }}
        .trend-bar {{
            font-size: 14px;
            font-weight: 600;
            background: #e9ecef;
            padding: 8px 12px;
            border-radius: 4px;
            margin-bottom: 15px;
        }}
        .executive-box h3 {{
            margin-top: 0;
            color: #004085;
            font-family: 'Merriweather', serif;
            font-size: 18px;
        }}
        .key-figures-grid {{
            display: flex;
            gap: 12px;
            flex-wrap: wrap;
            margin: 15px 0;
        }}
        .figure-card {{
            background: #ffffff;
            border: 1px solid #ced4da;
            border-radius: 6px;
            padding: 10px 14px;
            flex: 1;
            min-width: 130px;
            text-align: center;
            box-shadow: 0 2px 4px rgba(0,0,0,0.04);
        }}
        .figure-card .number {{
            font-size: 19px;
            font-weight: 700;
            color: #2d6a4f;
            display: block;
        }}
        .figure-card .label {{
            font-size: 11px;
            color: #6c757d;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .swot-box {{
            background: #ffffff;
            border: 1px dashed #adb5bd;
            padding: 12px 15px;
            font-size: 13.5px;
            border-radius: 4px;
            margin-top: 15px;
        }}
        .quote-box {{
            font-style: italic;
            background: #e8f4f8;
            border-left: 4px solid #17a2b8;
            padding: 10px 15px;
            margin-top: 15px;
            font-size: 14px;
            color: #114b5f;
        }}

        /* Indice TOC */
        .toc-box {{
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            background: #ffffff;
            padding: 12px;
            border: 1px solid #dee2e6;
            border-radius: 6px;
            margin-bottom: 30px;
        }}
        .toc-box a {{
            font-size: 12px;
            background: #f1f3f5;
            color: #495057;
            padding: 6px 10px;
            border-radius: 4px;
            text-decoration: none;
            font-weight: 600;
        }}
        .toc-box a:hover {{
            background: #004085;
            color: #ffffff;
        }}

        /* Badge Territoriali */
        .city-tag {{
            display: inline-block;
            background-color: #004085;
            color: #ffffff;
            font-size: 10px;
            font-weight: 700;
            padding: 2px 7px;
            border-radius: 3px;
            margin-right: 6px;
            vertical-align: middle;
        }}

        h2 {{
            font-family: 'Merriweather', serif;
            font-size: 20px;
            color: #1b4332;
            background-color: #f0f7f4;
            padding: 12px 16px;
            border-left: 6px solid #2d6a4f;
            margin-top: 40px;
            margin-bottom: 20px;
            border-radius: 4px;
        }}
        p {{
            font-size: 15px;
            margin-bottom: 18px;
            text-align: justify;
        }}
        ul {{
            margin-bottom: 20px;
            padding-left: 20px;
        }}
        li {{
            margin-bottom: 8px;
            font-size: 14.5px;
        }}
        a {{
            color: #0056b3;
            text-decoration: none;
            font-weight: 600;
        }}
        a:hover {{
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    <div class="rassegna-container">
        <div class="rassegna-header">
            <h1>Rassegna Stampa & Strategic Analysis</h1>
            <small style="color: #6c757d; font-size: 14px;">Emilia-Romagna • Edizione del {TODAY}</small>
        </div>
        {body_content}
    </div>
</body>
</html>"""

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(styled_html)
        
    print(f"✅ File generato con successo: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
