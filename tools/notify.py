"""
Notifiche sul telefono con ntfy (app gratuita per Android e iPhone).

Dopo ogni pubblicazione manda un avviso al "topic" scritto nel segreto NTFY_TOPIC del repository:
- edizione del mattino: numero di notizie e l'inizio di "Il punto del giorno";
- aggiornamenti delle 13 e delle 19: i primi titoli, prima quelli di Bologna;
- In breve: solo se sono arrivate notizie nuove, con priorità bassa (senza suono);
- se qualcosa va storto: un avviso con priorità alta.
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


def main():
    slot = sys.argv[1] if len(sys.argv) > 1 else "mattina"
    esito = sys.argv[2] if len(sys.argv) > 2 else "success"
    link = f"{SITE}#{TODAY}"

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
