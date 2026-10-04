import os
import time
import datetime
import urllib.request
import xml.etree.ElementTree as ET
from google import genai
from google.genai import errors

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
    """Raccoglie tutti gli articoli dai feed RSS in modo resiliente."""
    articles = []
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}

    for source_name, url in RSS_FEEDS.items():
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as response:
                xml_bytes = response.read()
                
                # Gestione dei caratteri non validi nei feed XML locali
                try:
                    root = ET.fromstring(xml_bytes)
                except ET.ParseError:
                    cleaned_xml = xml_bytes.decode('utf-8', errors='ignore')
                    root = ET.fromstring(cleaned_xml)

                for item in root.findall(".//item"):
                    title = item.findtext("title")
                    description = item.findtext("description")
                    if title:
                        text = f"Fonte: {source_name} | Titolo: {title.strip()}"
                        if description:
                            # Sanificazione tag HTML elementari dal sommario
                            clean_desc = description.replace("<p>", "").replace("</p>", "").replace("<br>", "").replace("<br/>", "").strip()
                            text += f" | Dettaglio: {clean_desc[:500]}"
                        articles.append(text)
        except Exception as e:
            print(f"Attenzione: Impossibile recuperare feed {source_name}: {e}")

    print(f"Raccolti {len(articles)} articoli totali da {len(RSS_FEEDS)} fonti locali.")
    return articles


def build_prompt(today_str, articles_text):
    """Crea il prompt ad alta densità informativa per l'analisi di Gemini."""
    return f"""
Sei un caporedattore e analista d'informazione professionista. Il tuo compito è redigere la **Rassegna Stampa Ufficiale dell'Emilia-Romagna** per la giornata del {today_str}.

I dati provengono da oltre 30 testate giornalistiche regionali e provinciali. Devi produrre un documento HTML **estremamente utile, ricco, operativo e ad alto valore informativo**. Evita assolutamente sintesi generiche, banalità o omissioni.

REGOLE DI REDAZIONE RIGOROSE:
1. **DENSITÀ ED ESATTEZZA**: Conserva dettagli concreti come nomi delle persone coinvolte, età, vie o quartieri specifici, importi economici, decisioni amministrative e dinamiche dettagliate.
2. **COPERTURA CAPILLARE**: Non scartare le notizie locali minori se sono rilevanti per il territorio. Se per una provincia ci sono 15 notizie di cronaca o utilità, inseriscile tutte.
3. **ATTRIBUZIONE FONTI**: Ogni singolo punto informativo deve riportare tra parentesi la fonte originale (es. *Fonte: BolognaToday* o *Fonte: ANSA Emilia-Romagna / Resto del Carlino*).
4. **ORGANIZZAZIONE**: Suddividi chiaramente la cronaca per singola provincia.

FORMATO DI OUTPUT RICHIESTO (Fornisci ESCLUSIVAMENTE il contenuto HTML interno al tag <body>, SENZA blocchi markdown ```html):

<h1>Rassegna Stampa Emilia-Romagna - {today_str}</h1>

<h2>In Evidenza e Notizie Principali</h2>
<ol>
  <li><strong>[Titolo Notizia Fondamentale 1]</strong> — <em>[Località]</em>: Analisi approfondita ed esaustiva dell'evento, impatto sul territorio, dichiarazioni e dettagli esecutivi. (Fonte: ...)</li>
  <li><strong>[Titolo Notizia Fondamentale 2]</strong> — <em>[Località]</em>: Analisi approfondita ed esaustiva dell'evento. (Fonte: ...)</li>
</ol>

<h2>Cronaca Provinciale Capillare</h2>

<h3>Bologna e Imola</h3>
<ul>
  <li><strong>[Titolo Notizia]</strong> — <em>[Comune/Quartiere]</em>: Dettaglio completo, nomi, fatti ed evoluzioni. (Fonte: ...)</li>
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

<h2>Economia, Lavoro, Infrastrutture e Politica Regionale</h2>
<ul>
  <li><strong>[Titolo Argomento]</strong> — Dettagli esatti su vertenze sindacali, investimenti aziendali, bandi pubblici o decisioni della Giunta Regionale. (Fonte: ...)</li>
</ul>

ARTICOLI GREZZI ACQUISITI DALLE FONTI LOCALI:
{articles_text}
"""


def generate_rassegna():
    today_file_fmt = datetime.datetime.now().strftime("%Y-%m-%d")
    today_display_fmt = datetime.datetime.now().strftime("%d/%m/%Y")
    
    print(f"[{today_file_fmt}] Avvio scansione e analisi rassegna stampa...")
    
    # 1. Raccolta dati
    articles = fetch_rss_articles()
    if not articles:
        print("Errore critico: Nessun articolo recuperato dalle fonti RSS.")
        return

    # Invia fino a 350 articoli per garantire massima ricchezza di contenuto
    articles_text = "\n".join(articles[:350]) 
    
    # 2. Configurazione Client Gemini
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("La variabile d'ambiente GEMINI_API_KEY non è impostata.")

    client = genai.Client(api_key=api_key)
    prompt = build_prompt(today_display_fmt, articles_text)
    
    # Stratificazione modelli per prevenire blocchi da 503 Server Unavailable
    candidate_models = ['gemini-2.5-flash', 'gemini-1.5-flash', 'gemini-1.5-pro']
    max_retries_per_model = 3
    html_content = None

    for model_name in candidate_models:
        for attempt in range(1, max_retries_per_model + 1):
            try:
                print(f"[IA] Generazione in corso con '{model_name}' (Tentativo {attempt}/{max_retries_per_model})...")
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )
                if response and response.text:
                    html_content = response.text.strip()
                    break
            except errors.ServerError as e:
                print(f"[503 Server Demand] Il modello {model_name} è momentaneamente occupato: {e}")
                if attempt < max_retries_per_model:
                    wait_seconds = attempt * 10
                    print(f"Pausa tattica di {wait_seconds}s prima del re-try...")
                    time.sleep(wait_seconds)
            except Exception as e:
                print(f"Eccezione con {model_name}: {e}")
                break

        if html_content:
            print(f"Generazione completata con successo tramite modello '{model_name}'.")
            break

    if not html_content:
        raise RuntimeError("Impossibile completare l'analisi: tutti i modelli dell'API risultano temporaneamente occupati.")

    # Sanitizzazione blocchi di codice markdown
    if html_content.startswith("```html"):
        html_content = html_content[7:]
    if html_content.startswith("```"):
        html_content = html_content[3:]
    if html_content.endswith("```"):
        html_content = html_content[:-3]
    html_content = html_content.strip()

    # 3. Salvataggio
    os.makedirs("edizioni", exist_ok=True)
    out_path = os.path.join("edizioni", f"{today_file_fmt}.html")
    
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    print(f"File dell'edizione salvato correttamente in: {out_path}")


if __name__ == "__main__":
    generate_rassegna()
