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
    
    # Testate locali
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
# 2. SCRAPING DEI FEED RSS
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
                        'description': clean_desc[:300]
                    })
        except Exception:
            continue

    print(f"Estratti con successo {len(articles)} articoli totali.")
    return articles

# ---------------------------------------------------------------------------
# 3. GENERAZIONE SINTESI TEMATICA ESTESA
# ---------------------------------------------------------------------------
def generate_sintesi_tematica(articles, client):
    raw_text = "\n".join([f"- Titolo: {a['title']}\n  Sintesi: {a['description']}\n" for a in articles])

    system_instruction = f"""
Sei il Caporedattore e Analista Politico di un quotidiano regionale dell'Emilia-Romagna.
Analizza tutte le notizie del giorno ({TODAY}) ed elabora una Sintesi Esecutiva di livello dirigenziale.

STRUTTURA OBBLIGATORIA (Rispettare scrupolosamente i tag per compatibilità con il lettore vocale):
- Restituisci ESCLUSIVAMENTE un blocco HTML racchiuso dentro un <div class="sintesi-tematica">...</div>.
- Titolo iniziale: <h2>QUADRO SINTETICO E TEMATICO REGIONALE</h2>
- Genera un elenco <ul> contenente esattamente tra i 6 e gli 8 punti tematici distinti.
- Ogni punto <li> deve rappresentare un'area di interesse strategico (es. Politica & Riforme, Economia & Imprese, Infrastrutture & Aeroporti, Lavoro & Crisi Industriali, Sanità & Sociale, Ordine Pubblico & Sicurezza, Territorio & Ambiente).

REGOLE DI REDAZIONE PER I PUNTI (<li>):
1. Inizia ogni punto con un titolo in grassetto senza numeri, es. <strong>Politica e Riforme Regionali:</strong>
2. Sviluppa per OGNI punto un paragrafo approfondito e analitico di 5-7 righe.
3. Cita dove pertinente le province coinvolte tra le 9 della regione (Bologna, Modena, Reggio Emilia, Parma, Piacenza, Ferrara, Ravenna, Forlì-Cesena, Rimini), specificando fatti, dati e impatto sul territorio.
4. Mantieni un tono formale e autorevole.

NON inserire tag <section>, <html>, <head> o marcatori markdown ```html.
"""

    prompt = f"Ecco le notizie del giorno:\n\n{raw_text}\n\nGenera la sintesi tematica approfondita per le 9 province:"

    try:
        print("Generazione della sintesi tematica professionale in corso...")
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.2,
                max_output_tokens=4096
            )
        )
        if response and response.text:
            clean = re.sub(r'^```html\s*', '', response.text.strip(), flags=re.MULTILINE)
            clean = re.sub(r'```$', '', clean.strip(), flags=re.MULTILINE)
            return clean
    except Exception as e:
        print(f"Errore durante la generazione della sintesi: {e}")
    return ""

# ---------------------------------------------------------------------------
# 4. GENERAZIONE CORPO RASSEGNA
# ---------------------------------------------------------------------------
def generate_rassegna_body(articles):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("ERRORE CRITICO: La variabile d'ambiente GEMINI_API_KEY non è impostata.")

    client = genai.Client(api_key=api_key)

    sintesi_html = generate_sintesi_tematica(articles, client)

    raw_text = "\n".join([f"- Titolo: {a['title']}\n  Link: {a['link']}\n  Sintesi: {a['description']}\n" for a in articles])

    system_instruction = f"""
Sei un caporedattore esperto di cronaca, economia e politica dell'Emilia-Romagna.
Sintetizza le notizie di oggi ({TODAY}) in una Rassegna Stampa HTML.

REGOLE TASSATIVE DI STRUTTURA PER COMPATIBILITÀ PARSER AUDIO:
- NON generare <html>, <head>, <body> o <section>.
- Usa SOLO <h2> per i titoli di sezione principale.
- Usa SOLO <h3> per le sotto-sezioni o province.
- Ogni singola notizia deve essere racchiusa esclusivamente in un elemento <p> o <li>.
- NON avvolgere le notizie in tag <div> generici o personalizzati.

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
Restituisci SOLO ed esclusivamente il codice HTML del corpo senza blocchi markdown.
"""

    prompt = f"Ecco gli articoli pubblicati oggi:\n\n{raw_text}\n\nGenera la rassegna:"

    models_to_try = [
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-2.5-pro"
    ]
    
    for model_name in models_to_try:
        for attempt in range(2):
            try:
                print(f"Generazione del corpo rassegna con {model_name} (tentativo {attempt + 1})...")
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
                        return sintesi_html + "\n\n" + clean_html
            except Exception as e:
                print(f"Avviso: Errore con {model_name} (tentativo {attempt + 1}): {e}")
                time.sleep(3)

    raise RuntimeError("Impossibile generare la rassegna con i modelli configurati.")

# ---------------------------------------------------------------------------
# 5. MAIN
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
        line-height: 1.7;
        color: #2c3e50;
        max-width: 820px;
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
    print(f"✅ File HTML generato con successo per la rassegna e l'audio TTS: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
