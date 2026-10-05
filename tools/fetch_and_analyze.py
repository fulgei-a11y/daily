import os
import re
import time
import datetime
import requests
import xml.etree.ElementTree as ET
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# 1. CONFIGURAZIONE E LISTA COMPLETA FONTI RSS (Invariate da fetch_and_analyze_3.py)
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
# 2. SCRAPING, DEDUPLICAZIONE E ROUTING INTELLIGENTE
# ---------------------------------------------------------------------------
def fetch_and_categorize_articles():
    seen_titles = set()
    categorized = {
        "PRIMA PAGINA E POLITICA REGIONALE": [],
        "ECONOMIA, LAVORO E IMPRESE": [],
        "PROTEZIONE CIVILE E AMBIENTE": [],
        "CRONACA E TERRITORIO": []
    }
    
    print(f"[{TODAY}] Avvio estrazione notizie da {len(RSS_FEEDS)} fonti RSS...")
    
    # Parole chiave per instradamento dinamico
    kw_politica = ["regione", "giunta", "de pascale", "assemblea", "comune", "sindaco", "pdl", "m5s", "pd", "forza italia", "lega", "fratelli d'italia", "elezioni", "bando", "fondi", "sanità"]
    kw_economia = ["economia", "impresa", "aziende", "lavoro", "sindacato", "export", "fiera", "confindustria", "cna", "investimenti", "mercato", "pmi", "settore"]
    kw_ambiente = ["meteo", "allerta", "fiume", "piena", "protezione civile", "pioggia", "vento", "neve", "frana", "terremoto", "ambiente", "siccità", "arpae"]

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
                
                title_clean = title.strip()
                if not title_clean or title_clean.lower() in seen_titles:
                    continue
                seen_titles.add(title_clean.lower())
                
                clean_desc = re.sub(r'<[^>]+>', '', description).strip()[:300]
                article_data = {'title': title_clean, 'link': link.strip(), 'description': clean_desc}
                text_to_check = (title_clean + " " + clean_desc).lower()
                
                # Assegnazione alla categoria idonea
                if any(k in text_to_check for k in kw_ambiente) or "allertameteo" in feed_url:
                    categorized["PROTEZIONE CIVILE E AMBIENTE"].append(article_data)
                elif any(k in text_to_check for k in kw_politica) or "regione.emilia-romagna" in feed_url:
                    categorized["PRIMA PAGINA E POLITICA REGIONALE"].append(article_data)
                elif any(k in text_to_check for k in kw_economia) or "ilsole24ore" in feed_url:
                    categorized["ECONOMIA, LAVORO E IMPRESE"].append(article_data)
                else:
                    categorized["CRONACA E TERRITORIO"].append(article_data)
        except Exception:
            continue

    for cat, items in categorized.items():
        print(f"  - {cat}: {len(items)} notizie filtrate.")
        
    return categorized

# ---------------------------------------------------------------------------
# 3. GENERAZIONE HTML PER SEZIONE SEPARATA
# ---------------------------------------------------------------------------
def generate_section_html(client, section_title, articles):
    if not articles:
        return f"<h2>{section_title}</h2>\n<p>Nessun aggiornamento di rilievo segnalato nelle ultime ore per questa sezione.</p>"
    
    # Seleziona le 15 notizie più rilevanti per evitare sovraccarichi
    selected_articles = articles[:15]
    raw_text = "\n".join([f"- Titolo: {a['title']}\n  Link: {a['link']}\n  Sintesi: {a['description']}\n" for a in selected_articles])

    system_instruction = f"""
Sei un caporedattore esperto di un quotidiano dell'Emilia-Romagna.
Il tuo compito è scrivere ESCLUSIVAMENTE la sezione: "<h2>{section_title}</h2>" per la rassegna stampa di oggi ({TODAY}).

REGOLE TASSATIVE DI FORMATTAZIONE HTML:
1. Inizia SEMPRE ed ESCLUSIVAMENTE con il tag <h2>{section_title}</h2>.
2. Usa <h3> per raggruppare le notizie per Capoluogo/Provincia (es. <h3>Bologna</h3>, <h3>Modena</h3>) o per Tematiche Principali.
3. Ogni notizia deve essere sintetizzata in un paragrafo <p> autonomo, chiaro e completo di dettagli di cronaca.
4. Alla fine di OGNI paragrafo <p>, inserisci SEMPRE il link alla fonte nel formato esatto: <a href="URL" target="_blank">(Fonte: Nome Testata)</a>.
5. NON usare mai <div> per avvolgere le notizie. NON inserire mai <html>, <head> o <body>.
6. Non troncare MAI le frasi e chiudi sempre tutti i tag HTML apertamente.
"""

    prompt = f"Ecco gli articoli selezionati per la sezione {section_title}:\n\n{raw_text}\n\nGenera il frammento HTML completo:"

    models_to_try = [
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-2.0-flash",
        "gemini-1.5-flash"
    ]

    for model_name in models_to_try:
        for attempt in range(2):
            try:
                print(f"-> Generazione '{section_title}' con {model_name} (tentativo {attempt + 1})...")
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.2,
                        max_output_tokens=8192,  # Massimizzato per evitare truncation
                        safety_settings=[
                            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH),
                            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH),
                            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH)
                        ]
                    )
                )
                if response and response.text:
                    clean_html = re.sub(r'^```html\s*', '', response.text.strip(), flags=re.MULTILINE)
                    clean_html = re.sub(r'```$', '', clean_html.strip(), flags=re.MULTILINE)
                    if len(clean_html) > 50:
                        return clean_html
            except Exception as e:
                print(f"  [!] Avviso: Errore con {model_name}: {e}")
                time.sleep(3)

    return f"<h2>{section_title}</h2>\n<p>Sezione temporaneamente non disponibile.</p>"

def generate_rassegna_body(categorized_articles):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("ERRORE CRITICO: La variabile d'ambiente GEMINI_API_KEY non è impostata.")

    client = genai.Client(api_key=api_key)
    full_body_html = ""

    # Elaborazione sequenziale per le 4 sezioni principali
    sections_order = [
        "PRIMA PAGINA E POLITICA REGIONALE",
        "ECONOMIA, LAVORO E IMPRESE",
        "CRONACA E TERRITORIO",
        "PROTEZIONE CIVILE E AMBIENTE"
    ]

    for section_title in sections_order:
        articles = categorized_articles.get(section_title, [])
        print(f"\nProcessing sezione: {section_title}...")
        sec_html = generate_section_html(client, section_title, articles)
        full_body_html += "\n" + sec_html + "\n"
        time.sleep(1)

    return full_body_html

# ---------------------------------------------------------------------------
# 4. COMPOSIZIONE FINALE E SALVATAGGIO HTML
# ---------------------------------------------------------------------------
def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    categorized = fetch_and_categorize_articles()
    body_content = generate_rassegna_body(categorized)

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
    p {{
        font-size: 15px;
        margin-bottom: 16px;
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
        
    print(f"\n✅ File generato con successo: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
