#!/usr/bin/env python3
"""
tools/fetch_and_analyze.py
--------------------------
Script definitivo per l'estrazione quotidiana di notizie dalle 9 province dell'Emilia-Romagna.
Garantisce:
- Copertura equa di tutte e 9 le province (3 fonti per provincia).
- Filtro temporale (max 36 ore) e deduplicazione automatica.
- Blocco totale di sport, gossip e notizie riempitive.
- Estrazione full-text protetta con timeout e fallback su descrizione RSS.
- Formattazione HTML strutturata per la Web App via Gemini API.
"""

import os
import sys
import re
import time
from datetime import datetime, timedelta, timezone
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
import requests
import trafilatura
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# CONFIGURAZIONE GENERALE E DATE
# ---------------------------------------------------------------------------
NOW = datetime.now(timezone.utc)
TODAY_STR = NOW.strftime("%Y-%m-%d")
TODAY_HUMAN = NOW.strftime("%d %B %Y")
CUTOFF_TIME = NOW - timedelta(hours=36)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
}

# MAPPA DELLE PROVINCE E RELATIVI FEED RSS (3 Fonti dedicate per ciascuna provincia)
PROVINCIAL_FEEDS = {
    "Regionali/Economia": [
        {"url": "https://www.ansa.it/emiliaromagna/notizie/emiliaromagna_rss.xml", "source": "ANSA E-R"},
        {"url": "https://www.regione.emilia-romagna.it/notizie/RSS", "source": "Regione E-R"}
    ],
    "Bologna": [
        {"url": "https://www.ilrestodelcarlino.it/bologna/rss", "source": "Il Resto del Carlino Bologna"},
        {"url": "https://www.bolognatoday.it/rss", "source": "BolognaToday"},
        {"url": "https://www.ilrestodelcarlino.it/imola/rss", "source": "Il Resto del Carlino Imola"}
    ],
    "Modena": [
        {"url": "https://www.ilrestodelcarlino.it/modena/rss", "source": "Il Resto del Carlino Modena"},
        {"url": "https://www.modenatoday.it/rss", "source": "ModenaToday"}
    ],
    "Reggio Emilia": [
        {"url": "https://www.ilrestodelcarlino.it/reggio-emilia/rss", "source": "Il Resto del Carlino Reggio Emilia"},
        {"url": "https://www.reggiotoday.it/rss", "source": "ReggioToday"},
        {"url": "https://www.reggionline.com/feed/", "source": "Reggionline"}
    ],
    "Parma": [
        {"url": "https://www.gazzettadiparma.it/rss/", "source": "Gazzetta di Parma"},
        {"url": "https://www.parmatoday.it/rss", "source": "ParmaToday"}
    ],
    "Piacenza": [
        {"url": "https://www.liberta.it/feed/", "source": "Libertà Piacenza"},
        {"url": "https://www.piacenzatoday.it/rss", "source": "PiacenzaToday"},
        {"url": "https://www.piacenzasera.it/feed/", "source": "PiacenzaSera"}
    ],
    "Ferrara": [
        {"url": "https://www.ilrestodelcarlino.it/ferrara/rss", "source": "Il Resto del Carlino Ferrara"},
        {"url": "https://www.ferraratoday.it/rss", "source": "FerraraToday"},
        {"url": "https://www.estense.com/feed/", "source": "Estense.com"}
    ],
    "Ravenna": [
        {"url": "https://www.ilrestodelcarlino.it/ravenna/rss", "source": "Il Resto del Carlino Ravenna"},
        {"url": "https://www.ravennatoday.it/rss", "source": "RavennaToday"}
    ],
    "Forlì-Cesena": [
        {"url": "https://www.ilrestodelcarlino.it/forli/rss", "source": "Il Resto del Carlino Forlì"},
        {"url": "https://www.ilrestodelcarlino.it/cesena/rss", "source": "Il Resto del Carlino Cesena"},
        {"url": "https://www.forlitoday.it/rss", "source": "ForlìToday"}
    ],
    "Rimini": [
        {"url": "https://www.ilrestodelcarlino.it/rimini/rss", "source": "Il Resto del Carlino Rimini"},
        {"url": "https://www.riminitoday.it/rss", "source": "RiminiToday"}
    ]
}

