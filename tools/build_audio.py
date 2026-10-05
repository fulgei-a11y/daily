#!/usr/bin/env python3
"""Genera l'MP3 di un'edizione della "Rassegna ER" con la voce italiana Paola (sherpa-onnx, offline).

Uso:  python3 build_audio.py --html AAAA-MM-GG.html --date AAAA-MM-GG --out ./audio_out
Input: il frammento HTML dell'edizione (lo stesso che sta dentro <template id="doc"> dell'app).
Produce: out/AAAA-MM-GG.mp3 e out/audio_meta.json
  audio_meta.json = {"date", "audio": "audio/AAAA-MM-GG.mp3", "duration": sec, "items": N, "segments": [{"i": indice notizia, "t": sec}]}
Gli indici "i" corrispondono, nello stesso ordine, alle notizie che l'app mostra (stessa logica di lettura del frammento),
così la pagina evidenzia la notizia in ascolto e un tocco su una notizia salta al punto giusto dell'audio.
"""
import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import wave

SHERPA_VER = "1.12.14"
SHERPA_URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/v{SHERPA_VER}/sherpa-onnx-v{SHERPA_VER}-linux-x64-shared.tar.bz2"
VOICE_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-it_IT-paola-medium.tar.bz2"
CACHE = os.path.expanduser("~/.cache/rassegna-tts")
MESI = [
    '', 'gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno',
    'luglio', 'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre'
]
GIORNI = ['lunedì', 'martedì', 'mercoledì', 'giovedì', 'venerdì', 'sabato', 'domenica']


def ensure_libs():
    try:
        import bs4  # noqa
    except ImportError:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "--break-system-packages", "beautifulsoup4"],
            check=True
        )


def ensure_engine():
    root = os.path.join(CACHE, f"sherpa-onnx-v{SHERPA_VER}-linux-x64-shared")
    vdir = os.path.join(CACHE, "vits-piper-it_IT-paola-medium")
    os.makedirs(CACHE, exist_ok=True)
    for url, check in ((SHERPA_URL, root), (VOICE_URL, vdir)):
        if not os.path.isdir(check):
            arc = os.path.join(CACHE, os.path.basename(url))
            subprocess.run(["curl", "-sSL", "--fail", "--retry", "3", "-o", arc, url], check=True)
            with tarfile.open(arc) as t:
                t.extractall(CACHE)
    return root, vdir


