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
    "Corriere Romagna": "https://www.corriereromagna.it/feed/",
    
    # Bologna / Imola
    "BolognaToday": "https://www.bolognatoday.it/rss",
    "Resto del Carlino - Bologna": "https://www.ilrestodelcarlino.it/bologna/rss",
    "Bologna24ore": "https://www.bologna24ore.it/feed/",
    "Bologna2000": "https://www.bologna2000.com/feed/",
    "Resto del Carlino - Imola": "https://www.ilrestodelcarlino.it/imola/rss",
    
    # Modena
    "ModenaToday": "https://www.modenatoday.it/rss",
    "Resto del Carlino - Modena": "https://www.ilrestodelcarlino.it/modena/rss",
    "Gazzetta di Modena": "https://www.gazzettadimodena.it/rss",
    "SulPanaro": "https://www.sulpanaro.net/feed/",
    "Sassuolo2000": "https://www.sassuolo2000.it/feed/",
    "La Pressa": "https://www.lapressa.it/feed/",
    
    # Reggio Emilia
    "Resto del Carlino - Reggio": "https://www.ilrestodelcarlino.it/reggio-emilia/rss",
    "Gazzetta di Reggio": "https://www.gazzettadireggio.it/rss",
    "24Emilia": "https://www.24emilia.com/feed/",
    "Reggiosera": "https://www.reggiosera.it/feed/",
    
    # Parma
    "ParmaToday": "https://www.parmatoday.it/rss",
    "Resto del Carlino - Parma": "https://www.ilrestodelcarlino.it/parma/rss",
    "Gazzetta di Parma": "https://www.gazzettadiparma.it/feed/",
    "ParmaDaily": "https://www.parmadaily.it/feed/",
    "12 TV Parma": "https://www.12tvparma.it/feed/",
    
    # Piacenza
    "PiacenzaSera": "https://www.piacenzasera.it/feed/",
    "Il Piacenza": "https://www.ilpiacenza.it/rss",
    "Libertà": "https://www.liberta.it/feed/",
    
    # Ferrara
    "Estense.com": "https://www.estense.com/feed/",
    "Resto del Carlino - Ferrara": "https://www.ilrestodelcarlino.it/ferrara/rss",
    "La Nuova Ferrara": "https://www.lanuovaferrara.it/rss",
    
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
    # Uno user-agent che simula un browser per evitare blocchi dai giornali
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

    for source_name, url in RSS_FEEDS.items():
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as response:
                xml_data = response.read()
                root = ET.fromstring(xml_data)

                for item in root.findall(".//item"):
                    title = item.findtext("title")
                    description = item.findtext("description")
                    if title:
                        text = f"Fonte: {source_name} | Titolo: {title}"
                        if description:
                            clean_desc = description.replace("<p>", "").replace("</p>", "").strip()
                            text += f" | Dettaglio: {clean_desc[:400]}"
                        articles.append(text)
        except Exception as e:
            print(f"Attenzione: Impossibile recuperare feed {source_name}: {e}")

    print(f"Raccolti {len(articles)} articoli totali dai feed RSS.")
    return articles


def build_prompt(today_str, articles_text):
    """Crea il prompt super-dettagliato per Gemini."""
    return f"""
Sei un giornalista professionista specializzato nella rassegna stampa capillare dell'Emilia-Romagna.
Oggi è il {today_str}.

Il tuo compito è analizzare i seguenti articoli grezzi raccolti da oltre 30 testate locali e produrre una **RASSEGNA STAMPA COMPLETA, RICCA E MOLTO DETTAGLIATA**. 

REGOLE ESSENZIALI DI CONTENUTO:
1. NON RIASSUMERE TROPPO E NON TAGLIARE LE NOTIZIE: se ci sono 20 notizie di cronaca per una provincia, mettile tutte in elenco puntato.
2. Riporta i nomi, le età, i luoghi (comuni, quartieri o vie) e le dinamiche esatte (arresti, incidenti, vertenze, eventi).
3. Specifica sempre la Fonte (o le fonti) alla fine di ogni singola notizia.
4. Organizza il testo rigorosamente per province.

STRUTTURA HTML DA USARE (rispondi SOLO con il codice HTML contenuto nel tag <body>, niente ```html):

<h1>Rassegna Stampa Emilia-Romagna - {today_str}</h1>

<h2>In evidenza</h2>
<ol>
  <li><strong>Titolo Notizia Principale 1</strong> — [Località]: Descrizione molto approfondita. Fonte: ...</li>
  <li><strong>Titolo Notizia Principale 2</strong> — [Località]: Descrizione molto approfondita. Fonte: ...</li>
</ol>

<h2>Cronaca</h2>

<h3>Bologna (e Imola)</h3>
<ul>
  <li><strong>Titolo notizia</strong> — [Comune/Quartiere]: Dettagli esatti dell'evento. Fonte: ...</li>
  (Inserisci TUTTE le notizie pertinenti, non scartarne nessuna)
</ul>

<h3>Modena</h3>
<ul> ... (Tutte le notizie di Modena) ... </ul>

<h3>Reggio Emilia</h3>
<ul> ... (Tutte le notizie di Reggio) ... </ul>

<h3>Parma</h3>
<ul> ... (Tutte le notizie di Parma) ... </ul>

<h3>Piacenza</h3>
<ul> ... (Tutte le notizie di Piacenza) ... </ul>

<h3>Ferrara</h3>
<ul> ... (Tutte le notizie di Ferrara) ... </ul>

<h3>Ravenna</h3>
<ul> ... (Tutte le notizie di Ravenna) ... </ul>

<h3>Forlì-Cesena</h3>
<ul> ... (Tutte le notizie di Forlì e Cesena) ... </ul>

<h3>Rimini</h3>
<ul> ... (Tutte le notizie di Rimini) ... </ul>

<h2>Economia, Lavoro e Territorio</h2>
<ul> 
  <li><strong>Titolo</strong> — Dettagli sulla vertenza, azienda o politica locale. Fonte: ...</li>
  (Usa un unico grande elenco puntato per economia, politica e istituzioni)
</ul>

ARTICOLI GREZZI RACCOLTI (Elencati per l'elaborazione):
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

    # Passiamo a Gemini i primi 300 articoli per avere massima capillarità
    articles_text = "\n".join(articles[:300]) 
    
    # 2. Inizializzazione Client Gemini
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("La variabile d'ambiente GEMINI_API_KEY non è impostata.")

    client = genai.Client(api_key=api_key)
    
    prompt = build_prompt(today_formatted, articles_text)
    
    print("Invio dati a Gemini per l'elaborazione... (Il modello Flash ha un context window enorme e leggerà tutto)")
    
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt
    )
    
    html_content = response.text.strip()
    
    if html_content.startswith("```html"):
        html_content = html_content[7:]
    if html_content.startswith("```"):
        html_content = html_content[3:]
    if html_content.endswith("```"):
        html_content = html_content[:-3]
    html_content = html_content.strip()

    # 3. Salvataggio su file
    os.makedirs("edizioni", exist_ok=True)
    out_path = os.path.join("edizioni", f"{today}.html")
    
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    print(f"Edizione salvata con successo in: {out_path}")


if __name__ == "__main__":
    generate_rassegna()
