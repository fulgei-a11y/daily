import os
import datetime
import urllib.request
import xml.etree.ElementTree as ET
from google import genai

# ==========================================
# 1. LISTA COMPLETA FEED RSS EMILIA-ROMAGNA
# ==========================================
RSS_FEEDS = {
    # Generali / Regionali
    "ANSA Emilia-Romagna": "https://www.ansa.it/emiliaromagna/notizie/emiliaromagna_rss.xml",
    "RAI TGR Emilia-Romagna": "https://www.rainews.it/rss/tgr/emiliaromagna",
    
    # Bologna / Imola
    "BolognaToday": "https://www.bolognatoday.it/rss",
    "Resto del Carlino - Bologna": "https://www.ilrestodelcarlino.it/bologna/rss",
    "Resto del Carlino - Imola": "https://www.ilrestodelcarlino.it/imola/rss",
    
    # Modena
    "ModenaToday": "https://www.modenatoday.it/rss",
    "Resto del Carlino - Modena": "https://www.ilrestodelcarlino.it/modena/rss",
    "SulPanaro": "https://www.sulpanaro.net/feed/",
    
    # Reggio Emilia
    "Resto del Carlino - Reggio": "https://www.ilrestodelcarlino.it/reggio-emilia/rss",
    "24Emilia": "https://www.24emilia.com/feed/",
    "Reggiosera": "https://www.reggiosera.it/feed/",
    
    # Parma
    "ParmaToday": "https://www.parmatoday.it/rss",
    "Resto del Carlino - Parma": "https://www.ilrestodelcarlino.it/parma/rss",
    
    # Piacenza
    "PiacenzaSera": "https://www.piacenzasera.it/feed/",
    
    # Ferrara
    "Estense.com": "https://www.estense.com/feed/",
    "Resto del Carlino - Ferrara": "https://www.ilrestodelcarlino.it/ferrara/rss",
    
    # Ravenna
    "RavennaToday": "https://www.ravennatoday.it/rss",
    "RavennaNotizie": "https://www.ravennanotizie.it/feed/",
    "Resto del Carlino - Ravenna": "https://www.ilrestodelcarlino.it/ravenna/rss",
    
    # Forlì-Cesena
    "ForlìToday": "https://www.forlitoday.it/rss",
    "CesenaToday": "https://www.cesenatoday.it/rss",
    "Resto del Carlino - Forlì": "https://www.ilrestodelcarlino.it/forli/rss",
    "Resto del Carlino - Cesena": "https://www.ilrestodelcarlino.it/cesena/rss",
    
    # Rimini
    "RiminiToday": "https://www.riminitoday.it/rss",
    "Resto del Carlino - Rimini": "https://www.ilrestodelcarlino.it/rimini/rss",
}


def fetch_rss_articles():
    """Raccoglie tutti gli articoli disponibili dai feed RSS."""
    articles = []
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    for source_name, url in RSS_FEEDS.items():
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                xml_data = response.read()
                root = ET.fromstring(xml_data)

                # Gestione RSS standard
                for item in root.findall(".//item"):
                    title = item.findtext("title")
                    description = item.findtext("description")
                    if title:
                        text = f"Fonte: {source_name} | Titolo: {title}"
                        if description:
                            # Pulizia tag HTML base se presenti
                            clean_desc = description.replace("<p>", "").replace("</p>", "").strip()
                            text += f" | Dettaglio: {clean_desc[:300]}"
                        articles.append(text)
        except Exception as e:
            print(f"Attenzione: Impossibile recuperare feed {source_name}: {e}")

    print(f"Raccolti {len(articles)} articoli totali dai feed RSS.")
    return articles


