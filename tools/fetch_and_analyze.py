import os
import re
import datetime
import requests
import xml.etree.ElementTree as ET
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# 1. CONFIGURAZIONE E LISTA FONTI RSS (Copertura 9 Province + Economia + Regione)
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
# 2. RAGGRUPPAMENTO E SCRAPING DEI FEED RSS
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
# 3. PROMPT DI SISTEMA ED ELABORAZIONE IA (Gemini 2.5 Flash / Fallback)
# ---------------------------------------------------------------------------
def generate_rassegna_html(articles):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("ERRORE CRITICO: La variabile d'ambiente GEMINI_API_KEY non è impostata.")

    client = genai.Client(api_key=api_key)

    raw_text = "\n".join([f"- Titolo: {a['title']}\n  Link: {a['link']}\n  Sintesi: {a['description']}\n" for a in articles])

    system_instruction = f"""
Sei un caporedattore edigooglitore esperto di cronaca, economia e politica dell'Emilia-Romagna.
Analizza la lista di notizie estratte oggi ({TODAY}) e sintetizzale in una Rassegna Stampa quotidiana completa in formato HTML.

REGOLE TASSATIVE DI STRUTTURA HTML (FONDAMENTALE PER IL LETTORE VOCALE):
- Usa ESCLUSIVAMENTE tag <h2> per i titoli di sezione, <h3> per i capoluoghi/province, e singoli paragrafi <p> o liste <ul><li> per OGNI notizia.
- NON avvolgere le notizie dentro tag <div> generici. Ogni singola notizia deve stare dentro un proprio tag <p> o <li>.

REGOLE DI COPERTURA E FONTI:
1. COPERTURA TERRITORIALE OBBLIGATORIA: Devi coprire tutte e 9 le province: Bologna, Modena, Reggio Emilia, Parma, Piacenza, Ferrara, Ravenna, Forlì-Cesena, Rimini.
2. LINK ALLA FONTE PER OGNI NOTIZIA: Alla fine di ogni paragrafo <p> o <li>, inserisci SEMPRE il link cliccabile originale:
   Es: <p>Testo notizia... <a href="URL" target="_blank">(Fonte: Ansa)</a></p>
3. FILTRO CONTENUTI: Scarta gossip e sport minore. Includi le allerte meteo ufficiali della Protezione Civile. Unifica le notizie duplicate citando le diverse fonti.

SEZIONI OBBLIGATORIE:
- <h2>PRIMA PAGINA E POLITICA REGIONALE</h2>
- <h2>ECONOMIA, LAVORO E IMPRESE</h2>
- <h2>CRONACA E TERRITORIO</h2> (usa <h3> per le varie province)
- <h2>PROTEZIONE CIVILE E AMBIENTE</h2>

FORMATO OUTPUT:
Restituisci SOLO ed esclusivamente il frammento HTML (senza tag <html> o <body> e senza blocchi markdown ```html).
"""

    prompt = f"Ecco gli articoli pubblicati oggi in Emilia-Romagna:\n\n{raw_text}\n\nGenera la rassegna stampa HTML:"

    models_to_try = ["gemini-2.5-flash", "gemini-1.5-pro"]
    
    for model_name in models_to_try:
        try:
            print(f"Generazione in corso con il modello {model_name}...")
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.3
                )
            )
            if response.text:
                clean_html = re.sub(r'^```html\s*', '', response.text.strip(), flags=re.MULTILINE)
                clean_html = re.sub(r'```$', '', clean_html.strip(), flags=re.MULTILINE)
                return clean_html
        except Exception as e:
            print(f"Avviso: Errore con il modello {model_name}: {e}. Tentativo successivo...")

    raise RuntimeError("Impossibile generare la rassegna con tutti i modelli configurati.")

# ---------------------------------------------------------------------------
# 4. SALVATAGGIO FILE HTML
# ---------------------------------------------------------------------------
def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    articles = fetch_rss_articles()
    if not articles:
        print("Nessun articolo estratto. Interruzione.")
        return

    html_content = generate_rassegna_html(articles)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    print(f"✅ Rassegna generata con successo e salvata in: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