def normalize(s):
    s = re.sub(r"\s+", " ", s)
    s = re.sub(
        r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b",
        lambda m: f"{int(m[1])} {MESI[int(m[2])]} {m[3]}" if 1 <= int(m[2]) <= 12 else m[0],
        s
    )
    s = re.sub(
        r"\b(\d{1,2})/(\d{1,2})\b",
        lambda m: f"{int(m[1])} {MESI[int(m[2])]}" if 1 <= int(m[2]) <= 12 and int(m[1]) <= 31 else m[0],
        s
    )
    s = re.sub(r"€\s?/\s?l\b", " euro al litro", s)
    s = re.sub(r"€\s?/\s?kg\b", " euro al chilo", s)
    s = re.sub(r"€\s?/\s?MWh\b", " euro al megawattora", s)
    s = s.replace("€", " euro").replace("m²", " metri quadri").replace("%", " per cento")
    s = re.sub(r"(^|[\s(:])\+(\d)", r"\1più \2", s)
    s = re.sub(r"(^|[\s(:])-(\d)", r"\1meno \2", s)
    s = re.sub(r"\s?\((BO|MO|RE|PR|PC|FE|RA|FC|RN)\)", "", s)
    s = re.sub(r"\bE-R\b", "Emilia-Romagna", s)
    s = re.sub(r"\bpm\b", "pubblico ministero", s)
    s = re.sub(r"\s[—–]\s", ". ", s).replace("—", ", ").replace("·", ",").replace("›", ",").replace("×", " per ")
    s = re.sub(r"[\"«»“”*_#]", "", s)
    s = re.sub(r"\(\s*[,;\s]*\)", "", s)
    s = re.sub(r"\s+([,.;:])", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


def items_from_fragment(html):
    """Esegue il parsing dell'HTML estraendo h2, h3, p e li anche da documenti HTML completi."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    
    # Se il documento contiene un body o un main, usalo come radice di partenza
    root = soup.find("main") or soup.find("body") or soup
    
    out, st = [], {"sec": None, "sub": None}

    def add(node):
        if st["sec"] is None:
            st["sec"] = "Rassegna"
        out.append((st["sec"], st["sub"], node))

    def walk(nodes):
        for n in nodes:
            if not getattr(n, "name", None):
                continue
            t = n.name
            if t == "h2":
                st["sec"], st["sub"] = n.get_text().strip(), None
            elif t == "h3":
                st["sub"] = n.get_text().strip()
            elif t == "p":
                if "note" in (n.get("class") or []):
                    continue
                add(n)
            elif t in ("ol", "ul"):
                for li in n.find_all("li", recursive=False):
                    add(li)
            else:
                # Entra ricorsivamente in qualsiasi altro contenitore (html, body, main, div, section, ecc.)
                if hasattr(n, "children"):
                    walk(n.children)

    walk(root.children)
    return out


def spoken(prev, cur):
    sec, sub, node = cur
    from bs4 import BeautifulSoup
    c = BeautifulSoup(str(node), "html.parser")
    for a in c.find_all("a"):
        a.decompose()
    s = c.get_text(" ")
    s = re.sub(r"\s*(Fonte unica|Fonti|Fonte|Notizia da una sola fonte)\s*:[\s,·;.()]*$", "", s, flags=re.I)
    s = re.sub(r"(Fonte unica|Fonti|Fonte)\s*:\s*[,;.]?", "", s, flags=re.I)
    s = normalize(s)
    if s and not re.search(r"[.!?]$", s):
        s += "."
    pre = ""
    if prev is None or prev[0] != sec:
        pre += sec + ". "
    if sub and (prev is None or prev[1] != sub or prev[0] != sec):
        pre += sub + ". "
    return normalize(pre) + (" " if pre else "") + s


def split_long(text, limit=600):
    """Frasi lunghe in pezzi, per una sintesi più stabile."""
    parts, buf = [], ""
    for p in re.split(r"(?<=[.!?;])\s+", text):
        if len(buf) + len(p) + 1 > limit and buf:
            parts.append(buf)
            buf = p
        else:
            buf = (buf + " " + p).strip()
    if buf:
        parts.append(buf)
    return parts


def synth_all(jobs, root, vdir, workers=3):
    from concurrent.futures import ThreadPoolExecutor
    exe = os.path.join(root, "bin", "sherpa-onnx-offline-tts")
    env = dict(os.environ, LD_LIBRARY_PATH=os.path.join(root, "lib"))
    base = [
        exe,
        f"--vits-model={vdir}/it_IT-paola-medium.onnx",
        f"--vits-tokens={vdir}/tokens.txt",
        f"--vits-data-dir={vdir}/espeak-ng-data",
        "--num-threads=1",
        "--vits-length-scale=1.0"
    ]

    def one(job):
        text, out = job
        for _ in range(2):
            r = subprocess.run(
                base + [f"--output-filename={out}", text],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            if r.returncode == 0 and os.path.exists(out):
                return True
        return False

    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(one, jobs))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    ensure_libs()
    root, vdir = ensure_engine()
    os.makedirs(a.out, exist_ok=True)

    with open(a.html, encoding="utf-8") as f:
        html_content = f.read()

    its = items_from_fragment(html_content)
    y, m, d = map(int, a.date.split("-"))
    wd = GIORNI[datetime.date(y, m, d).weekday()]
    intro = f"Rassegna dell'Emilia-Romagna di {wd} {d} {MESI[m]} {y}."
    texts = [spoken(its[i - 1] if i else None, its[i]) for i in range(len(its))]

    tmp = tempfile.mkdtemp()
    jobs, owner = [(intro, os.path.join(tmp, "intro.wav"))], [-1]
    for i, t in enumerate(texts):
        for k, piece in enumerate(split_long(t)):
            jobs.append((piece, os.path.join(tmp, f"{i:04d}_{k:02d}.wav")))
            owner.append(i)

    ok = synth_all(jobs, root, vdir)
    if sum(ok) < len(jobs) * 0.95:
        sys.exit(f"Sintesi fallita per {len(jobs) - sum(ok)} pezzi su {len(jobs)}")

    rate, segs, t, last = None, [], 0.0, None
    full = os.path.join(tmp, "full.wav")

    with wave.open(full, "wb") as w:
        for (txt, p), i in zip(jobs, owner):
            if not os.path.exists(p):
                continue
            with wave.open(p, "rb") as r:
                if rate is None:
                    rate = r.getframerate()
                    w.setnchannels(1)
                    w.setsampwidth(r.getsampwidth())
                    w.setframerate(rate)
                if i != last and i >= 0:
                    newsec = i == 0 or its[i][0] != its[i - 1][0]
                    gap = 0.9 if newsec else 0.35
                    w.writeframes(b"\x00\x00" * int(rate * gap))
                    t += gap
                    segs.append({"i": i, "t": round(t, 2)})
                    last = i
                w.writeframes(r.readframes(r.getnframes()))
                t += r.getnframes() / rate
                w.writeframes(b"\x00\x00" * int(rate * 0.15))
                t += 0.15

    mp3 = os.path.join(a.out, f"{a.date}.mp3")
    for br in ("40k", "32k", "24k"):
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-i", full, "-ac", "1", "-ar", "22050",
            "-codec:a", "libmp3lame", "-b:a", br, mp3
        ], check=True)
        if os.path.getsize(mp3) < 14 * 1024 * 1024:
            break

    meta = {
        "date": a.date,
        "audio": f"audio/{a.date}.mp3",
        "duration": round(t, 1),
        "items": len(its),
        "segments": segs
    }

    meta_path = os.path.join(a.out, "audio_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)

    shutil.copy(meta_path, os.path.join(a.out, f"{a.date}.json"))
    shutil.rmtree(tmp, ignore_errors=True)

    print(f"OK {mp3} {os.path.getsize(mp3) // 1024} KB, {t / 60:.1f} min, {len(segs)} notizie")


if __name__ == "__main__":
    main()