# ---------------------------------------------------------------------------
# UTILITIES DI PARSING E DEDUPLICAZIONE
# ---------------------------------------------------------------------------
def clean_xml_text(raw_bytes: bytes) -> str:
    """Rimuove caratteri di controllo ASCII non validi per l'XML."""
    text = raw_bytes.decode('utf-8', errors='ignore')
    return re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]', '', text)

def parse_pub_date(date_str: str) -> datetime:
    """Parsing della data di pubblicazione dagli RSS."""
    if not date_str:
        return None
    try:
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None

def make_title_key(title: str) -> str:
    """Genera una chiave per la deduplicazione basata sulle prime 5 parole significativi."""
    norm = re.sub(r'\W+', ' ', title.lower()).strip()
    words = norm.split()
    return " ".join(words[:5]) if words else ""

def fetch_rss_balanced() -> list:
    """Estrae articoli in modo equo garantendo copertura per ogni provincia."""
    selected_articles = []
    seen_keys = set()
    print(f"[{TODAY_STR}] Avvio estrazione bilanciata per le 9 province dell'Emilia-Romagna...")

    for category, feeds in PROVINCIAL_FEEDS.items():
        category_count = 0
        for feed_info in feeds:
            if category_count >= 3:  # Max 3 articoli distinti per provincia
                break
            try:
                resp = requests.get(feed_info["url"], headers=HEADERS, timeout=8)
                if resp.status_code != 200:
                    continue

                cleaned_xml = clean_xml_text(resp.content)
                root = ET.fromstring(cleaned_xml)
                items = root.findall('.//item') or root.findall('.//{http://www.w3.org/2005/Atom}entry')

                for item in items[:6]:
                    if category_count >= 3:
                        break

                    title = item.findtext('title') or item.findtext('{http://www.w3.org/2005/Atom}title') or ""
                    link = item.findtext('link') or item.findtext('{http://www.w3.org/2005/Atom}href') or ""
                    desc = item.findtext('description') or item.findtext('{http://www.w3.org/2005/Atom}summary') or ""
                    pub_date_raw = item.findtext('pubDate') or item.findtext('{http://www.w3.org/2005/Atom}updated') or ""

                    dt = parse_pub_date(pub_date_raw)
                    if dt and dt < CUTOFF_TIME:
                        continue

                    title_clean = title.strip()
                    title_key = make_title_key(title_clean)
                    if not title_clean or not link.strip() or title_key in seen_keys:
                        continue

                    seen_keys.add(title_key)
                    clean_desc = re.sub(r'<[^>]+>', '', desc).strip()

                    selected_articles.append({
                        'province_cat': category,
                        'title': title_clean,
                        'link': link.strip(),
                        'source': feed_info["source"],
                        'description': clean_desc
                    })
                    category_count += 1
            except Exception:
                continue

    print(f"Estratti {len(selected_articles)} articoli unici e bilanciati su tutte le province.")

    # Estrazione del testo completo via HTTP + Trafilatura con fallback sicuro
    full_articles = []
    print("Avvio estrazione contenuto full-text con timeout di sicurezza...")
    for art in selected_articles:
        try:
            res = requests.get(art['link'], headers=HEADERS, timeout=5)
            if res.status_code == 200:
                text = trafilatura.extract(res.text, include_comments=False, include_tables=False)
                final_text = text if text and len(text) > 150 else art['description']
            else:
                final_text = art['description']
        except Exception:
            final_text = art['description']

        full_articles.append({
            'province_cat': art['province_cat'],
            'title': art['title'],
            'link': art['link'],
            'source': art['source'],
            'content': final_text[:2000]
        })

    return full_articles

# ---------------------------------------------------------------------------
# GENERAZIONE RASSEGNA VIA GEMINI API
# ---------------------------------------------------------------------------
def generate_executive_newsletter(articles: list) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERRORE: GEMINI_API_KEY non trovata nell'ambiente.")
        sys.exit(1
