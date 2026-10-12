"""Sistem vəziyyəti: DubLens-in asılı olduğu hər xidmət ayrıca yoxlanılır (açarlar göstərilmir).

Hər yoxlama {"name", "ok", "detail", "ms"} qaytarır; biri yıxılsa da qalanları işləyir.
"""
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import requests

from backend import config, db


def _timed(fn):
    t = time.time()
    try:
        ok, detail = fn()
    except requests.exceptions.Timeout:
        ok, detail = False, "cavab gecikir (vaxt aşımı)"
    except requests.exceptions.ConnectionError as e:
        host = getattr(getattr(e, "request", None), "url", "") or ""
        ok, detail = False, f"qoşulmaq olmur: {urlsplit(host).netloc} (işləyir? internet var?)"
    except Exception as e:
        ok, detail = False, str(e)[:160]
    return ok, detail, int((time.time() - t) * 1000)


def _openai():
    if not config.OPENAI_API_KEY:
        return False, ".env-də OPENAI_API_KEY yoxdur"
    r = requests.get(f"https://api.openai.com/v1/models/{config.LLM_MODEL}",
                     headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"}, timeout=15)
    if r.status_code == 200:
        return True, f"{config.LLM_MODEL} · tərcümə, Whisper, ehtiyat səs"
    return False, f"HTTP {r.status_code}: {r.text[:120]}"


def _elevenlabs():
    if not config.ELEVENLABS_API_KEY:
        return True, "açar yoxdur — OpenAI səsi işləyir"
    r = requests.get("https://api.elevenlabs.io/v1/user/subscription",
                     headers={"xi-api-key": config.ELEVENLABS_API_KEY}, timeout=15)
    if r.status_code == 200:
        d = r.json()
        left = (d.get("character_limit") or 0) - (d.get("character_count") or 0)
        return left > 300, f"plan: {d.get('tier')} · qalan: {left:,} simvol".replace(",", " ")
    if r.status_code == 401:
        return False, "açarın icazələri çatmır (Text to Speech, User: read)"
    return False, f"HTTP {r.status_code}"


def _n8n():
    url = config.N8N_EVENT_WEBHOOK
    if not url:
        return False, "N8N_EVENT_WEBHOOK boşdur"
    p = urlsplit(url)
    r = requests.get(f"{p.scheme}://{p.netloc}/healthz", timeout=8)
    if r.status_code == 200:
        return True, f"{p.netloc} · hadisələr, səhər kartları, MCP"
    return False, f"{p.netloc} cavab verdi: HTTP {r.status_code}"


def _api():
    r = requests.get(f"{config.API_URL.rstrip('/')}/health", timeout=6)
    d = r.json()
    return r.status_code == 200, f"{config.API_URL} · səs: {d.get('tts')}"


def _ffmpeg():
    from backend import studio
    exe = studio.ffmpeg_bin()
    out = subprocess.run([exe, "-version"], capture_output=True, text=True).stdout.split("\n")[0]
    return True, out.split(" Copyright")[0]


def _db():
    with db.conn() as c:
        users = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        videos = c.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
        words = c.execute("SELECT COUNT(*) FROM vocab").fetchone()[0]
    return True, f"{users} istifadəçi · {videos} video · {words} söz"


CHECKS = [("OpenAI", _openai), ("ElevenLabs", _elevenlabs), ("n8n", _n8n), ("DubLens API", _api),
          ("ffmpeg", _ffmpeg), ("Verilənlər bazası", _db)]


def run() -> list[dict]:
    with ThreadPoolExecutor(len(CHECKS)) as pool:
        res = list(pool.map(lambda c: (c[0], *_timed(c[1])), CHECKS))
    return [{"name": n, "ok": ok, "detail": d, "ms": ms} for n, ok, d, ms in res]
