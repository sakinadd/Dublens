"""Dialoq videoları: kim danışır, neçə nəfərdir və hər kəsə hansı səs düşür.

    səs → gpt-4o-transcribe-diarize (danışan etiketli hissələr: A, B, C…) → cümlələrə bölünür
        → hər danışanın səs tonu (F0) ölçülür → qadın / kişi
        → səs seçimi:  [klon]   ElevenLabs Instant Voice Clone — hər kəs öz səsi ilə danışır (Starter planı lazımdır)
                       [hazır]  cinsinə uyğun, hər danışana fərqli hazır səs
Klon alınmasa (pulsuz plan, az səs materialı, şəbəkə) avtomatik hazır səsə keçir.
"""
import io
import re
import wave

import numpy as np
import requests

from backend import config, tts

DIARIZE_MODEL = "gpt-4o-transcribe-diarize"
SR = 16000
MAX_SENT_CHARS = 110
CLONE_MIN_SEC = 8          # bundan az material olarsa klon pis alınır — hazır səs
CLONE_MAX_SEC = 90

# səs qrupu → hazır səslər (hər danışana hələ verilməmiş ilk səs düşür)
#   c — uşaq (ton ≥ 255 Hz), f — qadın (165–255), m — kişi (< 165; ən dərin ton → ən yaşlı/dərin səs)
POOL = {
    "elevenlabs": {"c": ["el_laura", "el_alice"], "f": ["el_sarah", "el_alice", "el_laura"],
                   "m": ["el_george", "el_charlie", "el_brian"], "m_deep": ["el_brian", "el_george", "el_charlie"]},
    "openai": {"c": ["coral", "shimmer"], "f": ["nova", "shimmer", "coral"],
               "m": ["echo", "fable", "onyx"], "m_deep": ["onyx", "echo", "fable"]},
}
GENDER_AZ = {"c": "uşaq", "f": "qadın", "m": "kişi"}
# OpenAI ehtiyat səsinə rol təsviri — eyni səs uşaq / yaşlı kimi fərqli oxunur
PERSONA = {"c": "You are a young child, about 8–10 years old: bright, curious, playful, a bit fast.",
           "f": "You are an adult woman speaking warmly and naturally.",
           "m": "You are an adult man speaking in a relaxed, friendly way.",
           "m_deep": "You are an elderly man, around 70: calm, unhurried, warm, slightly gravelly voice."}
CHILD_HZ, FEMALE_HZ, DEEP_HZ = 240, 165, 115


def group(hz: float) -> str:
    return "c" if hz >= CHILD_HZ else "f" if hz >= FEMALE_HZ else "m"


def _pick(pool: list[str], taken: set) -> int:
    for i, v in enumerate(pool):
        if v not in taken:
            return i
    return len(taken) % len(pool)


# ------------------------------------------------------------------ 1. kim nə vaxt danışır
def diarize(audio_path) -> list[dict]:
    """[{speaker, s, e, text}] — OpenAI-ın danışanları ayıran transkripsiya modeli."""
    with open(audio_path, "rb") as f:
        r = requests.post("https://api.openai.com/v1/audio/transcriptions",
                          headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
                          files={"file": (audio_path.name, f, "audio/mpeg")},
                          data={"model": DIARIZE_MODEL, "response_format": "diarized_json",
                                "chunking_strategy": "auto"},
                          timeout=900)
    if r.status_code != 200:
        raise RuntimeError(f"diarize {r.status_code}: {r.text[:200]}")
    out = []
    for seg in r.json().get("segments", []):
        text = str(seg.get("text", "")).strip()
        if text:
            out.append({"speaker": str(seg.get("speaker") or "A"), "s": float(seg["start"]),
                        "e": float(seg["end"]), "text": text})
    return out


MERGE_GAP = 0.8           # eyni danışanın bu qədər fasilə ilə gələn parçaları bir cümlə sayılır
MERGE_CHARS = 150


def merge_parts(parts: list[dict]) -> list[dict]:
    """Eyni danışanın qırıq parçalarını ("Mr.", "Right, uh,") birləşdirir — qısa parçalar ayrıca
    səsləndiriləndə danışıq kəsik-kəsik, robot kimi çıxır."""
    out: list[dict] = []
    for p in parts:
        last = out[-1] if out else None
        if (last and last["speaker"] == p["speaker"] and p["s"] - last["e"] <= MERGE_GAP
                and len(last["text"]) + len(p["text"]) <= MERGE_CHARS):
            last["text"] = f'{last["text"]} {p["text"]}'
            last["e"] = p["e"]
        else:
            out.append(dict(p))
    return out


