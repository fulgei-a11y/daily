import os
import re
import time
import datetime
import requests
import xml.etree.ElementTree as ET
import trafilatura
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# 1. CONFIGURAZIONE E LISTA FONTI RSS
# ---------------------------------------------------------------------------
TODAY = datetime.date.today().strftime('%Y-%m-%d')
OUTPUT_DIR = "edizioni"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, f"{TODAY}.html")

RSS_FEEDS = [
    # Regione & Protezione Civile
    "https://www.regione.emilia-romagna.it/notizie/RSS",
    "https://allertameteo.regione.emilia-romagna.it/notizie-rss",
    
    # ANSA Regionali
    "https://www.ansa.it/emiliaromagna/notizie/emiliaromagna_rss.xml",
    
    # Resto del Carlino
    "https://www.ilrestodelcarlino.it/bologna/rss",
    "https://www.ilrestodelcarlino.it/modena/rss",
    "https://www.ilrestodelcarlino.it/reggio-emilia/rss",
    "https://www.ilrestodelcarlino.it/ferrara/rss",
    "https://www.ilrestodelcarlino.it/ravenna/rss",
    "https://www.ilrestodelcarlino.it/forli/rss",
    "https://www.ilrestodelcarlino.it/cesena/rss",
    "https://www.ilrestodelcarlino.it/rimini/rss",
    "https://www.ilrestodelcarlino.it/imola/rss",
    
    # Network "Today"
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
    "https://www.ilsole24ore.com/rss/italia--emilia-romagna.xml"
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# ---------------------------------------------------------------------------
# 2. SCRAPING DEI FEED RSS & FULL-TEXT EXTRACTION
# ---------------------------------------------------------------------------
def fetch_rss_articles():
    raw_articles = []
    print(f"[{TODAY}] Avvio estrazione feed RSS da {len(RSS_FEEDS)} fonti...")
    
    for feed_url in RSS_FEEDS:
        try:
            response = requests.get(feed_url, headers=HEADERS, timeout=10)
            if response.status_code != 200:
                continue
            
            root = ET.fromstring(response.content)
            items = root.findall('.//item') or root.findall('.//{http://www.w3.org/2005/Atom}entry')
            
            for item in items[:6]:  # Prendiamo i primi 6 da ciascun feed per garantire qualità
                title = item.findtext('title') or item.findtext('{http://www.w3.org/2005/Atom}title') or ""
                link = item.findtext('link') or item.findtext('{http://www.w3.org/2005/Atom}href') or ""
                description = item.findtext('description') or item.findtext('{http://www.w3.org/2005/Atom}summary') or ""
                
                clean_desc = re.sub(r'<[^>]+>', '', description).strip()
                
                if title and link:
                    raw_articles.append({
                        'title': title.strip(),
                        'link': link.strip(),
                        'description': clean_desc
                    })
        except Exception:
            continue

    print(f"Estratti {len(raw_articles)} link. Avvio download testo integrale (Full-Text Extraction)...")
    
    # Full-Text Extraction con Trafilatura
    full_articles = []
    for idx, art in enumerate(raw_articles[:40]):  # Analizziamo fino a 40 articoli top
        try:
            downloaded = trafilatura.fetch_url(art['link'])
            text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
            
            # Fallback se trafilatura non estrae il testo integrale
            final_content = text if text and len(text) > 200 else art['description']
            
            full_articles.append({
                'title': art['title'],
                'link': art['link'],
                'content': final_content[:2500]  # Fino a 2500 caratteri per articolo
            })
            print(f"[{idx+1}/{min(40, len(raw_articles))}] Estratto: {art['title'][:40]}...")
        except Exception:
            full_articles.append({
                'title': art['title'],
                'link': art['link'],
                'content': art['description']
            })

    return full_articles

# ---------------------------------------------------------------------------
# 3. GENERAZIONE HTML CON EXECUTIVE SUMMARY & ANALISI APPROFONDITA
# ---------------------------------------------------------------------------
def generate_rassegna_body(articles):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("ERRORE CRITICO: La variabile d'ambiente GEMINI_API_KEY non è impostata.")

    client = genai.Client(api_key=api_key)

    raw_text = "\n\n".join([f"=== ARTICOLO ===\nTitolo: {a['title']}\nLink: {a['link']}\nTesto Completo:\n{a['content']}" for a in articles])

    system_instruction = f"""
Sei il Caporedattore e Chief Analyst di una newsletter d'informazione strategica ed economica per dirigenti e istituzioni dell'Emilia-Romagna.
Il tuo compito è produrre un REPORT DI SCENARIO ED ANALISI STRATEGICA sulla giornata di oggi ({TODAY}).

CRITERI RIGIDI DI FILTRAGGIO (SELEZIONE CRITICA):
- ESCLUDI TASSATIVAMENTE la micro-cronaca e la cronaca nera minore: NESSUN incidente stradale isolato, NESSUN furto in abitazione, NESSUNA rissa da bar.
- CONCENTRATI ESCLUSIVAMENTE SU TEMI DI RILEVANZA DI SISTEMA: Politica regionale e locale, infrastrutture, nodi sanitari, industria e distretti, turismo, scuola/integrazione, transizione ecologica e allerte meteo.

STRUTTURA DELL'OUTPUT HTML:
Devi generare SOLO il frammento interno HTML (senza <html>, <head> o <body>), così formattato:

1. BOX EXECUTIVE SUMMARY & KEY FIGURES (In testa al report):
   - Inserisci un div con classe 'executive-box':
     * Titolo <h3>I 3 Fatti Chiave di Oggi</h3> con un elenco di 3 punti focali e le relative implicazioni.
     * Un contenitore div con classe 'key-figures-grid' contenente 3-4 badge ('figure-card') con le cifre/statistiche più importanti estratte dai testi (es. "+4% Turismo", "4.5M€ per Condotte", "25kg Sequestro").

2. SEZIONI DI ANALISI APPROFONDITA (Testo fluido e giornalistico):
   - Usa <h2> per le macro-sezioni tematiche.
   - Usa <h3> per i focus territoriali/tematici.
   - NON USARE ELENCHI PUNTATI BANALI NEL CORPO DELLE SEZIONI. Scrivi paragrafi ampi, articolati (300-500 parole per macro-sezione) che colleghino le fonti e contestualizzino le posizioni dei vari attori.
   - Inserisci SEMPRE il link alla fonte citata: ... <a href="URL" target="_blank">(Fonte: Nome)</a>.

SEZIONI OBBLIGATORIE:
- <h2>1. POLITICA REGIONALE, GOVERNABILITÀ ED INFRASTRUTTURE</h2>
- <h2>2. ECONOMIA, DISTRETTI INDUSTRIALI E BRAND TURISMO</h2>
- <h2>3. SANITÀ, SCUOLA E POLITICHE SOCIALI SUL TERRITORIO</h2>
- <h2>4. PROTEZIONE CIVILE, AMBIENTE E PIANIFICAZIONE</h2>

FORMATO OUTPUT:
Restituisci SOLO ed esclusivamente il codice HTML del corpo senza blocchi markdown (nessun ```html).
"""

    prompt = f"Ecco gli articoli integrali estratti oggi in Emilia-Romagna:\n\n{raw_text}\n\nGenera il Report con Executive Summary e Cifre Chiave:"

    models_to_try = [
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-2.0-flash",
        "gemini-1.5-flash"
    ]
    
    for model_name in models_to_try:
        for attempt in range(2):
            try:
                print(f"Generazione analisi avanzata con {model_name} (tentativo {attempt + 1})...")
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.3
                    )
                )
                if response and response.text:
                    clean_html = re.sub(r'^```html\s*', '', response.text.strip(), flags=re.MULTILINE)
                    clean_html = re.sub(r'```$', '', clean_html.strip(), flags=re.MULTILINE)
                    if len(clean_html) > 300:
                        return clean_html
            except Exception as e:
                print(f"Avviso: Errore con {model_name} (tentativo {attempt + 1}): {e}")
                time.sleep(5)

    raise RuntimeError("Impossibile generare la rassegna con tutti i modelli configurati.")

