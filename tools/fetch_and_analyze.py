import os
import re
import time
import datetime
import requests
import xml.etree.ElementTree as ET
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# 1. CONFIGURAZIONE E LISTA FONTI RSS (Identico a 1_4.py)
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
    
    # Resto del Carlino (Copertura capillare province)
    "https://www.ilrestodelcarlino.it/bologna/rss",
    "https://www.ilrestodelcarlino.it/modena/rss",
    "https://www.ilrestodelcarlino.it/reggio-emilia/rss",
    "https://www.ilrestodelcarlino.it/ferrara/rss",
    "https://www.ilrestodelcarlino.it/ravenna/rss",
    "https://www.ilrestodelcarlino.it/forli/rss",
    "https://www.ilrestodelcarlino.it/cesena/rss",
    "https://www.ilrestodelcarlino.it/rimini/rss",
    "https://www.ilrestodelcarlino.it/imola/rss",
    
    # Network "Today" (Province e capoluoghi)
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
# 2. SCRAPING DEI FEED RSS (Identico a 1_4.py)
# ---------------------------------------------------------------------------
def fetch_rss_articles():
    articles = []
    print(f"[{TODAY}] Avvio estrazione notizie da {len(RSS_FEEDS)} fonti RSS...")
    
    for feed_url in RSS_FEEDS:
        try:
            response = requests.get(feed_url, headers=HEADERS, timeout=10)
            if response.status_code != 200:
                continue
            
            root = ET.fromstring(response.content)
            items = root.findall('.//item') or root.findall('.//{http://www.w3.org/2005/Atom}entry')
            
            for item in items[:10]:
                title = item.findtext('title') or item.findtext('{http://www.w3.org/2005/Atom}title') or ""
                link = item.findtext('link') or item.findtext('{http://www.w3.org/2005/Atom}href') or ""
                description = item.findtext('description') or item.findtext('{http://www.w3.org/2005/Atom}summary') or ""
                
                clean_desc = re.sub(r'<[^>]+>', '', description).strip()
                
                if title:
                    articles.append({
                        'title': title.strip(),
                        'link': link.strip(),
                        'description': clean_desc[:400]
                    })
        except Exception:
            continue

    print(f"Estratti con successo {len(articles)} articoli totali.")
    return articles