def to_sentences(parts: list[dict]) -> list[dict]:
    """Uzun hissələri cümlələrə bölür (vaxt simvol sayına görə paylanır). Danışan etiketi saxlanılır."""
    sents = []
    for p in merge_parts(parts):
        pieces = [x.strip() for x in re.split(r"(?<=[.!?…])\s+", p["text"]) if x.strip()]
        # çox qısa parçaları əvvəlkinə birləşdir, çox uzunları vergüldən böl
        chunks: list[str] = []
        for x in pieces:
            if chunks and (len(chunks[-1]) < 45 or len(x) < 25) and len(chunks[-1]) + len(x) <= MAX_SENT_CHARS:
                chunks[-1] += " " + x
            elif len(x) > MAX_SENT_CHARS:
                buf = ""
                for w in re.split(r"(?<=,)\s+", x):
                    if buf and len(buf) + len(w) > MAX_SENT_CHARS:
                        chunks.append(buf)
                        buf = w
                    else:
                        buf = (buf + " " + w).strip()
                if buf:
                    chunks.append(buf)
            else:
                chunks.append(x)
        total = sum(len(c) for c in chunks) or 1
        t = p["s"]
        for c in chunks:
            dur = (p["e"] - p["s"]) * len(c) / total
            sents.append({"id": len(sents), "s": round(t, 2), "e": round(max(t + dur, t + 0.6), 2),
                          "src": c, "speaker": p["speaker"]})
            t += dur
    return sents


# ------------------------------------------------------------------ 2. səs tonu
def _pitch_frames(pcm: np.ndarray) -> np.ndarray:
    """Hər 20 ms üçün əsas ton (Hz), YIN alqoritmi. Səssiz / küylü kadrlar atılır.
    YIN avtokorrelyasiyadan fərqli olaraq oktava səhvi (tonu 2 dəfə yüksək ölçmək) az edir."""
    frame, hop = int(0.04 * SR), int(0.02 * SR)
    lo, hi = int(SR / 400), int(SR / 70)
    if len(pcm) < frame + hi:
        return np.zeros(0)
    rms_all = float(np.sqrt(np.mean(pcm ** 2))) or 1e-6
    out = []
    for i in range(0, len(pcm) - frame - hi, hop):
        x = pcm[i:i + frame + hi].astype(np.float64)
        if float(np.sqrt(np.mean(x[:frame] ** 2))) < 0.4 * rms_all:
            continue
        # fərq funksiyası d(τ) = Σ (x[j] − x[j+τ])²
        w = x[:frame]
        d = np.array([np.sum((w - x[t:t + frame]) ** 2) for t in range(1, hi + 1)])
        cmnd = d * np.arange(1, hi + 1) / np.maximum(np.cumsum(d), 1e-12)
        cand = np.where(cmnd[lo - 1:] < 0.15)[0]
        if not len(cand):
            continue
        t = cand[0] + lo - 1
        while t + 1 < len(cmnd) and cmnd[t + 1] < cmnd[t]:      # yerli minimuma qədər en
            t += 1
        out.append(SR / (t + 1))
    return np.array(out)


def _pitch(pcm: np.ndarray) -> float:
    f = _pitch_frames(pcm)
    return float(np.median(f)) if len(f) >= 5 else 0.0


def _speaker_audio(full: np.ndarray, sents: list[dict], who: str, limit: float) -> np.ndarray:
    parts, got = [], 0.0
    for s in sents:
        if s["speaker"] != who:
            continue
        a, b = int(s["s"] * SR), int(s["e"] * SR)
        chunk = full[a:b]
        if len(chunk):
            parts.append(chunk)
            got += len(chunk) / SR
        if got >= limit:
            break
    return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)


