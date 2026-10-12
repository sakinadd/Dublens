"""Dublyaj səsi. Hər cümlə ayrıca mp3 olur və keşlənir (eyni cümlə ikinci dəfə pul xərcləmir).

Əsas: ElevenLabs (ELEVENLABS_API_KEY varsa)
  - Azərbaycan dili → eleven_v3 (az-ı yalnız bu model dəstəkləyir, ən təbii səs)
  - türk / rus / ingilis → uzantıda eleven_flash_v2_5 (sürət), video studiyada eleven_multilingual_v2 (keyfiyyət)
  - qonşu cümlələr previous_text / next_text kimi verilir → intonasiya cümlədən cümləyə axıcı keçir
  - mətn vaxtına sığmırsa, səs bir az sürətli yaradılır (speed ≤ 1.15)
Ehtiyat: OpenAI (gpt-4o-mini-tts → tts-1). ElevenLabs xəta verərsə avtomatik keçir; səbəb LAST_ERROR-da qalır.
"""
import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from openai import OpenAI

from backend import config

STYLE = {
    "formal": "Speak clearly and calmly, like a thoughtful narrator.",
    "neutral": "Speak naturally, like a real person talking to a friend.",
    "informal": "Speak in a relaxed, lively, conversational way, like everyday talk.",
}
HUMAN = ("Sound like a real human, not a voice assistant: natural rhythm, small natural pauses, "
         "varied intonation that follows the meaning, real emotion where it fits. Never flat, never robotic.")
ACCENT = {"az": "You are a native Azerbaijani speaker from Baku; use natural Azerbaijani pronunciation and "
                "stress, not a foreign accent.",
          "tr": "You are a native Turkish speaker from Istanbul.",
          "ru": "You are a native Russian speaker.",
          "en": "You are a native English speaker."}
ELEVEN_MODEL_HQ = getattr(config, "ELEVEN_MODEL_HQ", "eleven_multilingual_v2")

_EL_SLOTS = threading.BoundedSemaphore(max(1, getattr(config, "ELEVEN_CONCURRENCY", 2)))
LAST_ERROR = ""                 # ElevenLabs-ın son xətası (panel göstərir)
STATS = {"elevenlabs": 0, "openai": 0}
_lock = threading.Lock()

# ElevenLabs-ın hamıya açıq standart səsləri
EL_VOICES = {
    "el_sarah": ("EXAVITQu4vr4xnSDxMaL", "Sarah — qadın, yumşaq"),
    "el_laura": ("FGY2WhTYpPnrIDTdsKH5", "Laura — qadın, canlı"),
    "el_alice": ("Xb7hH8MSUJpSbSDYk0k2", "Alice — qadın, aydın"),
    "el_george": ("JBFqnCBsd6RMkjVDRZzb", "George — kişi, isti"),
    "el_brian": ("nPczCjzI2devNBz1zQrb", "Brian — kişi, dərin"),
    "el_charlie": ("IKne3meq5aSn9XLyUdCD", "Charlie — kişi, gənc"),
}
# OpenAI səsi seçilibsə, amma ElevenLabs açarı varsa — oxşar ElevenLabs səsi
OPENAI_TO_EL = {"nova": "el_sarah", "shimmer": "el_sarah", "coral": "el_laura", "alloy": "el_alice",
                "onyx": "el_brian", "echo": "el_george", "fable": "el_charlie", "sage": "el_alice"}
EL_TO_OPENAI = {"el_sarah": "nova", "el_laura": "coral", "el_alice": "shimmer",
                "el_george": "echo", "el_brian": "onyx", "el_charlie": "fable"}
OPENAI_VOICES = ("nova", "onyx", "alloy", "shimmer", "echo", "fable", "coral", "sage")


def provider() -> str:
    return "elevenlabs" if config.ELEVENLABS_API_KEY else "openai"


def _key(text: str, voice: str, lang: str, style: str, speed: float, prov: str, extra: str = "") -> str:
    return hashlib.sha1(f"{prov}|{voice}|{lang}|{style}|{speed:.2f}|{extra}|{text}".encode()).hexdigest()[:20]


