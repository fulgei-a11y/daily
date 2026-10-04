import os
import re
import datetime
import urllib.request
import xml.etree.ElementTree as ET
from google import genai

# 1. FONTI COMPLETA EDESISTENTI PER L'EMILIA-ROMAGNA (Tutte le 9 province + Economia + Regione)
RSS_SOURCES = {
    "ANSA Emilia-Romagna": "https://www.ansa.it/emiliaromagna/notizie/emiliaromagna_rss.xml",
    "Regione Emilia-Romagna": "https://www.regione.emilia-romagna.it/notizie/rss/notizie-dalla-regione",
    "Resto del Carlino - Bologna": "https://www.ilrestodelcarlino.it/bologna/rss",
    "Resto del Carlino - Modena": "https://www.ilrestodelcarlino.it/modena/rss",
    "Resto del Carlino - Reggio Emilia": "https://www.ilrestodelcarlino.it/reggio-emilia/rss",
    "Resto del Carlino - Ferrara": "https://www.ilrestodelcarlino.it/ferrara/rss",
    "Resto del Carlino - Ravenna": "https://www.ilrestodelcarlino.it/ravenna/rss",
    "Resto del Carlino - Forlì": "https://www.ilrestodelcarlino.it/forli/rss",
    "Resto del Carlino - Cesena": "https://www.ilrestodelcarlino.it/cesena/rss",
    "Resto del Carlino - Rimini": "https://www.ilrestodelcarlino.it/rimini/rss",
    "Resto del Carlino - Imola": "https://www.ilrestodelcarlino.it/imola/rss",
    "BolognaToday": "https://www.bolognatoday.it/rss",
    "ModenaToday": "https://www.modenatoday.it/rss",
    "RomagnaToday": "https://www.romagnatoday.it/rss",
    "ParmaToday": "https://www.parmatoday.it/rss",
    "Il Sole 24 Ore - Italia": "https://www.ilsole24ore.com/rss/italia.xml"
}

def fetch_all_regional_news():
    """Scandaglia tutte le fonti regionali e locali raccogliendo notizie e dettagli"""
    collected_articles = []
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    print("-> Avvio scansione fonti capillari dell'Emilia-Romagna...")
    for source_name, url in RSS_SOURCES.items():
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                xml_data = response.read()
                root = ET.fromstring(xml_data)
                
                count = 0
                for item in root.findall('.//item'):
                    if count >= 4: # Prende fino a 4 notizie principali per ogni testata
                        break
                    
                    title = item.findtext('title', default='').strip()
                    desc = item.findtext('description', default='').strip()
                    link = item.findtext('link', default='').strip()
                    
                    # Pulizia HTML dalle descrizioni
                    desc_clean = re.sub('<[^<]+?>', '', desc)
                    
                    if title:
                        collected_articles.append(
                            f"Fonte: [{source_name}] ({link})\n"
                            f"Titolo: {title}\n"
                            f"Dettagli: {desc_clean}\n"
                        )
                        count += 1
        except Exception as e:
            print(f"Nota: Impossibile leggere il feed {source_name}: {e}")
            
    print(f"-> Raccolti {len(collected_articles)} articoli dalle fonti locali.")
    return "\n---\n".join(collected_articles)

def generate_rassegna_with_claude_instructions(news_data, today_formatted):
    """Invia tutto il materiale a Gemini imponendo il rigoroso sistema di istruzioni di Claude"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY non trovata nei Secrets di GitHub!")

    client = genai.Client(api_key=api_key)

    prompt = f"""
IMPORTANTE: Questo è un lavoro professionale di redazione per una rassegna stampa radiofonica dell'Emilia-Romagna.
Non fare un riassunto veloce: sii circostanziato, puntuale e dettagliato (chi, cosa, dove, comune e provincia, quando, cifre, nomi di persone/aziende/enti, stato dei fatti).

Data di oggi: {today_formatted}

Ecco il materiale grezzo raccolto nelle ultime 24 ore dalle principali testate regionali e provinciali:

{news_data}

---

Sulla base di questo materiale, produci la RASSEGNA MATTUTINA DELL'EMILIA-ROMAGNA.
Copri OBBLIGATORIAMENTE tutte le 9 province: Bologna (e Imola), Modena, Reggio Emilia, Parma, Piacenza, Ferrara, Ravenna, Forlì-Cesena, Rimini.

Svolgi l'analisi approfondita per:
- CRONACA: incidenti gravi, delitti, arresti, operazioni di polizia/carabinieri/GdF, processi, inchieste, emergenze ambientali/sanitarie, allerte meteo.
- ECONOMIA: crisi aziendali, vertenze, cassa integrazione, licenziamenti, scioperi, acquisizioni, investimenti, risultati di aziende regionali, dati congiunturali (export, occupazione), agricoltura, turismo, infrastrutture.

