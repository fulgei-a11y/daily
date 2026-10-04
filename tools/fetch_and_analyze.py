import os
import json
import datetime
from bs4 import BeautifulSoup
import cloudscraper
from openai import OpenAI

# ---------------------------------------------------------------------------
# CONFIGURAZIONE DELLE FONTI E DEL CLIENT
# ---------------------------------------------------------------------------

# Inizializziamo il client OpenAI (assicurati di avere la variabile d'ambiente OPENAI_API_KEY impostata)
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# Sfruttiamo cloudscraper per aggirare i controlli anti-bot (Cloudflare, ecc.)
scraper = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'windows',
        'desktop': True
    }
)

# Elenco completo ed esaustivo di tutte le fonti per l'Emilia-Romagna
FONTI_ER = [
    # Quotidiani nazionali e regionali con cronaca locale
    {"nome": "La Repubblica Bologna", "url": "https://bologna.repubblica.it/"},
    {"nome": "Corriere di Bologna", "url": "https://corrieredibologna.corriere.it/"},
    
    # Il Resto del Carlino (Edizioni Territoriali)
    {"nome": "Il Resto del Carlino - Bologna", "url": "https://www.ilrestodelcarlino.bologna.it/"},
    {"nome": "Il Resto del Carlino - Modena", "url": "https://www.ilrestodelcarlino.modena.it/"},
    {"nome": "Il Resto del Carlino - Parma", "url": "https://www.ilrestodelcarlino.parma.it/"},
    {"nome": "Il Resto del Carlino - Ferrara", "url": "https://www.ilrestodelcarlino.ferrara.it/"},
    {"nome": "Il Resto del Carlino - Ravenna", "url": "https://www.ilrestodelcarlino.ravenna.it/"},
    {"nome": "Il Resto del Carlino - Forlì", "url": "https://www.ilrestodelcarlino.forli.it/"},
    {"nome": "Il Resto del Carlino - Cesena", "url": "https://www.ilrestodelcarlino.cesena.it/"},
    {"nome": "Il Resto del Carlino - Rimini", "url": "https://www.ilrestodelcarlino.rimini.it/"},
    {"nome": "Il Resto del Carlino - Imola", "url": "https://www.ilrestodelcarlino.imola.it/"},
    
    # Network CityNews (Edizioni locali)
    {"nome": "BolognaToday", "url": "https://www.bolognatoday.it/"},
    {"nome": "ModenaToday", "url": "https://www.modenatoday.it/"},
    {"nome": "ParmaToday", "url": "https://www.parmatoday.it/"},
    {"nome": "FerraraToday", "url": "https://www.ferraratoday.it/"},
    {"nome": "RavennaToday", "url": "https://www.ravennatoday.it/"},
    {"nome": "ForlìToday", "url": "https://www.forlitoday.it/"},
    {"nome": "CesenaToday", "url": "https://www.cesenatoday.it/"},
    {"nome": "RiminiToday", "url": "https://www.riminitoday.it/"},
    {"nome": "IlPiacenza", "url": "https://www.ilpiacenza.it/"},

    # Emittenti televisive e testate giornalistiche locali
    {"nome": "Teleromagna (TR24)", "url": "https://www.teleromagna.it/it/news"},
    {"nome": "E-Tv Rete 7", "url": "https://e-tv.it/news/"},
    {"nome": "Reggionline (Telereggio)", "url": "https://www.reggionline.com/"}
]

# ---------------------------------------------------------------------------
# 1. RACCOLTA E PULIZIA DELLE PAGINE WEB
# ---------------------------------------------------------------------------
def scarica_testi_fonti(fonti):
    testi_raccolti = []
    print("Inizio la raccolta delle notizie da tutte le fonti regionali...")
    
    for fonte in fonti:
        print(f"Scaricamento da: {fonte['nome']} ({fonte['url']})...")
        try:
            response = scraper.get(fonte['url'], timeout=15)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Rimuoviamo elementi superflui (script, stili, footer, menu)
                for element in soup(["script", "style", "nav", "footer", "header", "aside"]):
                    element.decompose()
                
                # Estraiamo i titoli e i paragrafi principali
                articoli = soup.find_all(['h2', 'h3', 'p'])
                contenuto_pagina = " ".join([elem.get_text(strip=True) for elem in articoli if len(elem.get_text(strip=True)) > 20])
                
                # Tronchiamo per evitare di superare i limiti di token per singola fonte
                contenuto_pagina = contenuto_pagina[:12000]
                
                if contenuto_pagina:
                    testi_raccolti.append(f"--- FONTE: {fonte['nome']} ---\n{contenuto_pagina}\n")
            else:
                print(f"Errore HTTP {response.status_code} per {fonte['nome']}")
        except Exception as e:
            print(f"Impossibile raggiungere {fonte['nome']}: {e}")
            
    return "\n".join(testi_raccolti)

# ---------------------------------------------------------------------------
# 2. ANALISI E SINTESI TRAMITE MODELLO AI
# ---------------------------------------------------------------------------
def analizza_e_struttura_notizie(testo_grezzo, data_odierna):
    print("Elaborazione e sintesi delle notizie in corso con l'intelligenza artificiale...")
    
    prompt = f"""
Sei un caporedattore di una rassegna stampa quotidiana seria ed elegante sull'Emilia-Romagna.
Analizza i testi raccolti da tutte le testate e portali locali per l'edizione del {data_odierna}.

Crea una rassegna strutturata suddivisa in sezioni logiche (es. Cronaca, Economia, Politica, Territorio).
Restituisci ESCLUSIVAMENTE un blocco JSON valido che rispetti questo schema esatto, senza aggiungere altro testo fuori dal JSON:
{{
  "data": "{data_odierna}",
  "sezioni": [
    {{
      "titolo_sezione": "Nome Sezione (es. CRONACA)",
      "sottosezione": "Eventuale sottotitolo o lascia stringa vuota",
      "notizie": [
        "Testo della notizia 1, scritto con tono giornalistico e fluido, completo di indicazione della fonte.",
        "Testo della notizia 2..."
      ]
    }}
  ]
}}

Ecco i testi grezzi delle fonti giornalistiche da cui estrarre le notizie:
{testo_grezzo}
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "Sei un assistente editoriale rigoroso che restituisce solo JSON."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.3
    )
    
    return json.loads(response.choices.message.content)

# ---------------------------------------------------------------------------
# 3. GENERAZIONE DEI FILE FINALI (JSON)
# ---------------------------------------------------------------------------
def genera_output(dati_rassegna):
    data_iso = dati_rassegna.get("data", datetime.date.today().isoformat())
    
    # Salvataggio del file JSON dell'edizione
    nome_file_json = f"audio-{data_iso}.json"
    with open(nome_file_json, "w", encoding="utf-8") as f:
        json.dump(dati_rassegna, f, ensure_ascii=False, indent=2)
    print(f"Creato con successo il file di dati: {nome_file_json}")

# ---------------------------------------------------------------------------
# ESECUZIONE PRINCIPALE
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    data_corrente = datetime.date.today().isoformat()
    
    # Step 1: Scarica i testi da tutte le fonti regionali
    testi = scarica_testi_fonti(FONTI_ER)
    
    if testi.strip():
        # Step 2: Analizza e sintetizza con l'AI
        rassegna_strutturata = analizza_e_struttura_notizie(testi, data_corrente)
        
        # Step 3: Salva gli output pronti per il frontend
        genera_output(rassegna_strutturata)
        print("Pipeline completata con successo!")
    else:
        print("Nessun testo scaricato dalle fonti. Verifica la connessione o i selettori.")
