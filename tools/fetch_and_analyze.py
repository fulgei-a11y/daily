#!/usr/bin/env python3
"""
tools/fetch_and_analyze.py
--------------------------
Rassegna Stampa Mattutina dell'Emilia-Romagna.
Scandaglia 35+ fonti locali, regionali ed economiche con estrazione Full-Text
e genera il frammento HTML (edizioni/AAAA-MM-GG.html) strutturato per l'App di Lettura.
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
# 1. CONFIGURAZIONE DATE E PERCORSI
# ---------------------------------------------------------------------------
TODAY_STR = datetime.date.today().strftime('%Y-%m-%d')
OUTPUT_DIR = "edizioni"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, f"{TODAY_STR}.html")

# ---------------------------------------------------------------------------
# 2. ELENCO FONTI RSS (REGIONALE, PROVINCIALE, ECONOMIA E FALLBACK)
# ---------------------------------------------------------------------------
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

    # Google News Backup (Fallback mirato su province ed economia)
    "https://news.google.com/rss/search?q=site:liberta.it+Piacenza&hl=it&gl=IT&ceid=IT:it",
    "https://news.google.com/rss/search?q=site:gazzettadimodena.it&hl=it&gl=IT&ceid=IT:it",
    "https://news.google.com/rss/search?q=site:gazzettadireggio.it&hl=it&gl=IT&ceid=IT:it",
    "https://news.google.com/rss/search?q=site:lanuovaferrara.it&hl=it&gl=IT&ceid=IT:it",
    "https://news.google.com/rss/search?q=site:corrieredibologna.corriere.it&hl=it&gl=IT&ceid=IT:it",
    "https://news.google.com/rss/search?q=site:bologna.repubblica.it&hl=it&gl=IT&ceid=IT:it",
    "https://news.google.com/rss/search?q=Emilia+Romagna+Hera+BPER+Unipol+Ferrari+IMA+Datalogic+Credem+Interpump&hl=it&gl=IT&ceid=IT:it",
    "https://news.google.com/rss/search?q=Confindustria+Unioncamere+CGIL+CISL+UIL+Emilia+Romagna&hl=it&gl=IT&ceid=IT:it"
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
}

# ---------------------------------------------------------------------------
# 3. SCRAPING DEI FEED RSS & ESTRAZIONE FULL-TEXT
# ---------------------------------------------------------------------------
def clean_xml_text(raw_bytes: bytes) -> str:
    text = raw_bytes.decode('utf-8', errors='ignore')
    return re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]', '', text)

def fetch_rss_articles():
    raw_articles = []
    seen_titles = set()
    print(f"[{TODAY_STR}] Avvio estrazione feed RSS da {len(RSS_FEEDS)} fonti...")
    
    for feed_url in RSS_FEEDS:
        try:
            response = requests.get(feed_url, headers=HEADERS, timeout=6)
            if response.status_code != 200:
                continue
            
            cleaned_xml = clean_xml_text(response.content)
            root = ET.fromstring(cleaned_xml)
            items = root.findall('.//item') or root.findall('.//{http://www.w3.org/2005/Atom}entry')
            
            for item in items[:4]:
                title = item.findtext('title') or item.findtext('{http://www.w3.org/2005/Atom}title') or ""
                link = item.findtext('link') or item.findtext('{http://www.w3.org/2005/Atom}href') or ""
                description = item.findtext('description') or item.findtext('{http://www.w3.org/2005/Atom}summary') or ""
                
                clean_title = re.sub(r'<[^>]+>', '', title).strip()
                clean_desc = re.sub(r'<[^>]+>', '', description).strip()
                
                t_key = clean_title.lower()[:35]
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
    for idx, art in enumerate(raw_articles[:60]):
        try:
            downloaded = trafilatura.fetch_url(art['link'])
            text = trafilatura.extract(downloaded, include_comments=False, include_tables=False) if downloaded else None
            
            final_content = text if text and len(text) > 200 else art['description']
            
            full_articles.append({
                'title': art['title'],
                'link': art['link'],
                'content': final_content[:3000]
            })
            print(f" [{idx+1}/{min(60, len(raw_articles))}] Estratto: {art['title'][:40]}...")
        except Exception:
            full_articles.append({
                'title': art['title'],
                'link': art['link'],
                'content': art['description']
            })

    return full_articles

# ---------------------------------------------------------------------------
# 4. GENERAZIONE DEL FRAMMENTO HTML CON GEMINI API
# ---------------------------------------------------------------------------
def generate_html_fragment(articles):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("ERRORE CRITICO: La variabile d'ambiente GEMINI_API_KEY non è impostata.")

    client = genai.Client(api_key=api_key)

    raw_text = "\n\n".join([f"=== ARTICOLO ===\nTitolo: {a['title']}\nLink: {a['link']}\nTesto:\n{a['content']}" for a in articles])

    system_instruction = f"""
Sei il Caporedattore della RASSEGNA MATTUTINA DELL'EMILIA-ROMAGNA.
Produci un frammento HTML puro senza tag <html>, <head> o <body> per la giornata di oggi ({TODAY_STR}).

REGOLE ESSENZIALI:
- Non abbreviare o tagliare dettagli.
- Notizie circostanziate: chi, cosa, dove (comune e provincia), quando, cifre, nomi di persone/aziende, stato dei fatti.
- NESSUNA EMOJI NEI TITOLI H2 / H3.
- Ogni notizia deve terminare con il link alla fonte: <a target="_blank" rel="noopener" href="URL">Nome Testata</a>.
- COPRI TUTTE LE 9 PROVINCE: Bologna (e Imola), Modena, Reggio Emilia, Parma, Piacenza, Ferrara, Ravenna, Forlì-Cesena, Rimini. Se per una provincia non emergono notizie rilevanti, inserisci: <p class="note">Nessuna notizia rilevante segnalata nelle ultime 24 ore.</p>.

