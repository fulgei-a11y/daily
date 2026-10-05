import os
import re
import html
import time
import requests
import feedparser
from datetime import datetime
import google.generativeai as genai

# ==========================================
# 1. CONFIGURAZIONE API E FONTI RSS
# ==========================================

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY non trovata nelle variabili d'ambiente.")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")

RSS_FEEDS = [
    # Fonti Generali e Agenzie
    "https://www.ansa.it/emiliaromagna/notizie/emiliaromagna_rss.xml",
    "https://www.ilrestodelcarlino.it/rss",
    "https://www.corrieredibo.it/feed/",
    
    # Fonti Territoriali e Locali
    "https://www.bolognatoday.it/rss",
    "https://www.estense.com/feed/",
    "https://www.ilPiacenza.it/rss",
    "https://www.parmatoday.it/rss",
    "https://www.reggiotoday.it/rss",
    "https://www.modenatoday.it/rss",
    "https://www.ravennatoday.it/rss",
    "https://www.riminitoday.it/rss",
    "https://www.forlitoday.it/rss",
    "https://www.cesenatoday.it/rss"
]

PROVINCE = [
    "Bologna", "Ferrara", "Forlì-Cesena", "Modena", 
    "Parma", "Piacenza", "Ravenna", "Reggio Emilia", "Rimini"
]

# ==========================================
# 2. BLACKLIST E SCORING
# ==========================================

BLACKLIST_KEYWORDS = [
    "calcio", "serie a", "serie b", "serie c", "promozione", "eccellenza",
    "basket", "pallavolo", "tennis", "formula 1", "motogp", "partita",
    "ballando con le stelle", "grande fratello", "sanremo", "oroscopo",
    "gossip", "spettacolo", "concerti", "disco", "movida"
]

KW_PA = ["regione", "giunta", "assemblea legislativa", "comune", "sindaco", "ausl", "bando", "delibera", "pnrr", "appalto", "finanziamento", "sanità"]
KW_ECONOMIA = ["azienda", "crisi", "sindacato", "lavoro", "licenziamento", "investimenti", "export", "fiera", "confindustria", "infrastrutture", "porto"]
KW_CRONACA = ["arresto", "omicidio", "incidente", "carabinieri", "polizia", "sequestro", "indagine", "procura", "incendio", "protezione civile", "alluvione"]

def clean_html_text(text):
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)
    return ' '.join(text.split())

def calculate_relevance_score(title, desc):
    full_text = f"{title} {desc}".lower()
    if any(kw in full_text for kw in BLACKLIST_KEYWORDS):
        return -100
        
    score = 0
    for kw in KW_PA:
        if kw in full_text: score += 4
    for kw in KW_ECONOMIA:
        if kw in full_text: score += 3
    for kw in KW_CRONACA:
        if kw in full_text: score += 3
    for prov in PROVINCE:
        if prov.lower() in full_text: score += 2

    return score

def detect_province(title, desc):
    full_text = f"{title} {desc}".lower()
    detected = [prov for prov in PROVINCE if prov.lower() in full_text]
    return detected if detected else ["Regionale"]

# ==========================================
# 3. PIPELINE RACCOLTA
# ==========================================

def fetch_and_process_news():
    raw_articles = []
    seen_fingerprints = set()

    print("--> 1. Raccolta articoli da RSS...")
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            source_name = feed.feed.get("title", "Fonte Locale")
            
            for entry in feed.entries[:35]:
                title = clean_html_text(entry.get("title", ""))
                summary = clean_html_text(entry.get("summary", entry.get("description", "")))
                link = entry.get("link", "")
                
                if not title or len(title) < 10:
                    continue
                
                title_words = re.sub(r'[^\w\s]', '', title.lower()).split()
                fingerprint = " ".join(title_words[:6])
                
                if fingerprint in seen_fingerprints:
                    continue
                seen_fingerprints.add(fingerprint)

                score = calculate_relevance_score(title, summary)
                if score < 0:
                    continue

                provinces = detect_province(title, summary)
                raw_articles.append({
                    "title": title,
                    "desc": summary[:800],
                    "link": link,
                    "source": source_name,
                    "score": score,
                    "provinces": provinces
                })
        except Exception as e:
            print(f"Errore feed {feed_url}: {e}")

    print(f"--> Raccolti {len(raw_articles)} articoli validi.")
    raw_articles.sort(key=lambda x: x["score"], reverse=True)
    return raw_articles

# ==========================================
# 4. GENERAZIONE SEZIONI PER PROVINCIA (SINTASSI STRICT PER BUILD_AUDIO)
# ==========================================

