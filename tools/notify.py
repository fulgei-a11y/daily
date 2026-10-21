"""
Notifiche sul telefono con ntfy (app gratuita per Android e iPhone).

Dopo ogni pubblicazione manda un avviso al "topic" scritto nel segreto NTFY_TOPIC del repository:
- edizione del mattino: numero di notizie e l'inizio di "Il punto del giorno";
- aggiornamenti delle 13 e delle 19: i primi titoli, prima quelli di Bologna;
- In breve: solo se sono arrivate notizie nuove, con priorità bassa (senza suono);
- se qualcosa va storto: un avviso con priorità alta;
- SENTINELLA: se una notizia appena pubblicata contiene una delle parole scritte nel segreto SENTINELLE
  (separate da virgole, es. «Lepore, Casalecchio, sciopero, Tper»), arriva un avviso a parte, con priorità
  alta, che porta dritto a quella notizia.
Toccando la notifica si apre la rassegna.

Uso: python3 tools/notify.py <slot> <esito del job>     (slot: mattina, 13, 19, ultimora)
Se NTFY_TOPIC non è impostato non fa nulla.
"""
import datetime as dt
import html
import json
import os
import re
import sys
import unicodedata
import urllib.request
from zoneinfo import ZoneInfo

ROME = ZoneInfo("Europe/Rome")
TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
repo = os.environ.get("GITHUB_REPOSITORY", "fulgei-a11y/rassegna")
owner, name = repo.split("/")
SITE = os.environ.get("SITE_URL", f"https://{owner.lower()}.github.io/{name}/")
TODAY = dt.datetime.now(ROME).strftime("%Y-%m-%d")


def text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def titles(fragment, n):
    """Primi titoli, prima quelli della parte Bologna."""
    bo, other, cur = [], [], ""
    for m in re.finditer(r"<h[23]>(.*?)</h[23]>|<li>\s*<strong>(.*?)</strong>", fragment, flags=re.S):
        if m.group(1) is not None:
            cur = text(m.group(1))
            continue
        t = text(m.group(2))
        (bo if cur.lower().startswith("bologna") else other).append(t)
    return (bo + other)[:n]


