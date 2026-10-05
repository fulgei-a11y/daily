#!/usr/bin/env python3
"""
tools/fetch_and_analyze.py
--------------------------
Rassegna Stampa Capillare dell'Emilia-Romagna.
Scandaglia 35+ feed RSS e query territoriali per coprire 9/9 province,
estrae il full-text con Trafilatura e genera il report e il frammento HTML
per l'applicazione tramite Gemini API (google-genai).
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
NOW = datetime.datetime.now()
TODAY_STR = NOW.strftime('%Y-%m-%d')
OUTPUT_DIR = "edizioni"
HTML_FRAGMENT_FILE = os.path.join(OUTPUT_DIR, f"{TODAY_STR}.html")

# ---------------------------------------------------------------------------
# 2. MAPPA FONTI RSS COMPLETA (35+ FEED DIVISI PER AMBITO E PROVINCIA)
# ---------------------------------------------------------------------------
RSS_SOURCES = {
    # REGIONALE, ISTITUZIONI E AGENZIE
    "Istituzioni": [
        "https://www.regione.emilia-romagna.it/notizie/RSS",
        "https://allertameteo.regione.emilia-romagna.it/notizie-rss",
        "https://www.ansa.it/emiliaromagna/notizie/emiliaromagna_rss.xml",
    ],
    
    # IL RESTO DEL CARLINO (CAPILLARE SULLE PROVINCE)
    "Resto del Carlino": [
        "https://www.ilrestodelcarlino.it/bologna/rss",
        "https://www.ilrestodelcarlino.it/modena/rss",
        "https://www.ilrestodelcarlino.it/reggio-emilia/rss",
        "https://www.ilrestodelcarlino.it/ferrara/rss",
        "https://www.ilrestodelcarlino.it/ravenna/rss",
        "https://www.ilrestodelcarlino.it/forli/rss",
        "https://www.ilrestodelcarlino.it/cesena/rss",
        "https://www.ilrestodelcarlino.it/rimini/rss",
        "https://www.ilrestodelcarlino.it/imola/rss",
    ],

    # NETWORK TODAY / CITYNEWS
    "Today Network": [
        "https://www.bolognatoday.it/rss",
        "https://www.modenatoday.it/rss",
        "https://www.riminitoday.it/rss",
        "https://www.ravennatoday.it/rss",
        "https://www.parmatoday.it/rss",
        "https://www.piacenzatoday.it/rss",
        "https://www.forlitoday.it/rss",
    ],

    # TESTATE EDELIZIE E GAZZETTE LOCALI
    "Gazzette e Locali": [
        "https://www.gazzettadiparma.it/rss/",
        "https://www.piacenzasera.it/feed/",
        "https://www.corriereromagna.it/feed/",
        "https://www.estense.com/feed/",
    ],

    # ECONOMIA, BORSA, SINDACATI E IMPRESE
    "Economia": [
        "https://www.ilsole24ore.com/rss/italia--emilia-romagna.xml",
    ],

    # PARACUTE DINAMICO GOOGLE NEWS: QUERY PROVINCIALI E TEMATICHE DEDICATE
    # Garantisce dati su Piacenza, Parma, Reggio, Modena, Bologna, Ferrara, Ravenna, Forlì-Cesena, Rimini e Borsa ER
    "Google News Provincial Fallback": [
        "https://news.google.com/rss/search?q=site:liberta.it+Piacenza&hl=it&gl=IT&ceid=IT:it",
        "https://news.google.com/rss/search?q=site:gazzettadimodena.it&hl=it&gl=IT&ceid=IT:it",
        "https://news.google.com/rss/search?q=site:gazzettadireggio.it&hl=it&gl=IT&ceid=IT:it",
        "https://news.google.com/rss/search?q=site:lanuovaferrara.it&hl=it&gl=IT&ceid=IT:it",
        "https://news.google.com/rss/search?q=site:corrieredibologna.corriere.it&hl=it&gl=IT&ceid=IT:it",
        "https://news.google.com/rss/search?q=site:bologna.repubblica.it&hl=it&gl=IT&ceid=IT:it",
        "https://news.google.com/rss/search?q=Emilia+Romagna+Hera+BPER+Unipol+Ferrari+IMA+Datalogic+Credem+Interpump&hl=it&gl=IT&ceid=IT:it",
        "https://news.google.com/rss/search?q=Confindustria+Unioncamere+CGIL+CISL+UIL+Emilia+Romagna&hl=it&gl=IT&ceid=IT:it"
    ]
}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
}

# ---------------------------------------------------------------------------
# 3. SCRAPING RSS & ESTRAZIONE FULL-TEXT CON TRAFILATURA
# ---------------------------------------------------------------------------
def clean_xml_text(raw_bytes: bytes) -> str:
    text = raw_bytes.decode('utf-8', errors='ignore')
    return re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]', '', text)

def fetch_all_articles():
    raw_articles = []
    seen_titles = set()
    
    total_feeds = sum(len(feeds) for feeds in RSS_SOURCES.values())
    print(f"[{TODAY_STR}] Avvio scansione di {total_feeds} feed e query provinciali...")
    
    for category, feed_urls in RSS_SOURCES.items():
        for url in feed_urls:
            try:
                response = requests.get(url, headers=HEADERS, timeout=6)
                if response.status_code != 200:
                    continue
                
                cleaned_xml = clean_xml_text(response.content)
                root = ET.fromstring(cleaned_xml)
                items = root.findall('.//item') or root.findall('.//{http://www.w3.org/2005/Atom}entry')
                
                for item in items[:4]:  # Primi 4 per feed
                    title = item.findtext('title') or item.findtext('{http://www.w3.org/2005/Atom}title') or ""
                    link = item.findtext('link') or item.findtext('{http://www.w3.org/2005/Atom}href') or ""
                    description = item.findtext('description') or item.findtext('{http://www.w3.org/2005/Atom}summary') or ""
                    
                    clean_title = re.sub(r'<[^>]+>', '', title).strip()
                    clean_desc = re.sub(r'<[^>]+>', '', description).strip()
                    
                    t_key = clean_title.lower()[:35]
                    if clean_title and link and t_key not in seen_titles:
                        seen_titles.add(t_key)
                        raw_articles.append({
                            'category': category,
                            'title': clean_title,
                            'link': link.strip(),
                            'description': clean_desc
                        })
            except Exception:
                continue

    print(f"Trovati {len(raw_articles)} articoli unici. Avvio estrazione Full-Text...")
    
    full_articles = []
    # Analizza fino a 60 articoli per massima copertura di tutte le province
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
            print(f" [{idx+1}/{min(60, len(raw_articles))}] Estratto: {art['title'][:45]}...")
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
        raise ValueError("ERRORE: GEMINI_API_KEY non presente nell'ambiente.")

    client = genai.Client(api_key=api_key)

    raw_text = "\n\n".join([f"=== ARTICOLO ===\nTitolo: {a['title']}\nLink: {a['link']}\nTesto:\n{a['content']}" for a in articles])

    system_instruction = f"""