# ---------------------------------------------------------------------------
# 3. GENERAZIONE SINTESI TEMATICA DETTAGLIATA (9 PROVINCE)
# ---------------------------------------------------------------------------
def generate_sintesi_tematica(articles, client):
    # Analizza fino a 60 notizie per garantire la copertura di tutte le 9 province
    raw_text = "\n".join([f"- Titolo: {a['title']}\n  Sintesi: {a['description']}\n" for a in articles[:60]])

    system_instruction = f"""
Sei il Caporedattore e Analista Politico di un quotidiano regionale dell'Emilia-Romagna.
Analizza in profondità il pacchetto di notizie di oggi ({TODAY}) ed elabora un QUADRO SINTETICO E TEMATICO REGIONALE altamente dettagliato.

STRUTTURA HTML OBBLIGATORIA (Compatibile con il lettore vocale TTS):
- Restituisci ESCLUSIVAMENTE un blocco HTML racchiuso dentro un <div class="sintesi-tematica">...</div>.
- Titolo iniziale: <h2>QUADRO SINTETICO E TEMATICO REGIONALE</h2>
- Genera un elenco <ul> contenente esattamente 8 punti tematici distinti.

SETTORI TEMATICI OBBLIGATORI (Ogni punto <li> deve trattare una delle seguenti aree):
1. Politica Regionale e Riforme Giuntale/Consiliare
2. Economia, Distretti Industriali ed Export
3. Infrastrutture, Trasporti, Mobilità ed Aeroporti
4. Lavoro, Occupazione e Crisi Aziendali
5. Sanità, Welfare e Assistenza Territoriale
6. Protezione Civile, Dissesto Idrogeologico e Meteo
7. Cronaca Giudiziaria e Sicurezza Urbana
8. Territorio, Ambiente, Cultura e Turismo

REGOLE TASSATIVE DI REDAZIONE PER CIASCUN PUNTO (<li>):
- Inizia SEMPRE con il titolo del tema in grassetto senza numeri, es: <strong>Politica Regionale e Riforme:</strong>
- Sviluppa un testo APPROFONDITO di almeno 6-8 righe complete per ciascun punto.
- Cita esplicitamente i fatti, i numeri, le istituzioni coinvolte e le specifiche PROVINCE interessate tra le 9 della Regione (Bologna, Modena, Reggio Emilia, Parma, Piacenza, Ferrara, Ravenna, Forlì-Cesena, Rimini).
- Mantieni uno stile giornalistico autorevole, preciso e informativo.

NON inserire tag <section>, <html>, <head> o marcatori markdown ```html.
"""

    prompt = f"Ecco il corpus delle notizie di oggi:\n\n{raw_text}\n\nGenera la sintesi tematica analitica e dettagliata per le 9 province:"

    models_to_try = [
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-1.5-flash"
    ]

    for model_name in models_to_try:
        try:
            print(f"Generazione sintesi tematica dettagliata con {model_name}...")
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.2
                )
            )
            if response and response.text:
                clean = re.sub(r'^```html\s*', '', response.text.strip(), flags=re.MULTILINE)
                clean = re.sub(r'```$', '', clean.strip(), flags=re.MULTILINE)
                if len(clean) > 200:
                    return clean
        except Exception as e:
            print(f"Avviso Sintesi ({model_name}): {e}")
            time.sleep(2)

    # Fallback garantito in caso di errore di tutte le API
    print("⚠️ Attivazione fallback strutturato per la sintesi tematica...")
    items_html = ""
    for a in articles[:8]:
        items_html += f"<li><strong>Sintesi Cronaca Territoriale:</strong> {a['title']} — {a['description']}</li>\n"
    
    return f"""<div class="sintesi-tematica">
<h2>QUADRO SINTETICO E TEMATICO REGIONALE</h2>
<ul>
{items_html}
</ul>
</div>"""

# ---------------------------------------------------------------------------
# 4. GENERAZIONE HTML CON GEMINI (Struttura di 1_4.py + Sintesi)
# ---------------------------------------------------------------------------
def generate_rassegna_body(articles):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("ERRORE CRITICO: La variabile d'ambiente GEMINI_API_KEY non è impostata.")

    client = genai.Client(api_key=api_key)

    # Generazione preventiva della sintesi tematica
    sintesi_html = generate_sintesi_tematica(articles, client)

    raw_text = "\n".join([f"- Titolo: {a['title']}\n  Link: {a['link']}\n  Sintesi: {a['description']}\n" for a in articles])

    system_instruction = f"""
Sei un caporedattore esperto di cronaca, economia e politica dell'Emilia-Romagna.
Sintetizza le notizie di oggi ({TODAY}) in una Rassegna Stampa HTML.

REGOLE TASSATIVE DI STRUTTURA:
- NON generare <html>, <head> o <body>. Genera SOLO il frammento interno.
- Usa <h2> per i titoli di sezione principale.
- Usa <h3> per le sotto-sezioni/province.
- Ogni singola notizia deve essere racchiusa in un paragrafo <p> o in un punto elenco <li>.
- NON usare <div> per avvolgere le notizie.

REGOLE CONTENUTI E FONTI:
1. Copertura obbligatoria delle 9 province: Bologna, Modena, Reggio Emilia, Parma, Piacenza, Ferrara, Ravenna, Forlì-Cesena, Rimini.
2. Inserisci SEMPRE il link alla fonte alla fine di ogni paragrafo o punto elenco:
   Es: <p>Testo notizia... <a href="URL" target="_blank">(Fonte: Ansa)</a></p>
3. Escludi gossip e sport minore. Includi allerte della Protezione Civile.

SEZIONI OBBLIGATORIE:
- <h2>PRIMA PAGINA E POLITICA REGIONALE</h2>
- <h2>ECONOMIA, LAVORO E IMPRESE</h2>
- <h2>CRONACA E TERRITORIO</h2>
- <h2>PROTEZIONE CIVILE E AMBIENTE</h2>

FORMATO OUTPUT:
Restituisci SOLO ed esclusivamente il codice HTML del corpo senza blocchi markdown (nessun ```html).
"""

    prompt = f"Ecco gli articoli pubblicati oggi:\n\n{raw_text}\n\nGenera la rassegna:"

    # Modelli sicuri e validati (Identico a 1_4.py)[span_2](start_span)[span_2](end_span)
    models_to_try = [
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-2.0-flash",
        "gemini-1.5-flash"
    ]
    
    for model_name in models_to_try:
        for attempt in range(2):
            try:
                print(f"Generazione in corso con il modello {model_name} (tentativo {attempt + 1})...")
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
                    if len(clean_html) > 100:
                        # Unione di Sintesi Tematica e Corpo
                        return sintesi_html + "\n\n" + clean_html
            except Exception as e:
                print(f"Avviso: Errore con {model_name} (tentativo {attempt + 1}): {e}")
                time.sleep(5)

    raise RuntimeError("Impossibile generare la rassegna con tutti i modelli configurati.")