def build_prompt(today_str, articles_text):
    """Crea il prompt dettagliato per Gemini."""
    return f"""
Sei un giornalista professionista specializzato nella rassegna stampa dell'Emilia-Romagna.
Oggi è il {today_str}.

Il tuo compito è analizzare i seguenti articoli grezzi raccolti dalle testate locali e produrre una **RASSEGNA STAMPA COMPLETA, RICCA E MOLTO DETTAGLIATA**.

REGOLE ESSENZIALI DI CONTENUTO:
1. NON riassumere eccessivamente: riporta OGNI fatto di cronaca, vertenza, intervento di soccorso, operazione delle forze dell'ordine o evento rilevante.
2. Organizza la rassegna rigorosamente per sezioni e per singola provincia.
3. Se per una provincia ci sono più notizie, inseriscile TUTTE come punti distinti sotto quella provincia.
4. Ogni notizia deve riportare la cittadina/comune specifico, una descrizione dettagliata del fatto (cosa è successo, chi è coinvolto, numeri, dinamica) e la fonte.

STRUTTURA HTML REQUISITA (rispondi SOLO con il codice HTML contenuto nel tag <body>):

<h1>Rassegna Stampa Emilia-Romagna - {today_str}</h1>

<h2>In evidenza</h2>
<ol>
  <li><strong>Titolo Notizia Principale 1</strong> — Descrizione approfondita dei fatti più importanti della giornata.</li>
  <li><strong>Titolo Notizia Principale 2</strong> — ...</li>
  <li><strong>Titolo Notizia Principale 3</strong> — ...</li>
</ol>

<h2>Cronaca</h2>

<h3>Bologna (e Imola)</h3>
<ul>
  <li><strong>Titolo notizia o fatto</strong> — [Comune/Quartiere]: Spiegazione dettagliata dell'accaduto con tutti i dettagli disponibili. Fonte: ...</li>
</ul>

<h3>Modena</h3>
<ul> ... </ul>

<h3>Reggio Emilia</h3>
<ul> ... </ul>

<h3>Parma</h3>
<ul> ... </ul>

<h3>Piacenza</h3>
<ul> ... </ul>

<h3>Ferrara</h3>
<ul> ... </ul>

<h3>Ravenna</h3>
<ul> ... </ul>

<h3>Forlì-Cesena</h3>
<ul> ... </ul>

<h3>Rimini</h3>
<ul> ... </ul>

<h2>Economia e lavoro</h2>
<h3>Imprese e vertenze</h3>
<ul> ... </ul>
<h3>Dati e congiuntura</h3>
<ul> ... </ul>
<h3>Regione e istituzioni</h3>
<ul> ... </ul>
<h3>Infrastrutture, agricoltura, turismo</h3>
<ul> ... </ul>

<h2>Politica e amministrazione</h2>
<ul> ... </ul>

<h2>Da seguire oggi</h2>
<ul> ... </ul>

Tutti i tag devono essere HTML pulito e ben formattato. Non includere blocchi di codice tipo ```html, restituisci solo il frammento HTML.

ARTICOLI GREZZI RACCOLTI:
{articles_text}
"""


def generate_rassegna():
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    today_formatted = datetime.datetime.now().strftime("%d/%m/%Y")
    
    print(f"Inizio elaborazione rassegna per la data: {today}")
    
    # 1. Raccolta articoli
    articles = fetch_rss_articles()
    if not articles:
        print("Errore: Nessun articolo recuperato dai feed.")
        return

    articles_text = "\n".join(articles[:120]) # Prende fino a 120 articoli per dare massima copertura
    
    # 2. Inizializzazione Client Gemini
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("La variabile d'ambiente GEMINI_API_KEY non è impostata.")

    client = genai.Client(api_key=api_key)
    
    prompt = build_prompt(today_formatted, articles_text)
    
    print("Invio dati a Gemini per l'elaborazione...")
    
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt
    )
    
    html_content = response.text.strip()
    
    # Rimuove eventuali marcatori markdown ```html se presenti
    if html_content.startswith("```html"):
        html_content = html_content[7:]
    if html_content.startswith("```"):
        html_content = html_content[3:]
    if html_content.endswith("```"):
        html_content = html_content[:-3]
    html_content = html_content.strip()

    # 3. Salvataggio su file edizioni/YYYY-MM-DD.html
    os.makedirs("edizioni", exist_ok=True)
    out_path = os.path.join("edizioni", f"{today}.html")
    
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    print(f"Edizione salvata con successo in: {out_path}")


if __name__ == "__main__":
    generate_rassegna()