IMPORTANTE: Restituisci ESCLUSIVAMENTE codice HTML pulito (senza blocchi markdown ```html, senza tag <!DOCTYPE>, <html> o <body>).
L'HTML deve seguire rigorosamente questa struttura esatta richiesta dall'App PWA:

<div class="edition">
  <h2>Rassegna Stampa Emilia-Romagna - {today_formatted}</h2>
  
  <div class="evid">
    <h2>In evidenza</h2>
    <ol>
      <li><strong>Titolo Notizia 1</strong> — Descrizione dettagliata di 2-3 righe con le notizie più importanti...</li>
      <li><strong>Titolo Notizia 2</strong> — Descrizione dettagliata di 2-3 righe...</li>
      <li><strong>Titolo Notizia 3</strong> — Descrizione dettagliata di 2-3 righe...</li>
    </ol>
  </div>

  <h2>Cronaca</h2>
  
  <h3>Bologna (e Imola)</h3>
  <article id="item-1" data-i="1">
    <p><strong>Titolo sintetico</strong> — comune (provincia): descrizione dettagliata di 3-6 righe con tutti i fatti essenziali (nomi, età, cifre, forze dell'ordine coinvolte, sviluppi). Fonte: <a target="_blank" rel="noopener" href="URL_SE_DISPONIBILE">Nome Testata</a></p>
  </article>

  <h3>Modena</h3>
  <article id="item-2" data-i="2">
    <p><strong>Titolo sintetico</strong> — comune (provincia): descrizione dettagliata...</p>
  </article>

  <h3>Reggio Emilia</h3>
  <article id="item-3" data-i="3">
    <p><strong>Titolo sintetico</strong> — comune (provincia): descrizione dettagliata...</p>
  </article>

  <h3>Parma</h3>
  <article id="item-4" data-i="4">
    <p><strong>Titolo sintetico</strong> — comune (provincia): descrizione dettagliata...</p>
  </article>

  <h3>Piacenza</h3>
  <article id="item-5" data-i="5">
    <p><strong>Titolo sintetico</strong> — comune (provincia): descrizione dettagliata...</p>
  </article>

  <h3>Ferrara</h3>
  <article id="item-6" data-i="6">
    <p><strong>Titolo sintetico</strong> — comune (provincia): descrizione dettagliata...</p>
  </article>

  <h3>Ravenna</h3>
  <article id="item-7" data-i="7">
    <p><strong>Titolo sintetico</strong> — comune (provincia): descrizione dettagliata...</p>
  </article>

  <h3>Forlì-Cesena</h3>
  <article id="item-8" data-i="8">
    <p><strong>Titolo sintetico</strong> — comune (provincia): descrizione dettagliata...</p>
  </article>

  <h3>Rimini</h3>
  <article id="item-9" data-i="9">
    <p><strong>Titolo sintetico</strong> — comune (provincia): descrizione dettagliata...</p>
  </article>

  <h2>Economia e lavoro</h2>
  
  <h3>Imprese e vertenze</h3>
  <article id="item-10" data-i="10">
    <p><strong>Titolo sintetico</strong> — Dettagli, cifre, aziende coinvolte...</p>
  </article>

  <h3>Dati e congiuntura</h3>
  <article id="item-11" data-i="11">
    <p><strong>Titolo sintetico</strong> — Dati Istat, Unioncamere, export...</p>
  </article>

  <h3>Regione e istituzioni</h3>
  <article id="item-12" data-i="12">
    <p><strong>Titolo sintetico</strong> — Bandi, delibere e finanziamenti regionali...</p>
  </article>

  <h3>Infrastrutture, agricoltura, turismo</h3>
  <article id="item-13" data-i="13">
    <p><strong>Titolo sintetico</strong> — Dettagli su cantieri, porti, aeroporti, agricoltura...</p>
  </article>

  <h2>Politica e amministrazione</h2>
  <article id="item-14" data-i="14">
    <p><strong>Titolo sintetico</strong> — Fatti rilevanti della giunta o consiglio regionale...</p>
  </article>

  <h2>Da seguire oggi</h2>
  <article id="item-15" data-i="15">
    <p><strong>Eventi e scadenze</strong> — Udienze, scioperi, consigli comunali o eventi in programma oggi...</p>
  </article>
</div>

Sii estremamente preciso. Incrementa progressivamente l'attributo data-i="X" e id="item-X" per ogni articolo <article> che crei.
Se per una provincia non ci sono notizie rilevanti nelle notizie fornite, inserisci un articolo che lo dichiara espressamente.
"""

    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
    )
    
    html_content = response.text.strip()
    # Rimuove blocchi di codice markdown se presenti
    html_content = re.sub(r'^```html\s*', '', html_content)
    html_content = re.sub(r'^```\s*', '', html_content)
    html_content = re.sub(r'\s*```$', '', html_content)
    
    return html_content

def main():
    today_str = datetime.date.today().strftime('%Y-%m-%d')
    output_dir = 'edizioni'
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, f"{today_str}.html")

    print(f"[{today_str}] Inizio elaborazione rassegna professionale Emilia-Romagna...")
    news_data = fetch_all_regional_news()
    
    print(f"[{today_str}] Generazione HTML e analisi giornalistica tramite IA...")
    html_code = generate_rassegna_with_claude_instructions(news_data, today_str)

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html_code)

    print(f"[{today_str}] Rassegna completa salvata con successo in {output_file}")

if __name__ == "__main__":
    main()
