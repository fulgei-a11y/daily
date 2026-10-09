"""
Controllo finale dell'aggiornamento quotidiano.

Verifica che l'edizione di oggi esista e sia sensata (abbastanza notizie, scritta da Gemini e non
dall'elenco di riserva, con l'audio). Scrive l'esito in health.md (testo dell'avviso) e restituisce:
  0 = tutto bene, 1 = problema serio (avviso), 2 = solo qualche anomalia minore (avviso leggero).
Il workflow usa l'esito per aprire o chiudere automaticamente una "issue" su GitHub, che arriva per e-mail.
"""
import datetime as dt
import json
import os
import sys
from zoneinfo import ZoneInfo

MIN_ITEMS = int(os.environ.get("MIN_ITEMS", "40"))
TODAY = dt.datetime.now(ZoneInfo("Europe/Rome")).strftime("%Y-%m-%d")


def main():
    job_status = (sys.argv[1] if len(sys.argv) > 1 else "success").lower()
    serious, minor = [], []

    if job_status not in ("success", ""):
        serious.append(f"Il workflow si è concluso con stato **{job_status}**: uno dei passaggi è fallito.")

    html_path = f"edizioni/{TODAY}.html"
    if not os.path.exists(html_path):
        serious.append(f"L'edizione di oggi (`{html_path}`) non è stata creata.")

    try:
        with open("stato.json", encoding="utf-8") as f:
            st = json.load(f)
    except Exception:
        st = {}
    if st.get("date") != TODAY:
        serious.append("Il file `stato.json` non è di oggi: lo script della rassegna non è arrivato in fondo.")
    else:
        if st.get("fallback"):
            serious.append("Gemini non ha risposto: oggi è stato pubblicato solo l'elenco dei titoli "
                           "(controlla la chiave `GEMINI_API_KEY` e la quota del piano).")
        if st.get("items", 0) < MIN_ITEMS:
            serious.append(f"Edizione troppo povera: {st.get('items', 0)} notizie (minimo atteso {MIN_ITEMS}).")
        ko = [f for f in st.get("feeds", []) if f.get("status") != "ok" or not f.get("items")]
        if st.get("feeds_total") and len(ko) > st["feeds_total"] / 2:
            serious.append(f"Più di metà delle fonti non ha risposto ({len(ko)} su {st['feeds_total']}).")
        elif len(ko) >= 6:
            minor.append(f"{len(ko)} fonti su {st.get('feeds_total')} non hanno fornito notizie.")

    if os.path.exists(html_path) and not os.path.exists(f"audio/{TODAY}.mp3"):
        serious.append("L'audio MP3 di oggi non è stato generato (la rassegna scritta è comunque online).")

    lines = [f"Controllo automatico dell'edizione del **{TODAY}**.", ""]
    for p in serious:
        lines.append(f"- ❌ {p}")
    for p in minor:
        lines.append(f"- ⚠️ {p}")
    if st.get("feeds"):
        bad = [f for f in st["feeds"] if f.get("status") != "ok" or not f.get("items")]
        if bad:
            lines += ["", "<details><summary>Fonti senza notizie oggi</summary>", ""]
            lines += [f"- {f['name']}{' (' + f['prov'] + ')' if f.get('prov') else ''}: {f['status']}" for f in bad]
            lines += ["", "</details>"]
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run = os.environ.get("GITHUB_RUN_ID", "")
    if repo and run:
        lines += ["", f"Dettagli del lavoro: https://github.com/{repo}/actions/runs/{run}"]
    lines += ["", "Per riprovare a mano: scheda **Actions** → *Rassegna Stampa Automatica* → **Run workflow**.",
              "Questo avviso si chiude da solo al primo aggiornamento riuscito."]
    with open("health.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("\n".join(lines))
    sys.exit(1 if serious else 2 if minor else 0)


if __name__ == "__main__":
    main()