Sei il Caporedattore esperto della RASSEGNA MATTUTINA DELL'EMILIA-ROMAGNA.
Produci un frammento HTML puro rigoroso e dettagliato per la giornata del {TODAY_STR}.

REGOLE ESSENZIALI:
- Non abbreviare o saltare i fatti per fretta.
- Dettagli necessari per ogni notizia: chi, cosa, dove (comune e provincia), quando, cifre, nomi, stato delle indagini o provvedimenti.
- NESSUNA EMOJI NEI TITOLI HTML.
- Inserisci link su ogni notizia: <a target="_blank" rel="noopener" href="URL">Nome Testata</a>.
- COPRI OBBLIGATORIAMENTE TUTTE LE 9 PROVINCE: Bologna (e Imola), Modena, Reggio Emilia, Parma, Piacenza, Ferrara, Ravenna, Forlì-Cesena, Rimini. Se per una provincia non ci sono fatti rilevanti, inserisci un paragrafo esplicativo <p class="note">Nessun fatto di cronaca rilevante segnalato nelle ultime 24 ore.</p>.

ESTRUTTURA HTML RIGIDA (Restituisci SOLO questo codice, senza wrapper ```html):

<h2>In evidenza</h2>
<div class="evid">
  <ol>
    <li><strong>Titolo sintetico</strong> — descrizione di 2-3 righe con fatti, cifre e fonte. Fonte: <a target="_blank" rel="noopener" href="URL">Testata</a></li>
    <!-- 3-5 notizie principali -->
  </ol>
</div>

<h2>Cronaca</h2>
<h3>Bologna (e Imola)</h3>
<p><strong>Titolo sintetico</strong> — comune (BO): testo di 3-6 righe circostanziato... Fonte: <a target="_blank" rel="noopener" href="URL">Testata</a></p>

<h3>Modena</h3>
<p><strong>Titolo sintetico</strong> — comune (MO): testo di 3-6 righe... Fonte: <a target="_blank" rel="noopener" href="URL">Testata</a></p>

<h3>Reggio Emilia</h3>
<p><strong>Titolo sintetico</strong> — comune (RE): testo di 3-6 righe... Fonte: <a target="_blank" rel="noopener" href="URL">Testata</a></p>

<h3>Parma</h3>
<p><strong>Titolo sintetico</strong> — comune (PR): testo di 3-6 righe... Fonte: <a target="_blank" rel="noopener" href="URL">Testata</a></p>

<h3>Piacenza</h3>
<p><strong>Titolo sintetico</strong> — comune (PC): testo di 3-6 righe... Fonte: <a target="_blank" rel="noopener" href="URL">Testata</a></p>

<h3>Ferrara</h3>
<p><strong>Titolo sintetico</strong> — comune (FE): testo di 3-6 righe... Fonte: <a target="_blank" rel="noopener" href="URL">Testata</a></p>

<h3>Ravenna</h3>
<p><strong>Titolo sintetico</strong> — comune (RA): testo di 3-6 righe... Fonte: <a target="_blank" rel="noopener" href="URL">Testata</a></p>

<h3>Forlì-Cesena</h3>
<p><strong>Titolo sintetico</strong> — comune (FC): testo di 3-6 righe... Fonte: <a target="_blank" rel="noopener" href="URL">Testata</a></p>

<h3>Rimini</h3>
<p><strong>Titolo sintetico</strong> — comune (RN): testo di 3-6 righe... Fonte: <a target="_blank" rel="noopener" href="URL">Testata</a></p>

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
<p><strong>Titolo sintetico</strong> — fatti regionali o comunali... Fonte: <a target="_blank" rel="noopener" href="URL">Testata</a></p>

<h2>Da seguire oggi</h2>
<ul>
  <li>Scadenza, appuntamento o evento di oggi...</li>
</ul>

<div class="foot">
  <p><strong>Nota sulle fonti.</strong> Elenco delle fonti consultate con esito favorevole o eventuali avvisi su fonti irraggiungibili.</p>
</div>
"""

    prompt = f"Ecco gli articoli estratti nelle ultime 24 ore in Emilia-Romagna:\n\n{raw_text}\n\nGenera il frammento HTML completo:"

    models = ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"]
    
    for model_name in models:
        try:
            print(f"Generazione HTML con modello {model_name}...")
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
                if len(clean_html) > 500:
                    return clean_html
        except Exception as e:
            print(f"Errore su {model_name}: {e}")
            time.sleep(2)

    raise RuntimeError("Impossibile generare l'HTML tramite i modelli Gemini.")

# ---------------------------------------------------------------------------
# 5. ESECUZIONE
# ---------------------------------------------------------------------------
def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    articles = fetch_all_articles()
    if not articles:
        print("Nessun articolo estratto dalle fonti.")
        sys.exit(1)

    html_content = generate_html_fragment(articles)

    with open(HTML_FRAGMENT_FILE, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"✅ Frammento HTML salvato con successo in: {HTML_FRAGMENT_FILE}")

if __name__ == "__main__":
    main()
