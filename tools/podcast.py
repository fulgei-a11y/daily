"""
Feed podcast della Rassegna ER (podcast.xml): ogni edizione del mattino e ogni aggiornamento delle 13 e
delle 19 è un episodio. Si ascolta con qualsiasi app di podcast (Apple Podcasts, Pocket Casts,
Podcast Addict, AntennaPod...) aggiungendo l'indirizzo del feed: gli episodi nuovi arrivano da soli.

Uso: python3 tools/podcast.py   (dalla cartella principale del repository)
"""
import datetime as dt
import email.utils
import html
import json
import os
import re
from zoneinfo import ZoneInfo

ROME = ZoneInfo("Europe/Rome")
repo = os.environ.get("GITHUB_REPOSITORY", "fulgei-a11y/rassegna")
owner, name = repo.split("/")
SITE = os.environ.get("SITE_URL", f"https://{owner.lower()}.github.io/{name}/")
GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
MESI = ["", "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
        "settembre", "ottobre", "novembre", "dicembre"]
MAX_EPISODES = 120


def long_date(iso):
    d = dt.date.fromisoformat(iso)
    return f"{GIORNI[d.weekday()]} {d.day} {MESI[d.month]} {d.year}"


def headlines(path, n=6):
    try:
        txt = open(path, encoding="utf-8").read()
    except OSError:
        return []
    out = []
    for t in re.findall(r"<li>\s*<strong>(.*?)</strong>", txt, flags=re.S):
        t = html.unescape(re.sub(r"<[^>]+>", "", t)).strip()
        if t and t not in out:
            out.append(t)
        if len(out) >= n:
            break
    return out


def main():
    try:
        index = {e["date"]: e for e in json.load(open("edizioni/index.json", encoding="utf-8"))}
    except Exception:
        index = {}
    episodes = []
    for f in os.listdir("audio"):
        m = re.match(r"^(\d{4}-\d{2}-\d{2})(?:-(13|19))?\.mp3$", f)
        if not m:
            continue
        date, slot = m.group(1), m.group(2)
        base = f[:-4]
        try:
            meta = json.load(open(f"audio/{base}.json", encoding="utf-8"))
        except Exception:
            meta = {}
        if not meta.get("items"):
            continue   # audio vuoto o senza notizie: non è un episodio
        e = index.get(date, {})
        when = e.get("updated")
        if slot:
            when = next((u.get("updated") for u in e.get("updates", []) if u.get("slot") == slot), None)
        try:
            pub = dt.datetime.fromisoformat(when)
        except Exception:
            pub = dt.datetime.fromisoformat(f"{date}T{'13:20' if slot == '13' else '19:20' if slot == '19' else '06:20'}").replace(tzinfo=ROME)
        title = (f"Aggiornamento delle {slot} · " if slot else "Rassegna del mattino · ") + long_date(date)
        heads = headlines(f"edizioni/{base}.html")
        desc = (f"{meta['items']} notizie dall'Emilia-Romagna. " +
                ("In apertura: " + "; ".join(heads) + "." if heads else "")).strip()
        page = f"{SITE}#{date}"
        episodes.append((pub, f"""    <item>
      <title>{html.escape(title)}</title>
      <description>{html.escape(desc)}</description>
      <link>{page}</link>
      <guid isPermaLink="false">rassegna-er-{base}</guid>
      <pubDate>{email.utils.format_datetime(pub)}</pubDate>
      <enclosure url="{SITE}audio/{f}" length="{os.path.getsize('audio/' + f)}" type="audio/mpeg"/>
      <itunes:duration>{int(meta.get('duration', 0))}</itunes:duration>
      <itunes:episodeType>full</itunes:episodeType>
    </item>"""))
    episodes.sort(key=lambda x: x[0], reverse=True)
    now = email.utils.format_datetime(dt.datetime.now(ROME))
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Rassegna ER</title>
    <link>{SITE}</link>
    <atom:link href="{SITE}podcast.xml" rel="self" type="application/rss+xml"/>
    <language>it</language>
    <description>La rassegna stampa quotidiana dell'Emilia-Romagna letta da Paola: l'edizione del mattino e gli aggiornamenti delle 13 e delle 19, provincia per provincia.</description>
    <itunes:summary>La rassegna stampa quotidiana dell'Emilia-Romagna: ogni mattina e alle 13 e alle 19.</itunes:summary>
    <itunes:author>Rassegna ER</itunes:author>
    <itunes:image href="{SITE}icons/podcast-1400.png"/>
    <image><url>{SITE}icons/podcast-1400.png</url><title>Rassegna ER</title><link>{SITE}</link></image>
    <itunes:category text="News"><itunes:category text="Daily News"/></itunes:category>
    <itunes:explicit>false</itunes:explicit>
    <itunes:type>episodic</itunes:type>
    <lastBuildDate>{now}</lastBuildDate>
{chr(10).join(x[1] for x in episodes[:MAX_EPISODES])}
  </channel>
</rss>
"""
    with open("podcast.xml", "w", encoding="utf-8") as f:
        f.write(xml)
    print(f"✅ podcast.xml: {min(len(episodes), MAX_EPISODES)} episodi")


if __name__ == "__main__":
    main()