def _wav_bytes(pcm: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(pcm, -1, 1) * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


# ------------------------------------------------------------------ 3. ElevenLabs klon
def clone(name: str, pcm: np.ndarray) -> str:
    r = requests.post("https://api.elevenlabs.io/v1/voices/add",
                      headers={"xi-api-key": config.ELEVENLABS_API_KEY},
                      data={"name": name, "remove_background_noise": "true",
                            "description": "DubLens müvəqqəti klon (iş bitəndə silinir)"},
                      files=[("files", (f"{name}.wav", _wav_bytes(pcm), "audio/wav"))], timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"ElevenLabs klon {r.status_code}: {r.text[:160]}")
    return r.json()["voice_id"]


def delete_clones(voice_ids: list[str]) -> None:
    for vid in voice_ids:
        try:
            requests.delete(f"https://api.elevenlabs.io/v1/voices/{vid}",
                            headers={"xi-api-key": config.ELEVENLABS_API_KEY}, timeout=30)
        except Exception:
            pass


# ------------------------------------------------------------------ 4. hər danışana səs
def _speaker_pitch(full: np.ndarray, sents: list[dict], who: str, limit: float = 45.0) -> float:
    """Yalnız başqası ilə üst-üstə düşməyən hissələrdən ölçülür (iki nəfər eyni anda danışanda ton qarışır)."""
    others = [(x["s"], x["e"]) for x in sents if x["speaker"] != who]
    frames, got = [], 0.0
    for x in sents:
        if x["speaker"] != who or any(a < x["e"] and x["s"] < b for a, b in others):
            continue
        f = _pitch_frames(full[int(x["s"] * SR):int(x["e"] * SR)])
        frames.append(f)
        got += x["e"] - x["s"]
        if got >= limit:
            break
    if not frames or sum(len(f) for f in frames) < 10:      # təmiz hissə yoxdursa — hamısından
        frames = [_pitch_frames(_speaker_audio(full, sents, who, limit))]
    f = np.concatenate(frames)
    return float(np.median(f)) if len(f) >= 5 else 0.0


def merge_minor(full: np.ndarray, sents: list[dict], on_step=lambda *_: None) -> None:
    """Cəmi 1–2 dəfə, 2.5 saniyədən az danışan "danışan" adətən ayırma səhvidir → tonca ən yaxın danışana."""
    talk: dict = {}
    for x in sents:
        talk.setdefault(x["speaker"], []).append(x["e"] - x["s"])
    major = [k for k, v in talk.items() if sum(v) >= 2.5 or len(v) > 2]
    minor = [k for k in talk if k not in major]
    if not major or not minor:
        return
    hz = {k: _speaker_pitch(full, sents, k) for k in talk}
    for k in minor:
        to = min(major, key=lambda m: abs(np.log((hz[k] or 150) / (hz[m] or 150))))
        for x in sents:
            if x["speaker"] == k:
                x["speaker"] = to
        on_step(f"Qısa danışan ({sum(talk[k]):.0f} san) əsas danışanlardan birinə birləşdirildi.")


def classify(hz: dict) -> dict:
    """Tona görə qrup: c uşaq, f qadın, m kişi, m_deep dərin/yaşlı kişi.
    Əvvəl mütləq hədlər, sonra danışanlar bir-biri ilə müqayisə olunur: eyni qrupa düşən, amma tonu
    xeyli fərqli iki nəfər ayrılır (məs. uşaq və qadın, kişi və yaşlı kişi)."""
    g = {}
    for k, v in hz.items():
        g[k] = ("c" if v >= CHILD_HZ else "f" if v >= FEMALE_HZ else
                "m_deep" if 0 < v < DEEP_HZ else "m")
    order = sorted(hz, key=lambda k: -hz[k])
    for hi_, lo_ in zip(order, order[1:]):
        r = hz[hi_] / hz[lo_] if hz[lo_] else 1
        if g[hi_] == "c" and g[lo_] == "f" and r >= 1.45:     # uşaqla yanaşı: qadından çox kişidir
            g[lo_] = "m"                                       # (yaşlı kişilərin tonu 150–180 Hz-ə qalxır)
        elif g[hi_] == g[lo_] and r >= 1.3:
            if g[hi_] == "f":
                if hz[hi_] >= 230:
                    g[hi_] = "c"
                elif hz[lo_] < 190:
                    g[lo_] = "m"
            elif g[hi_] == "m":
                g[lo_] = "m_deep"
    return g


def assign_voices(full: np.ndarray, sents: list[dict], use_clone: bool, tag: str,
                  on_step=lambda *_: None) -> dict:
    """Qaytarır: {speaker: {n, gender, pitch, seconds, voice, fallback, persona, label, cloned}}."""
    prov = tts.provider()
    merge_minor(full, sents, on_step)
    order = []
    for x in sents:
        if x["speaker"] not in order:
            order.append(x["speaker"])
    hz = {who: _speaker_pitch(full, sents, who) for who in order}
    groups = classify(hz)
    taken: set = set()
    info = {}
    for i, who in enumerate(order):
        key = groups[who]
        g = "m" if key == "m_deep" else key
        pool, oa = POOL[prov][key], POOL["openai"][key]
        k = _pick(pool, taken)
        voice = pool[k]
        fallback = tts.EL_TO_OPENAI.get(voice, voice) if prov == "elevenlabs" else oa[k]
        taken.add(voice)
        label, cloned = (tts.EL_VOICES[voice][1].split(" —")[0] if voice in tts.EL_VOICES
                         else voice.capitalize()), False
        pcm = _speaker_audio(full, sents, who, CLONE_MAX_SEC)
        sec = sum(x["e"] - x["s"] for x in sents if x["speaker"] == who)
        if use_clone and prov == "elevenlabs":
            if len(pcm) / SR < CLONE_MIN_SEC:
                on_step(f"Danışan {i + 1}: klon üçün səs azdır ({len(pcm) / SR:.0f} san) — hazır səs.")
            else:
                try:
                    voice = "elid:" + clone(f"dublens-{tag}-{who}", pcm)
                    label, cloned = "öz səsi (klon)", True
                except Exception as e:
                    on_step(f"Danışan {i + 1}: klon alınmadı — hazır səs. ({str(e)[:120]})")
        info[who] = {"n": i + 1, "gender": g, "pitch": round(hz[who]), "seconds": round(sec), "voice": voice,
                     "persona": PERSONA[key], "fallback": fallback, "label": label, "cloned": cloned}
    return info


def apply(segments: list[dict], info: dict) -> None:
    for s in segments:
        v = info.get(s.get("speaker"))
        if v:
            s["voice"], s["fallback"], s["persona"] = v["voice"], v["fallback"], v.get("persona", "")


def describe(info: dict) -> str:
    return " · ".join(f"{v['n']}: {GENDER_AZ[v['gender']]}, {v['label']}" for v in info.values())
