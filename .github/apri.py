#!/usr/bin/env python3
"""Decifra dati.bin nel tar.gz dei dati.

  python3 .github/apri.py dati.bin uscita.tgz

Prova le password in PASSWORD_NUOVA (se c'è, durante un cambio password) e poi in PASSWORD_DATI;
scrive sullo standard output quale ha funzionato ("nuova" o "attuale").

Formati accettati:
- "DAT2" + sale (16) + vettore (12) + AES-256-GCM (PBKDF2-SHA256, 600.000 passaggi): ogni modifica
  al file viene rilevata;
- quello vecchio di "openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -md sha256" ("Salted__" + sale).
"""
import hashlib
import os
import sys

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def nuovo(blob, pw):
    salt, iv = blob[4:20], blob[20:32]
    key = hashlib.pbkdf2_hmac("sha256", pw, salt, 600_000, dklen=32)
    try:
        return AESGCM(key).decrypt(iv, blob[32:], b"DAT2")
    except Exception:
        return None


def vecchio(blob, pw):
    raw = hashlib.pbkdf2_hmac("sha256", pw, blob[8:16], 200_000, dklen=48)
    try:
        d = Cipher(algorithms.AES(raw[:32]), modes.CBC(raw[32:])).decryptor()
        data = d.update(blob[16:]) + d.finalize()
        u = padding.PKCS7(128).unpadder()
        data = u.update(data) + u.finalize()
    except Exception:
        return None
    return data if data[:2] == b"\x1f\x8b" else None


def main():
    src, out = sys.argv[1], sys.argv[2]
    with open(src, "rb") as f:
        blob = f.read()
    if blob[:4] == b"DAT2":
        fn = nuovo
    elif blob[:8] == b"Salted__":
        fn = vecchio
    else:
        sys.exit("formato sconosciuto")
    for name, var in (("nuova", "PASSWORD_NUOVA"), ("attuale", "PASSWORD_DATI")):
        pw = os.environ.get(var, "")
        if not pw:
            continue
        data = fn(blob, pw.encode("utf-8"))
        if data is not None:
            with open(out, "wb") as f:
                f.write(data)
            print(name)
            return
    sys.exit("decifratura non riuscita")


if __name__ == "__main__":
    main()