# ---------------------------------------------------------------------------
# 4. SALVATAGGIO FILE HTML E CSS PREMIUM
# ---------------------------------------------------------------------------
def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    articles = fetch_rss_articles()
    if not articles:
        print("Nessun articolo estratto. Interruzione.")
        return

    body_content = generate_rassegna_body(articles)

    styled_html = f"""<style>
    @import url('[https://fonts.googleapis.com/css2?family=Merriweather:ital,wght@0,300;0,400;0,700;1,300&family=Open+Sans:wght@400;600;700&display=swap](https://fonts.googleapis.com/css2?family=Merriweather:ital,wght@0,300;0,400;0,700;1,300&family=Open+Sans:wght@400;600;700&display=swap)');
    
    .rassegna-container {{
        font-family: 'Open Sans', -apple-system, BlinkMacSystemFont, sans-serif;
        line-height: 1.8;
        color: #2c3e50;
        max-width: 850px;
        margin: 0 auto;
        padding: 25px;
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
        margin-bottom: 35px;
    }}
    .executive-box h3 {{
        margin-top: 0;
        color: #004085;
        font-family: 'Merriweather', serif;
        font-size: 18px;
        border-bottom: none;
    }}
    .key-figures-grid {{
        display: flex;
        gap: 15px;
        flex-wrap: wrap;
        margin-top: 15px;
    }}
    .figure-card {{
        background: #ffffff;
        border: 1px solid #ced4da;
        border-radius: 6px;
        padding: 10px 15px;
        flex: 1;
        min-width: 140px;
        text-align: center;
        box-shadow: 0 2px 4px rgba(0,0,0,0.04);
    }}
    .figure-card .number {{
        font-size: 20px;
        font-weight: 700;
        color: #2d6a4f;
        display: block;
    }}
    .figure-card .label {{
        font-size: 12px;
        color: #6c757d;
        text-transform: uppercase;
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
        letter-spacing: 0.5px;
    }}
    h3 {{
        font-family: 'Merriweather', serif;
        font-size: 17px;
        color: #1d3557;
        border-bottom: 2px solid #e9ecef;
        padding-bottom: 6px;
        margin-top: 30px;
        margin-bottom: 15px;
    }}
    p {{
        font-size: 15px;
        margin-bottom: 18px;
        text-align: justify;
    }}
    a {{
        color: #0056b3;
        text-decoration: none;
        font-weight: 600;
    }}
    a:hover {{
        text-decoration: underline;
    }}
    @media print {{
        .rassegna-container {{
            max-width: 100%;
            padding: 0;
        }}
        h2 {{
            background-color: #f1f1f1 !important;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
        }}
    }}
</style>

<div class="rassegna-container">
    <div class="rassegna-header">
        <h1>Rassegna Stampa & Strategic Analysis</h1>
        <small style="color: #6c757d; font-size: 14px;">Emilia-Romagna • Edizione del {TODAY}</small>
    </div>
    {body_content}
</div>"""

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(styled_html)
        
    print(f"✅ File generato con successo: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
