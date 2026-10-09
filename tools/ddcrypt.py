#!/usr/bin/env python3
"""Encrypt / decrypt the site's private files.

Format of every .enc file: b"DD1" + 12-byte nonce + AES-256-GCM ciphertext (tag appended).
Key = PBKDF2-HMAC-SHA256(password, salt, iterations) with salt/iterations in data/salt.json.
The browser app derives the same key with WebCrypto.

Files only the generator needs and that must never be guessable (the textbook text) use
b"DD2" + nonce + AES-256-GCM with a random 256-bit key given as base64 in env DD_SRCKEY.

Usage (password from env DD_PASS, textbook key from env DD_SRCKEY):
  python3 tools/ddcrypt.py enc <in> <out>
  python3 tools/ddcrypt.py dec <in> <out>
  python3 tools/ddcrypt.py encsrc <in> <out>  # DD2, random key
  python3 tools/ddcrypt.py unpack            # secure/*.enc -> work/src/*.json (+ work/src/tb/chNN.txt)
"""
import base64, json, os, sys
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

ROOT = Path(__file__).resolve().parent.parent
MAGIC = b"DD1"
MAGIC2 = b"DD2"
_KEY = None


def src_key():
    k = os.environ.get("DD_SRCKEY", "")
    if not k:
        return None
    return base64.urlsafe_b64decode(k + "=" * (-len(k) % 4))


def key():
    global _KEY
    if _KEY is None:
        pw = os.environ.get("DD_PASS")
        if not pw:
            sys.exit("DD_PASS is not set")
        meta = json.loads((ROOT / "data" / "salt.json").read_text())
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=base64.b64decode(meta["salt"]), iterations=meta["iter"])
        _KEY = kdf.derive(pw.encode())
    return _KEY


def enc_bytes(data: bytes) -> bytes:
    nonce = os.urandom(12)
    return MAGIC + nonce + AESGCM(key()).encrypt(nonce, data, None)


def dec_bytes(blob: bytes) -> bytes:
    if blob[:3] == MAGIC2:
        k = src_key()
        if not k:
            raise PermissionError("DD_SRCKEY is not set")
        return AESGCM(k).decrypt(blob[3:15], blob[15:], None)
    if blob[:3] != MAGIC:
        raise ValueError("not an encrypted file")
    return AESGCM(key()).decrypt(blob[3:15], blob[15:], None)


def enc_src(data: bytes) -> bytes:
    k = src_key()
    if not k:
        sys.exit("DD_SRCKEY is not set")
    nonce = os.urandom(12)
    return MAGIC2 + nonce + AESGCM(k).encrypt(nonce, data, None)


def write_tb(tb, out):
    """Textbook chapters as plain text files the writing/review agents can grep."""
    d = out / "tb"
    d.mkdir(parents=True, exist_ok=True)
    for c, wins in tb["ch"].items():
        body = "\n\n".join(f"[{w['id']} · 피부과학 7판 p.{w['p'][0]}{'–' + str(w['p'][1]) if w['p'][1] != w['p'][0] else ''}{' · ' + w['h'] if w['h'] else ''}]\n{w['text']}" for w in wins)
        (d / f"ch{int(c):02d}.txt").write_text(body)


def enc_json(obj, path):
    Path(path).write_bytes(enc_bytes(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()))


def dec_json(path):
    return json.loads(dec_bytes(Path(path).read_bytes()).decode())


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "enc":
        Path(sys.argv[3]).write_bytes(enc_bytes(Path(sys.argv[2]).read_bytes()))
    elif cmd == "dec":
        Path(sys.argv[3]).write_bytes(dec_bytes(Path(sys.argv[2]).read_bytes()))
    elif cmd == "encsrc":
        Path(sys.argv[3]).write_bytes(enc_src(Path(sys.argv[2]).read_bytes()))
    elif cmd == "unpack":
        out = ROOT / "work" / "src"
        out.mkdir(parents=True, exist_ok=True)
        for f in sorted((ROOT / "secure").glob("*.enc")):
            try:
                (out / (f.stem + ".json")).write_bytes(dec_bytes(f.read_bytes()))
                print("unpacked", f.name)
            except PermissionError:
                print("SKIPPED", f.name, "— DD_SRCKEY is not set (questions will be made without the textbook text)")
        if (out / "textbook.json").exists():
            write_tb(json.loads((out / "textbook.json").read_text()), out)
            print("textbook chapters -> work/src/tb/")
    else:
        sys.exit(__doc__)
