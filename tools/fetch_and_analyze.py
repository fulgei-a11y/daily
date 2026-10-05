import os
import re
import time
import datetime
import requests
import xml.etree.ElementTree as ET
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
# 2. SCRAPING ESTESO DEI FEED RSS
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
            
            for item in items[:15]:
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
# 3. GENERAZIONE PER SEZIONI SEPARATE (Mai più troncamenti)
# ---------------------------------------------------------------------------
def generate_section(client, section_title, articles_text):
    system_instruction = f"""
Sei un caporedattore esperto di cronaca, economia e politica dell'Emilia-Romagna.
Devi redigere ESCLUSIVAMENTE la sezione: "{section_title}" per la rassegna stampa di oggi ({TODAY}).

REGOLE TASSATIVE:
- Restituisci SOLO il codice HTML relativo a questa sezione (inizia direttamente con <h2>{section_title}</h2>).
- Usa <h3> per suddividere per provincia o sotto-temi rilevanti.
- Ogni notizia deve essere in un paragrafo <p> dettagliato e completo.
- Inserisci SEMPRE il link alla fonte alla fine di ogni paragrafo nel formato esatto: <a href="URL" target="_blank">(Fonte: Nome)</a>.
- NON generare <html> o <body>. Solo il blocco della sezione.
- Assicurati di completare la sezione senza troncare le frasi.
"""

    prompt = f"Ecco gli articoli disponibili:\n\n{articles_text}\n\nScrivi la sezione '{section_title}' in modo approfondito:"

    models_to_try = ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash", "gemini-1.5-flash"]

    for model_name in models_to_try:
        for attempt in range(2):
            try:
                print(f"Generazione sezione '{section_title}' con {model_name}...")
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.3,
                        max_output_tokens=4096
                    )
                )
                if response and response.text:
                    clean_html = re.sub(r'^```html\s*', '', response.text.strip(), flags=re.MULTILINE)
                    clean_html = re.sub(r'```$', '', clean_html.strip(), flags=re.MULTILINE)
                    if len(clean_html) > 50:
                        return clean_html
            except Exception as e:
                print(f"Errore tentato con {model_name}: {e}")
                time.sleep(3)
                
    return f"<h2>{section_title}</h2><p>Errore di generazione per questa sezione.</p>"

def generate_rassegna_body(articles):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("ERRORE CRITICO: La variabile d'ambiente GEMINI_API_KEY non è impostata.")

    client = genai.Client(api_key=api_key)
    raw_text = "\n".join([f"- Titolo: {a['title']}\n  Link: {a['link']}\n  Sintesi: {a['description']}\n" for a in articles])

    sections = [
        "PRIMA PAGINA E POLITICA REGIONALE",
        "ECONOMIA, LAVORO E IMPRESE",
        "CRONACA E TERRITORIO",
        "PROTEZIONE CIVILE E AMBIENTE"
    ]

    full_body_html = ""
    for sec in sections:
        print(f"\nElaborazione sezione: {sec}...")
        section_html = generate_section(client, sec, raw_text)
        full_body_html += "\n" + section_html + "\n"
        time.sleep(1) # Pausa breve tra una chiamata e l'altra

    return full_body_html

# ---------------------------------------------------------------------------
# 4. SALVATAGGIO FILE HTML
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
        
    print(f"\n✅ File generato con successo: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