STRUTTURA HTML RIGIDA RICHIESTA (Restituisci SOLO questo codice):

<h2>In evidenza</h2>
<div class="evid">
  <ol>
    <li><strong>Titolo sintetico</strong> — descrizione circostanziata di 2-3 righe con fatti e cifre. Fonte: <a target="_blank" rel="noopener" href="URL">Testata</a></li>
  </ol>
</div>

<h2>Cronaca</h2>
<h3>Bologna (e Imola)</h3>
<p><strong>Titolo sintetico</strong> — comune (BO): descrizione dettagliata di 3-6 righe... Fonte: <a target="_blank" rel="noopener" href="URL">Testata</a></p>

<h3>Modena</h3>
<p><strong>Titolo sintetico</strong> — comune (MO): descrizione dettagliata di 3-6 righe... Fonte: <a target="_blank" rel="noopener" href="URL">Testata</a></p>

<h3>Reggio Emilia</h3>
<p><strong>Titolo sintetico</strong> — comune (RE): descrizione dettagliata di 3-6 righe... Fonte: <a target="_blank" rel="noopener" href="URL">Testata</a></p>

<h3>Parma</h3>
<p><strong>Titolo sintetico</strong> — comune (PR): descrizione dettagliata di 3-6 righe... Fonte: <a target="_blank" rel="noopener" href="URL">Testata</a></p>

<h3>Piacenza</h3>
<p><strong>Titolo sintetico</strong> — comune (PC): descrizione dettagliata di 3-6 righe... Fonte: <a target="_blank" rel="noopener" href="URL">Testata</a></p>

<h3>Ferrara</h3>
<p><strong>Titolo sintetico</strong> — comune (FE): descrizione dettagliata di 3-6 righe... Fonte: <a target="_blank" rel="noopener" href="URL">Testata</a></p>

<h3>Ravenna</h3>
<p><strong>Titolo sintetico</strong> — comune (RA): descrizione dettagliata di 3-6 righe... Fonte: <a target="_blank" rel="noopener" href="URL">Testata</a></p>

<h3>Forlì-Cesena</h3>
<p><strong>Titolo sintetico</strong> — comune (FC): descrizione dettagliata di 3-6 righe... Fonte: <a target="_blank" rel="noopener" href="URL">Testata</a></p>

<h3>Rimini</h3>
<p><strong>Titolo sintetico</strong> — comune (RN): descrizione dettagliata di 3-6 righe... Fonte: <a target="_blank" rel="noopener" href="URL">Testata</a></p>

<h2>Economia e lavoro</h2>
<h3>Imprese e vertenze</h3>
<p><strong>Titolo sintetico</strong> — testo dettagliato... Fonte: <a target="_blank" rel="noopener" href="URL">Testata</a></p>

<h3>Dati e congiuntura</h3>
<p><strong>Titolo sintetico</strong> — testo dettagliato... Fonte: <a target="_blank" rel="noopener" href="URL">Testata</a></p>

<h3>Regione e istituzioni</h3>
<p><strong>Titolo sintetico</strong> — testo dettagliato... Fonte: <a target="_blank" rel="noopener" href="URL">Testata</a></p>

<h3>Infrastrutture, agricoltura, turismo</h3>
<p><strong>Titolo sintetico</strong> — testo dettagliato... Fonte: <a target="_blank" rel="noopener" href="URL">Testata</a></p>

<h2>Politica e amministrazione</h2>
<p><strong>Titolo sintetico</strong> — fatti di amministrazione locale/regionale... Fonte: <a target="_blank" rel="noopener" href="URL">Testata</a></p>

<h2>Da seguire oggi</h2>
<ul>
  <li>Scadenze, consigli, udienze ed eventi di oggi...</li>
</ul>

<div class="foot">
  <p><strong>Nota sulle fonti.</strong> Indicazione sintetica dello stato delle fonti consultate.</p>
</div>
"""

    prompt = f"Ecco gli articoli estratti oggi in Emilia-Romagna:\n\n{raw_text}\n\nGenera il frammento HTML esatto:"

    models_to_try = [
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-2.0-flash"
    ]
    
    for model_name in models_to_try:
        try:
            print(f"Invocazione Gemini con modello {model_name}...")
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.15,
                    max_output_tokens=8192
                )
            )
            if response and response.text:
                clean_html = re.sub(r'^```[a-z]*\s*', '', response.text.strip(), flags=re.MULTILINE)
                clean_html = re.sub(r'```$', '', clean_html.strip(), flags=re.MULTILINE)
                if len(clean_html) > 400:
                    return clean_html
        except Exception as e:
            print(f"Avviso: Errore con {model_name}: {e}")
            time.sleep(2)

    raise RuntimeError("Impossibile generare la rassegna con i modelli configurati.")

# ---------------------------------------------------------------------------
# 5. SALVATAGGIO DEL FRAMMENTO HTML
# ---------------------------------------------------------------------------
def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    articles = fetch_rss_articles()
    if not articles:
        print("Nessun articolo estratto. Interruzione.")
        sys.exit(1)

    fragment_html = generate_html_fragment(articles)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(fragment_html)
        
    print(f"✅ Frammento HTML salvato con successo in: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
