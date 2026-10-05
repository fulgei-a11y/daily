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
    return detected if detected else ["Emilia-Romagna"]

# ==========================================
# 3. PIPELINE DI RACCOLTA
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
                extended_desc = summary[:800]

                raw_articles.append({
                    "title": title,
                    "desc": extended_desc,
                    "link": link,
                    "source": source_name,
                    "score": score,
                    "provinces": provinces
                })
        except Exception as e:
            print(f"Errore nella lettura del feed {feed_url}: {e}")

    print(f"--> Raccolti e filtrati {len(raw_articles)} articoli validi.")
    raw_articles.sort(key=lambda x: x["score"], reverse=True)
    return raw_articles

# ==========================================
# 4. ROBUSTA GENERAZIONE CON RETRY & PAUSE
# ==========================================

def generate_section_html(section_title, articles_list, prompt_instruction):
    if not articles_list:
        return f"<section><h2>{section_title}</h2><p>Nessun aggiornamento di rilievo nelle ultime ore.</p></section>"

    formatted_articles = ""
    for idx, a in enumerate(articles_list, 1):
        formatted_articles += f"""
---
ARTICOLO {idx}:
Titolo: {a['title']}
Fonte: {a['source']}
Territorio: {', '.join(a['provinces'])}
Punteggio Rilevanza: {a['score']}
Testo: {a['desc']}
Link: {a['link']}
"""

    prompt = f"""
Sei un caporedattore esperto specializzato in Pubblica Amministrazione, Economia e Cronaca della Regione Emilia-Romagna.

Compito: Genera il codice HTML pulito e ben strutturato per la sezione "{section_title}".

ISTRUZIONI DI REDAZIONE:
1. {prompt_instruction}
2. Non inserire notizie sportive, di gossip, spettacoli minori o curiosità.
3. Raggruppa le notizie in modo chiaro per argomento o per Provincia se pertinente.
4. Per ogni notizia includi:
   - Titolo chiaro ed esaustivo in <h3> o <h4>
   - Un riassunto giornalistico accurato ed esaustivo (2-4 frasi)
   - L'indicazione della fonte e il link originale `<a href="..." target="_blank">Leggi su [Fonte]</a>`
5. Usa tag HTML semanticamente corretti (`<section>`, `<h3>`, `<p>`, `<ul>`, `<li>`, `<strong>`).
6. NON restituire blocchi markdown ```html ... ```, restituisci solo il codice HTML grezzo.

ARTICOLI A DISPOSIZIONE:
{formatted_articles}
"""
    # Meccanismo di tentativi multipli (Retry) per evitare fallimenti temporanei API
    for attempt in range(3):
        try:
            response = model.generate_content(prompt)
            text = response.text.strip()
            text = re.sub(r'^```html\s*', '', text)
            text = re.sub(r'\s*```$', '', text)
            time.sleep(2) # Pausa di cortesia per rate-limiting
            return text
        except Exception as e:
            print(f"Tentativo {attempt+1} fallito per la sezione {section_title}: {e}")
            time.sleep(4)

    # Fallback se tutti i tentativi falliscono: genera HTML semplice con gli articoli ricevuti
    print(f"-> Utilizzo fallback locale per {section_title}")
    fallback_html = f"<section><h2>{section_title}</h2>"
    for a in articles_list[:8]:
        fallback_html += f"<h3>{a['title']}</h3><p>{a['desc']}</p><p><a href='{a['link']}' target='_blank'>Leggi su {a['source']}</a></p>"
    fallback_html += "</section>"
    return fallback_html

# ==========================================
# 5. ASSEMBLAGGIO FINALE DEL DOCUMENTO
# ==========================================

def build_full_rassegna():
    articles = fetch_and_process_news()
    
    top_regional = [a for a in articles if "Emilia-Romagna" in a["provinces"] or a["score"] >= 8][:12]
    top_economy = [a for a in articles if any(k in f"{a['title']} {a['desc']}".lower() for k in KW_ECONOMIA)][:15]
    top_cronaca = [a for a in articles if any(k in f"{a['title']} {a['desc']}".lower() for k in KW_CRONACA)][:18]
    top_pa = [a for a in articles if any(k in f"{a['title']} {a['desc']}".lower() for k in KW_PA)][:18]

    print("--> 2. Generazione sezione: Prima Pagina & Pubblica Amministrazione...")
    html_pa = generate_section_html(
        "Prima Pagina e Pubblica Amministrazione",
        top_pa + top_regional,
        "Focalizzati sulle delibere della Regione, atti dei Comuni, sanità (AUSL), PNRR, bandi e decisioni istituzionali per ciascuna provincia."
    )

    print("--> 3. Generazione sezione: Economia, Lavoro e Imprese...")
    html_eco = generate_section_html(
        "Economia, Lavoro e Imprese",
        top_economy,
        "Evidenzia vertenze aziendali, accordi sindacali, investimenti, fiere, export, infrastrutture e mercati dell'Emilia-Romagna."
    )

    print("--> 4. Generazione sezione: Cronaca, Sicurezza e Protezione Civile...")
    html_cro = generate_section_html(
        "Cronaca e Sicurezza",
        top_cronaca,
        "Riporta i fatti di cronaca giudiziaria, arresti, operazioni di polizia, incidenti rilevanti, incendi ed allerte meteo/Protezione Civile."
    )

    today_str = datetime.now().strftime("%d/%m/%Y")
    
    full_html = f"""<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Rassegna Stampa Emilia-Romagna - {today_str}</title>
    <style>
        body {{
            font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
            line-height: 1.6;
            color: #222;
            background-color: #f4f6f8;
            margin: 0;
            padding: 20px;
        }}
        .container {{
            max-width: 900px;
            margin: 0 auto;
            background: #ffffff;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.05);
        }}
        header {{
            border-bottom: 3px solid #d9534f;
            padding-bottom: 15px;
            margin-bottom: 30px;
        }}
        h1 {{
            color: #111;
            margin: 0 0 5px 0;
            font-size: 28px;
        }}
        .date {{
            color: #666;
            font-weight: bold;
        }}
        section {{
            margin-bottom: 35px;
        }}
        h2 {{
            color: #d9534f;
            border-bottom: 1px solid #eee;
            padding-bottom: 8px;
            font-size: 22px;
        }}
        h3 {{
            color: #2c3e50;
            margin-top: 20px;
            margin-bottom: 8px;
            font-size: 18px;
        }}
        p {{
            margin-top: 0;
            margin-bottom: 12px;
        }}
        a {{
            color: #0275d8;
            text-decoration: none;
            font-size: 14px;
        }}
        a:hover {{
            text-decoration: underline;
        }}
        footer {{
            margin-top: 40px;
            text-align: center;
            font-size: 13px;
            color: #888;
            border-top: 1px solid #eee;
            padding-top: 15px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Rassegna Stampa Emilia-Romagna</h1>
            <div class="date">Edizione del {today_str} — PA, Economia e Territorio</div>
        </header>

        <main>
            {html_pa}
            {html_eco}
            {html_cro}
        </main>

        <footer>
            Generato automaticamente via GitHub Actions & Gemini API — Emilia-Romagna Monitor
        </footer>
    </div>
</body>
</html>
"""
    
    # Salvataggio nella cartella edizioni
    os.makedirs("edizioni", exist_ok=True)
    today_filename = datetime.now().strftime("%Y-%m-%d.html")
    output_path = os.path.join("edizioni", today_filename)
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(full_html)
        
    print(f"--> Rassegna completata con successo! Salvata in '{output_path}'.")

if __name__ == "__main__":
    build_full_rassegna()
