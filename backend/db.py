"""SQLite verilənlər bazası: istifadəçilər, izlənən videolar, lüğət, terminlər, tərcümə keşi.

Hər funksiya öz bağlantısını açır (FastAPI və Streamlit eyni anda istifadə edə bilsin).
Şifrələr PBKDF2-SHA256 + salt ilə saxlanır; uzantı üçün ayrıca təsadüfi token var.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta

from backend import config

USERNAME_RE = re.compile(r"^[a-z0-9_-]{3,20}$")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
ITER = 200_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  username TEXT PRIMARY KEY, name TEXT, email TEXT, salt TEXT, hash TEXT, token TEXT UNIQUE,
  lang TEXT DEFAULT 'az', voice TEXT DEFAULT 'nova', remind_hour INTEGER DEFAULT 8, remind_on INTEGER DEFAULT 1,
  created TEXT);
CREATE TABLE IF NOT EXISTS videos (
  id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, video_id TEXT, title TEXT, lang TEXT, mode TEXT,
  segments INTEGER, seconds REAL, topic TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS vocab (
  id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, word TEXT, lemma TEXT, translation TEXT, pos TEXT,
  sentence TEXT, sentence_tr TEXT, example TEXT, video_id TEXT, title TEXT, t REAL, lang TEXT,
  box INTEGER DEFAULT 1, due TEXT, reviews INTEGER DEFAULT 0, correct INTEGER DEFAULT 0, created TEXT,
  UNIQUE(username, lemma, lang));
CREATE TABLE IF NOT EXISTS glossary (
  username TEXT, term TEXT, translation TEXT, PRIMARY KEY (username, term));
CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT, created TEXT);
"""


@contextmanager
def conn():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(config.DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with conn() as c:
        c.executescript(SCHEMA)


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ------------------------------------------------------------------ istifadəçilər
def _hash(pw: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, ITER).hex()


def register(username: str, password: str, name: str, email: str, remind_hour: int = 8,
             lang: str = "az") -> tuple[bool, str]:
    u = (username or "").strip().lower()
    email = (email or "").strip()
    if not USERNAME_RE.match(u):
        return False, "İstifadəçi adı 3–20 simvol olmalıdır: kiçik latın hərfləri, rəqəm, _ və ya -."
    if len(password or "") < 6:
        return False, "Şifrə ən azı 6 simvol olmalıdır."
    if not EMAIL_RE.match(email):
        return False, "Email düzgün deyil (məsələn: ad@gmail.com)."
    salt = os.urandom(16)
    try:
        with conn() as c:
            c.execute("INSERT INTO users (username, name, email, salt, hash, token, lang, remind_hour, created) "
                      "VALUES (?,?,?,?,?,?,?,?,?)",
                      (u, (name or u).strip()[:40], email, salt.hex(), _hash(password, salt),
                       "dl_" + secrets.token_urlsafe(24), lang, int(remind_hour), now()))
    except sqlite3.IntegrityError:
        return False, "Bu istifadəçi adı artıq var."
    return True, "Hesab yaradıldı."


def login(username: str, password: str) -> dict | None:
    u = (username or "").strip().lower()
    with conn() as c:
        r = c.execute("SELECT * FROM users WHERE username=?", (u,)).fetchone()
    if not r:
        _hash(password or "", b"equalize-timing!")
        return None
    return dict(r) if hmac.compare_digest(_hash(password or "", bytes.fromhex(r["salt"])), r["hash"]) else None


def user_by_token(token: str) -> dict | None:
    if not token:
        return None
    with conn() as c:
        r = c.execute("SELECT * FROM users WHERE token=?", (token,)).fetchone()
    return dict(r) if r else None


def get_user(username: str) -> dict | None:
    with conn() as c:
        r = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    return dict(r) if r else None


def update_user(username: str, **fields) -> dict:
    allowed = {k: v for k, v in fields.items() if k in ("name", "email", "lang", "voice", "remind_hour", "remind_on")}
    if "email" in allowed and allowed["email"] and not EMAIL_RE.match(allowed["email"]):
        raise ValueError("Email düzgün deyil.")
    if allowed:
        with conn() as c:
            c.execute(f"UPDATE users SET {', '.join(k + '=?' for k in allowed)} WHERE username=?",
                      (*allowed.values(), username))
    return get_user(username)


def new_token(username: str) -> str:
    t = "dl_" + secrets.token_urlsafe(24)
    with conn() as c:
        c.execute("UPDATE users SET token=? WHERE username=?", (t, username))
    return t


def public_profile(u: dict) -> dict:
    return {k: u.get(k) for k in ("username", "name", "email", "lang", "voice", "remind_hour", "remind_on")}


# ------------------------------------------------------------------ keş
def cache_get(key: str):
    with conn() as c:
        r = c.execute("SELECT value FROM cache WHERE key=?", (key,)).fetchone()
    return json.loads(r["value"]) if r else None


def cache_set(key: str, value):
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO cache (key, value, created) VALUES (?,?,?)",
                  (key, json.dumps(value, ensure_ascii=False), now()))