# ---------------------------------------------------------------------------
# 5. SALVATAGGIO FILE HTML (Stili aggiornati per la Sintesi)
# ---------------------------------------------------------------------------
def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    articles = fetch_rss_articles()
    if not articles:
        print("Nessun articolo estratto. Interruzione.")
        return

    body_content = generate_rassegna_body(articles)

    styled_html = f"""<style>
    @import url('https://fonts.googleapis.com/css2?family=Merriweather:ital,wght@0,300;0,400;0,700;1,300&family=Open+Sans:wght@400;600;700&display=swap');
    
    .rassegna-container {{
        font-family: 'Open Sans', -apple-system, BlinkMacSystemFont, sans-serif;
        line-height: 1.7;
        color: #2c3e50;
        max-width: 800px;
        margin: 0 auto;
        padding: 20px;
    }}
    .rassegna-header {{
        border-bottom: 3px solid #004085;
        padding-bottom: 12px;
        margin-bottom: 25px;
    }}
    .rassegna-header h1 {{
        font-family: 'Merriweather', serif;
        font-size: 26px;
        color: #004085;
        margin: 0;
    }}
    .sintesi-tematica {{
        background-color: #f4f7f9;
        border: 1px solid #b8daff;
        border-left: 6px solid #004085;
        border-radius: 6px;
        padding: 20px 24px;
        margin-bottom: 35px;
    }}
    .sintesi-tematica h2 {{
        font-family: 'Merriweather', serif;
        font-size: 18px;
        color: #004085;
        background-color: transparent;
        padding: 0;
        border-left: none;
        margin-top: 0;
        margin-bottom: 16px;
        text-transform: uppercase;
        border-bottom: 2px solid #cce5ff;
        padding-bottom: 8px;
    }}
    .sintesi-tematica ul {{
        margin: 0;
        padding-left: 0;
        list-style-type: none;
    }}
    .sintesi-tematica li {{
        font-size: 14.5px;
        margin-bottom: 18px;
        text-align: justify;
        line-height: 1.65;
        padding-bottom: 12px;
        border-bottom: 1px dashed #d6e4f0;
    }}
    .sintesi-tematica li:last-child {{
        border-bottom: none;
        margin-bottom: 0;
        padding-bottom: 0;
    }}
    .sintesi-tematica strong {{
        color: #0c5460;
        font-size: 15px;
        display: block;
        margin-bottom: 4px;
    }}
    h2 {{
        font-family: 'Merriweather', serif;
        font-size: 18px;
        color: #1b4332;
        background-color: #e8f5e9;
        padding: 10px 14px;
        border-left: 6px solid #2d6a4f;
        margin-top: 35px;
        border-radius: 4px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }}
    h3 {{
        font-size: 16px;
        color: #1d3557;
        border-bottom: 2px solid #e9ecef;
        padding-bottom: 4px;
        margin-top: 25px;
    }}
    p, li {{
        font-size: 15px;
        margin-bottom: 14px;
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
        <h1>Rassegna Stampa Emilia-Romagna</h1>
        <small style="color: #6c757d;">Edizione del {TODAY}</small>
    </div>
    {body_content}
</div>"""

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(styled_html)
        
    print(f"✅ File generato con successo: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