def clip_path(key: str):
    return config.TTS_DIR / f"{key}.mp3"


def _speed_for(text: str, slot: float | None) -> float:
    """Mətn vaxta sığmırsa, səs bir az sürətli yaradılsın (1.0–1.2)."""
    if not slot:
        return 1.0
    need = len(text) / max(0.8, slot) / config.CHARS_PER_SEC
    return round(min(1.15, max(1.0, need)), 2)


def _elevenlabs(text: str, voice: str, lang: str, speed: float, hq: bool = False,
                prev: str = "", nxt: str = "") -> bytes:
    if voice.startswith("elid:"):          # dialoq rejimində klonlanmış səs
        vid = voice[5:]
    else:
        vid = EL_VOICES.get(voice if voice in EL_VOICES else OPENAI_TO_EL.get(voice, "el_sarah"))[0]
    if lang == "az":
        model = config.ELEVEN_MODEL_AZ
    else:
        model = ELEVEN_MODEL_HQ if hq else config.ELEVEN_MODEL_FAST
    body = {"text": text, "model_id": model}
    if model == config.ELEVEN_MODEL_AZ:
        # v3: stability yalnız 0 / 0.5 / 1; 0.5 = "Natural" — 1 robotik, 0 qeyri-sabit olur
        body["voice_settings"] = {"stability": 0.5, "similarity_boost": 0.75}
    else:
        body["voice_settings"] = {"stability": 0.4, "similarity_boost": 0.75, "style": 0.25,
                                  "use_speaker_boost": True, "speed": speed}
        if model == config.ELEVEN_MODEL_FAST:
            body["language_code"] = lang
        if prev:
            body["previous_text"] = prev[-300:]
        if nxt:
            body["next_text"] = nxt[:300]
    # Planın eyni anda sorğu limiti var (pulsuz: 2). Limitdən artıq göndərsək 429 qaytarır və cümlə
    # başqa səslə (OpenAI) deyilir — səs birdən dəyişir. Ona görə: növbə + 429-da gözləyib təkrar.
    for attempt in range(5):
        with _EL_SLOTS:
            r = requests.post(f"https://api.elevenlabs.io/v1/text-to-speech/{vid}",
                              params={"output_format": "mp3_44100_128"},
                              headers={"xi-api-key": config.ELEVENLABS_API_KEY, "Content-Type": "application/json"},
                              json=body, timeout=90)
        if r.status_code not in (429, 500, 502, 503) or attempt == 4:
            break
        time.sleep(1.0 + attempt * 1.5)
    if r.status_code != 200:
        msg = r.text[:300]
        try:
            d = r.json().get("detail")
            msg = d.get("message") or d.get("status") if isinstance(d, dict) else str(d)
        except Exception:
            pass
        raise RuntimeError(f"ElevenLabs {r.status_code}: {msg}")
    return r.content


def _openai(text: str, voice: str, lang: str, register: str, speed: float, persona: str = "") -> bytes:
    client = OpenAI(api_key=config.OPENAI_API_KEY, timeout=60)
    v = voice if voice in OPENAI_VOICES else EL_TO_OPENAI.get(voice, "nova")
    instructions = " ".join(x for x in (persona, ACCENT.get(lang, ""), STYLE.get(register, STYLE["neutral"]),
                                        HUMAN) if x)
    if speed > 1.05:
        instructions += " Speak a little faster than usual."
    try:
        resp = client.audio.speech.create(model=config.TTS_MODEL, voice=v, input=text,
                                          instructions=instructions, response_format="mp3")
    except Exception:
        v = v if v in ("nova", "onyx", "alloy", "shimmer", "echo", "fable") else "nova"
        resp = client.audio.speech.create(model=config.TTS_FALLBACK_MODEL, voice=v, input=text,
                                          response_format="mp3", speed=speed)
    return resp.read() if hasattr(resp, "read") else resp.content