# ------------------------------------------------------------------ videolar
def add_video(username: str, video_id: str, title: str, lang: str, mode: str, segments: list, topic: str):
    secs = round(segments[-1]["e"] - segments[0]["s"], 1) if segments else 0
    with conn() as c:
        last = c.execute("SELECT id FROM videos WHERE username=? AND video_id=? AND lang=? AND mode=? "
                         "AND created > ?", (username, video_id, lang, mode,
                                             (datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"))
                         ).fetchone()
        if last:
            return
        c.execute("INSERT INTO videos (username, video_id, title, lang, mode, segments, seconds, topic, created) "
                  "VALUES (?,?,?,?,?,?,?,?,?)", (username, video_id, title, lang, mode, len(segments), secs, topic, now()))


def videos(username: str, limit: int = 200) -> list[dict]:
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM videos WHERE username=? ORDER BY id DESC LIMIT ?",
                                           (username, limit))]


# ------------------------------------------------------------------ lüğət (Leitner qutuları: 1 → 5)
BOX_DAYS = {1: 0, 2: 1, 3: 3, 4: 7, 5: 16}


def add_vocab(username: str, item: dict) -> dict:
    with conn() as c:
        c.execute("""INSERT INTO vocab (username, word, lemma, translation, pos, sentence, sentence_tr, example,
                     video_id, title, t, lang, box, due, created) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)
                     ON CONFLICT(username, lemma, lang) DO UPDATE SET sentence=excluded.sentence,
                     sentence_tr=excluded.sentence_tr, video_id=excluded.video_id, title=excluded.title, t=excluded.t""",
                  (username, item["word"], item["lemma"], item["translation"], item.get("pos", ""),
                   item.get("sentence", ""), item.get("sentence_tr", ""), item.get("example", ""),
                   item.get("video_id", ""), item.get("title", ""), item.get("t", 0), item.get("lang", "az"),
                   datetime.now().strftime("%Y-%m-%d"), now()))
        r = c.execute("SELECT * FROM vocab WHERE username=? AND lemma=? AND lang=?",
                      (username, item["lemma"], item.get("lang", "az"))).fetchone()
    return dict(r)


def vocab(username: str) -> list[dict]:
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM vocab WHERE username=? ORDER BY id DESC", (username,))]


def due_vocab(username: str, limit: int = 20) -> list[dict]:
    today = datetime.now().strftime("%Y-%m-%d")
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM vocab WHERE username=? AND due<=? ORDER BY box, due LIMIT ?",
                                           (username, today, limit))]


def review(vocab_id: int, username: str, ok: bool) -> dict:
    with conn() as c:
        r = c.execute("SELECT box, reviews, correct FROM vocab WHERE id=? AND username=?", (vocab_id, username)).fetchone()
        if not r:
            return {}
        box = min(5, r["box"] + 1) if ok else 1
        due = (datetime.now() + timedelta(days=BOX_DAYS[box])).strftime("%Y-%m-%d")
        c.execute("UPDATE vocab SET box=?, due=?, reviews=?, correct=? WHERE id=?",
                  (box, due, r["reviews"] + 1, r["correct"] + int(ok), vocab_id))
    return {"box": box, "due": due}


def delete_vocab(vocab_id: int, username: str):
    with conn() as c:
        c.execute("DELETE FROM vocab WHERE id=? AND username=?", (vocab_id, username))


# ------------------------------------------------------------------ terminlər
def glossary(username: str) -> dict[str, str]:
    with conn() as c:
        return {r["term"]: r["translation"] for r in
                c.execute("SELECT term, translation FROM glossary WHERE username=? ORDER BY term", (username,))}


def set_term(username: str, term: str, translation: str):
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO glossary (username, term, translation) VALUES (?,?,?)",
                  (username, term.strip(), translation.strip()))


def delete_term(username: str, term: str):
    with conn() as c:
        c.execute("DELETE FROM glossary WHERE username=? AND term=?", (username, term))


def stats(username: str) -> dict:
    with conn() as c:
        v = c.execute("SELECT count(*) n, coalesce(sum(seconds),0) s FROM videos WHERE username=?", (username,)).fetchone()
        w = c.execute("SELECT count(*) n, coalesce(sum(box>=4),0) m FROM vocab WHERE username=?", (username,)).fetchone()
        days = [r[0] for r in c.execute(
            "SELECT DISTINCT substr(created,1,10) d FROM (SELECT created FROM videos WHERE username=? "
            "UNION ALL SELECT created FROM vocab WHERE username=?) ORDER BY d DESC", (username, username))]
    streak, d = 0, datetime.now().date()
    for day in days:
        if day == d.isoformat():
            streak += 1
            d -= timedelta(days=1)
        elif streak == 0 and day == (d - timedelta(days=1)).isoformat():
            streak, d = 1, d - timedelta(days=2)
        else:
            break
    return {"videos": v["n"], "minutes": round(v["s"] / 60), "words": w["n"], "mastered": w["m"], "streak": streak}