def send(title, message, priority=3, tags=None, click=None):
    if not TOPIC:
        print("NTFY_TOPIC non impostato: nessuna notifica.")
        return
    payload = {"topic": TOPIC, "title": title[:250], "message": message[:3500] or title,
               "priority": priority, "tags": tags or [], "click": click or SITE}
    req = urllib.request.Request(SERVER, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            print(f"📱 Notifica inviata ({r.status}): {title}")
    except Exception as e:   # una notifica mancata non deve mai far fallire la rassegna
        print(f"⚠️ Notifica non inviata: {e}")


def read(path):
    try:
        return open(path, encoding="utf-8").read()
    except OSError:
        return ""


# ------------------------------------------------------------------ sentinella
def _norm(t):
    t = unicodedata.normalize("NFD", str(t or "").lower())
    return " " + re.sub(r"[^a-z0-9]+", " ", "".join(c for c in t if unicodedata.category(c) != "Mn")).strip() + " "


def parole_sentinella():
    return [p.strip() for p in re.split(r"[,;\n]", os.environ.get("SENTINELLE", "")) if len(p.strip()) >= 2]


def _items(path):
    """Notizie di un file nell'ordine della pagina (stessa logica dell'audio): [(testo, titolo)]."""
    page = read(path)
    if not page:
        return []
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from build_audio import items_from_fragment
    out = []
    for _sec, _sub, node in items_from_fragment(page):
        strong = node.find(["strong", "b"]) if hasattr(node, "find") else None
        out.append((node.get_text(" ", strip=True), strong.get_text(" ", strip=True) if strong else ""))
    return out


def sentinella(slot):
    """Avviso a parte per le notizie nuove che contengono una parola sorvegliata."""
    parole = parole_sentinella()
    if not parole:
        return
    files = [f"edizioni/{TODAY}.html", f"edizioni/{TODAY}-13.html", f"edizioni/{TODAY}-19.html"]
    lists = [_items(f) for f in files]
    # le notizie nuove di questo giro e la loro posizione nella pagina (per il link diretto: #data/numero)
    if slot == "mattina":
        new = [(i, t) for i, t in enumerate(lists[0])]
    elif slot in ("13", "19"):
        k = 1 if slot == "13" else 2
        base = len(lists[0]) + (len(lists[1]) if k == 2 else 0)
        new = [(base + i, t) for i, t in enumerate(lists[k])]
    elif slot == "ultimora":
        try:
            store = json.load(open("ultimora.json", encoding="utf-8"))
        except Exception:
            return
        n = (store.get("last_run") or {}).get("items", 0)
        new = [(None, (text(x.get("html", "")), x.get("title", ""))) for x in store.get("items", [])[:n]]
    else:
        return
    hits = []
    for pos, (testo, titolo) in new:
        t = _norm(testo)
        trovate = [p for p in parole if " " + _norm(p).strip() in t]   # a inizio di parola: «sciop» trova sciopero e scioperi
        if trovate:
            hits.append((pos, titolo or testo[:90], trovate))
    if not hits:
        return
    parole_viste = list(dict.fromkeys(p for _, _, ps in hits for p in ps))
    righe = [f"«{', '.join(ps)}» → {tit}" for _, tit, ps in hits[:8]]
    if len(hits) > 8:
        righe.append(f"… e altre {len(hits) - 8}")
    first = hits[0][0]
    send("🔔 Sentinella: " + ", ".join(parole_viste)[:80], "\n".join(righe), priority=4, tags=["rotating_light"],
         click=f"{SITE}#{TODAY}" + (f"/{first + 1}" if first is not None else ""))


def main():
    slot = sys.argv[1] if len(sys.argv) > 1 else "mattina"
    esito = sys.argv[2] if len(sys.argv) > 2 else "success"
    link = f"{SITE}#{TODAY}"

    if esito == "success":
        try:
            sentinella(slot)
        except Exception as e:   # la sentinella non deve mai bloccare le altre notifiche
            print(f"⚠️ Sentinella: {e}")

    if esito != "success":
        nomi = {"mattina": "l'edizione del mattino", "13": "l'aggiornamento delle 13",
                "19": "l'aggiornamento delle 19", "ultimora": "In breve"}
        send("⚠️ Rassegna: qualcosa non è andato",
             f"Non è stato possibile pubblicare {nomi.get(slot, slot)}. I dettagli sono su GitHub, nella scheda Actions.",
             priority=4, tags=["warning"], click=f"https://github.com/{repo}/actions")
        return

    if slot == "mattina":
        page = read(f"edizioni/{TODAY}.html")
        n = len(re.findall(r"<li\b", page))
        if not n:
            return
        m = re.search(r"Il punto del giorno</h2>\s*<p>(.*?)</p>", page, flags=re.S)
        punto = text(m.group(1)) if m else ""
        if len(punto) > 420:
            punto = punto[:417].rsplit(" ", 1)[0] + "…"
        body = punto or "\n".join("• " + t for t in titles(page, 5))
        send(f"📰 Rassegna del mattino · {n} notizie", body + "\n\nDa leggere o da ascoltare.",
             priority=3, tags=["newspaper"], click=link)

    elif slot in ("13", "19"):
        page = read(f"edizioni/{TODAY}-{slot}.html")
        n = len(re.findall(r"<li\b", page))
        if not n:
            return   # nessuna novità: nessuna notifica
        heads = titles(page, 4)
        send(f"🕐 Aggiornamento delle {slot} · {n} notizie", "\n".join("• " + t for t in heads),
             priority=3, tags=["bell"], click=link)

    elif slot == "ultimora":
        try:
            store = json.load(open("ultimora.json", encoding="utf-8"))
        except Exception:
            return
        new = (store.get("last_run") or {}).get("items", 0)
        if not new:
            return
        items = store.get("items", [])[:new]
        items.sort(key=lambda x: not x.get("bo"))   # prima Bologna
        lines = [("📍 " if x.get("bo") else "• ") + x.get("title", "") for x in items[:5]]
        send(f"⚡ In breve · {new} {'notizia nuova' if new == 1 else 'notizie nuove'}", "\n".join(lines),
             priority=2, tags=["zap"], click=link)


if __name__ == "__main__":
    main()