def synth(text: str, voice: str = "nova", lang: str = "az", register: str = "neutral",
          slot: float | None = None, fallback: str | None = None, hq: bool = False,
          prev: str = "", nxt: str = "", persona: str = "") -> str:
    """mp3 yaradır (və ya keşdən götürür), açarını qaytarır."""
    global LAST_ERROR
    config.TTS_DIR.mkdir(parents=True, exist_ok=True)
    prov = provider()
    speed = _speed_for(text, slot)
    key = _key(text, voice, lang, register, speed, prov, f"{int(hq)}|{persona}|{prev[-60:]}|{nxt[:60]}")
    path = clip_path(key)
    if path.exists() and path.stat().st_size > 0:
        return key
    data, used = None, "openai"
    if prov == "elevenlabs":
        try:
            data, used = _elevenlabs(text, voice, lang, speed, hq=hq, prev=prev, nxt=nxt), "elevenlabs"
        except Exception as e:
            LAST_ERROR = str(e)[:300]   # limit / açar icazəsi / şəbəkə — OpenAI ilə davam
            data = None
    if data is None:
        data = _openai(text, fallback or voice, lang, register, speed, persona)
        if prov == "elevenlabs":
            # ehtiyat səsi ElevenLabs açarı altında saxlama — yoxsa həmin cümlə həmişəlik başqa səslə qalır
            key = _key(text, voice, lang, register, speed, "openai-fallback",
                       f"{int(hq)}|{persona}|{prev[-60:]}|{nxt[:60]}")
            path = clip_path(key)
    with _lock:
        STATS[used] += 1
    path.write_bytes(data)
    return key


def synth_many(segments: list[dict], voice: str, lang: str, register: str, hq: bool = False) -> list[dict]:
    """Cümlələri paralel səsləndirir: [{id, s, e, key}]. Qonşu cümlələr kontekst kimi verilir."""
    def one(i):
        s = segments[i]
        prev = segments[i - 1]["tr"] if i > 0 else ""
        nxt = segments[i + 1]["tr"] if i + 1 < len(segments) else ""
        try:
            return {"id": s["id"], "s": s["s"], "e": s["e"],
                    "key": synth(s["tr"], s.get("voice") or voice, lang, register, slot=s["e"] - s["s"],
                                 fallback=s.get("fallback"), hq=hq, prev=prev if hq else "",
                                 nxt=nxt if hq else "", persona=s.get("persona", ""))}
        except Exception as e:  # bir cümlə alınmasa, qalanları işləsin
            return {"id": s["id"], "s": s["s"], "e": s["e"], "key": None, "error": str(e)[:200]}

    with ThreadPoolExecutor(max_workers=config.TTS_WORKERS) as pool:
        return list(pool.map(one, range(len(segments))))


def check() -> str:
    """ElevenLabs açarını yoxlayır: plan, qalan simvollar, qısa sınaq səsi. Açarı göstərmir."""
    if not config.ELEVENLABS_API_KEY:
        return "ELEVENLABS_API_KEY boşdur → OpenAI səsi işləyir."
    h = {"xi-api-key": config.ELEVENLABS_API_KEY}
    lines = []
    try:
        r = requests.get("https://api.elevenlabs.io/v1/user/subscription", headers=h, timeout=20)
        if r.status_code == 200:
            d = r.json()
            lines.append(f"Plan: {d.get('tier')} · istifadə: {d.get('character_count')}/{d.get('character_limit')} "
                         f"simvol · klon: {'var' if d.get('can_use_instant_voice_cloning') else 'yox'}")
        else:
            lines.append(f"Abunə məlumatı: {r.status_code} (açarda 'User: read' icazəsi olmaya bilər)")
    except Exception as e:
        lines.append(f"Şəbəkə: {e}")
    for lang in ("az", "en"):
        try:
            _elevenlabs("Salam, necəsən?" if lang == "az" else "Hello there.", "el_sarah", lang, 1.0, hq=True)
            lines.append(f"Səs sınağı ({lang}): işləyir ✓")
        except Exception as e:
            lines.append(f"Səs sınağı ({lang}): {e}")
    return "\n".join(lines)