def generate_section_html(section_title, articles_list, prompt_instruction):
    if not articles_list:
        return f"<h2>{section_title}</h2><p>Nessun aggiornamento di rilievo nelle ultime ore.</p>"

    formatted_articles = ""
    for idx, a in enumerate(articles_list, 1):
        formatted_articles += f"""
---
ARTICOLO {idx}:
Titolo: {a['title']}
Fonte: {a['source']}
Territorio/Provincia: {', '.join(a['provinces'])}
Testo: {a['desc']}
Link: {a['link']}
"""

    prompt = f"""
Sei un caporedattore esperto della Regione Emilia-Romagna.

Compito: Genera il frammento HTML per la sezione "<h2>{section_title}</h2>".

REGOLE RIGIDISSIME DI SINTASSI HTML (FONDAMENTALI PER IL PARSER AUDIO):
1. Inizia SEMPRE la sezione con il tag `<h2>{section_title}</h2>`.
2. DIVIDI OBBLIGATORIAMENTE I CONTENUTI PER PROVINCIA usando ESCLUSIVAMENTE il tag `<h3>` (es: `<h3>Focus Provincia di Bologna</h3>`, `<h3>Focus Provincia di Modena</h3>`, `<h3>Notizie Regionali</h3>`).
3. OGNI SINGOLA NOTIZIA DEVE ESSERE CONTENUTA IN UN TAG `<p>`. Non usare mai <h4> o <div> per le notizie.
4. Formatta ciascuna notizia dentro il tag `<p>` esattamente in questo modo:
   `<p><strong>Titolo della Notizia.</strong> Testo del riassunto chiaro ed esaustivo in 2-3 frasi. <a href="LINK" target="_blank">Leggi su FONTE</a></p>`
5. {prompt_instruction}
6. Restituisci SOLO codice HTML grezzo senza contenitori markdown (no ```html).

ARTICOLI A DISPOSIZIONE:
{formatted_articles}
"""
    for attempt in range(3):
        try:
            response = model.generate_content(prompt)
            text = response.text.strip()
            text = re.sub(r'^```html\s*', '', text)
            text = re.sub(r'\s*```$', '', text)
            time.sleep(2)
            return text
        except Exception as e:
            print(f"Tentativo {attempt+1} fallito per {section_title}: {e}")
            time.sleep(4)

    # Fallback rigoroso conforme al parser audio
    fallback = f"<h2>{section_title}</h2>"
    by_prov = {}
    for a in articles_list:
        prov = a['provinces'][0]
        by_prov.setdefault(prov, []).append(a)
        
    for prov, arts in by_prov.items():
        fallback += f"<h3>Focus Provincia di {prov}</h3>"
        for a in arts[:4]:
            fallback += f"<p><strong>{a['title']}.</strong> {a['desc']} <a href='{a['link']}' target='_blank'>Leggi su {a['source']}</a></p>"
    return fallback

# ==========================================
# 5. ASSEMBLAGGIO FINALE DEL DOCUMENTO
# ==========================================

def build_full_rassegna():
    articles = fetch_and_process_news()
    
    top_pa = [a for a in articles if any(k in f"{a['title']} {a['desc']}".lower() for k in KW_PA) or a["score"] >= 6][:20]
    top_economy = [a for a in articles if any(k in f"{a['title']} {a['desc']}".lower() for k in KW_ECONOMIA)][:18]
    top_cronaca = [a for a in articles if any(k in f"{a['title']} {a['desc']}".lower() for k in KW_CRONACA)][:18]

    print("--> 2. Generazione Pubblica Amministrazione & Territorio...")
    html_pa = generate_section_html("Prima Pagina e Pubblica Amministrazione", top_pa, "Raggruppa le notizie per Provincia con tag <h3> e inserisci ciascuna notizia dentro un tag <p>.")

    print("--> 3. Generazione Economia e Lavoro...")
    html_eco = generate_section_html("Economia, Lavoro e Imprese", top_economy, "Raggruppa le notizie per Provincia con tag <h3> e inserisci ciascuna notizia dentro un tag <p>.")

    print("--> 4. Generazione Cronaca e Sicurezza...")
    html_cro = generate_section_html("Cronaca e Sicurezza", top_cronaca, "Raggruppa le notizie per Provincia con tag <h3> e inserisci ciascuna notizia dentro un tag <p>.")

    today_str = datetime.now().strftime("%d/%m/%Y")
    
    full_html = f"""<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Rassegna Stampa Emilia-Romagna - {today_str}</title>
    <style>
        body {{ font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; line-height: 1.6; color: #222; max-width: 900px; margin: 0 auto; padding: 20px; background: #f4f6f8; }}
        .container {{ background: #fff; padding: 30px; border-radius: 8px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); }}
        header {{ border-bottom: 3px solid #d9534f; padding-bottom: 15px; margin-bottom: 30px; }}
        h1 {{ color: #111; margin: 0 0 5px 0; font-size: 28px; }}
        h2 {{ color: #d9534f; border-bottom: 1px solid #eee; padding-bottom: 8px; font-size: 22px; margin-top: 35px; }}
        h3 {{ color: #0275d8; margin-top: 25px; font-size: 18px; background: #eef5fa; padding: 6px 12px; border-left: 4px solid #0275d8; }}
        p {{ margin-top: 10px; margin-bottom: 15px; font-size: 15px; }}
        strong {{ color: #111; }}
        a {{ color: #0275d8; text-decoration: none; font-size: 13px; }}
        a:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Rassegna Stampa Emilia-Romagna</h1>
            <div><strong>Edizione del {today_str} — PA, Economia e Cronaca per Provincia</strong></div>
        </header>

        <main>
            {html_pa}
            {html_eco}
            {html_cro}
        </main>
    </div>
</body>
</html>
"""
    
    os.makedirs("edizioni", exist_ok=True)
    today_filename = datetime.now().strftime("%Y-%m-%d.html")
    output_path = os.path.join("edizioni", today_filename)
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(full_html)
        
    print(f"--> Rassegna completata e salvata con successo in '{output_path}'.")

if __name__ == "__main__":
    build_full_rassegna()
