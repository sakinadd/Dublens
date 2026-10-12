"""DubLens parametrləri. Hamısı .env-dən oxunur; başqa fayllar os.getenv yox, buradan istifadə edir."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_FALLBACK_MODEL = os.getenv("LLM_FALLBACK_MODEL", "gpt-4.1-mini")
TTS_MODEL = os.getenv("TTS_MODEL", "gpt-4o-mini-tts")
TTS_FALLBACK_MODEL = os.getenv("TTS_FALLBACK_MODEL", "tts-1")
# ElevenLabs (varsa əsas səs mənbəyi): az → v3, digər dillər → flash v2.5
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "").strip()
ELEVEN_MODEL_AZ = os.getenv("ELEVEN_MODEL_AZ", "eleven_v3")
ELEVEN_MODEL_FAST = os.getenv("ELEVEN_MODEL_FAST", "eleven_flash_v2_5")
# ElevenLabs eyni anda neçə sorğu qəbul edir: pulsuz plan 2, Starter 3, Creator 5
ELEVEN_CONCURRENCY = int(os.getenv("ELEVEN_CONCURRENCY", "2"))

DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data"))
DB_PATH = DATA_DIR / "dublens.db"
TTS_DIR = DATA_DIR / "tts"

# n8n: bütün hadisələr (profil, izlənən video, lüğətə söz) bir webhook-a gedir — DubLens 01
N8N_EVENT_WEBHOOK = os.getenv("N8N_EVENT_WEBHOOK", "http://localhost:5678/webhook/dublens/event")
# Serverdə qeydiyyat yalnız bu kodla (boşdursa hər kəs qeydiyyatdan keçə bilər)
INVITE_CODE = os.getenv("INVITE_CODE", "").strip()
# Bir istifadəçi gündə neçə video yükləyə bilər (API xərcini qorumaq üçün)
STUDIO_DAILY_LIMIT = int(os.getenv("STUDIO_DAILY_LIMIT", "10"))

# Panel API-ni harada yoxlasın (Docker-də: http://api:8000)
API_URL = os.getenv("API_URL", "http://localhost:8000")

# Dublyaj üçün: Azərbaycan dilində rahat danışıq sürəti (simvol/saniyə). Bundan uzun cümlə qısaldılır.
CHARS_PER_SEC = float(os.getenv("CHARS_PER_SEC", "13"))
TRANSLATE_BATCH = 12          # bir LLM çağırışında neçə cümlə (kiçik paket = ilk nəticə tez gəlir)
MAX_CONCURRENCY = 6           # paralel LLM çağırışları

LANGS = {"az": "Azerbaijani", "tr": "Turkish", "ru": "Russian", "en": "English"}
LANG_NAMES_AZ = {"az": "Azərbaycan dili", "tr": "Türk dili", "ru": "Rus dili", "en": "İngilis dili"}
TTS_WORKERS = 10              # eyni anda neçə cümlə səsləndirilir
VOICES = ["nova", "onyx", "alloy", "shimmer", "echo", "fable", "coral", "sage",
          "el_sarah", "el_laura", "el_alice", "el_george", "el_brian", "el_charlie"]
