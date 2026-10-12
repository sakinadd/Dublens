"""Video studiyası: istifadəçinin öz videosunu tərcümə (altyazı) və ya dublyaj edir.

    video → ffmpeg: səsi çıxar → Whisper: söz-söz vaxtla mətn → cümlələr
          → translate_chain (sub və ya dub) → [altyazı] SRT + MP4 (yumşaq altyazı ilə)
                                              [dublyaj] hər cümlə TTS → vaxtına yerləşdir (numpy)
                                                        + orijinal səs 12% → MP4

ffmpeg: imageio-ffmpeg paketindən (pip ilə gəlir) və ya sistemdəki ffmpeg.
"""
import json
import shutil
import time
import subprocess
import uuid
from pathlib import Path

import numpy as np
from openai import OpenAI

from backend import chains, config, segments, speakers, tts

SR = 24000                  # dublyaj trekinin tezliyi
MAX_MINUTES = 15
WHISPER_LIMIT = 24 * 1024 * 1024


def ffmpeg_bin() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        exe = shutil.which("ffmpeg")
        if exe:
            return exe
    raise RuntimeError("ffmpeg tapılmadı. Terminalda: pip install imageio-ffmpeg")


def _run(args: list[str]) -> subprocess.CompletedProcess:
    r = subprocess.run([ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", *args],
                       capture_output=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg: " + r.stderr.decode(errors="ignore")[-400:])
    return r


def duration(path: Path) -> float:
    r = subprocess.run([ffmpeg_bin(), "-hide_banner", "-i", str(path)], capture_output=True)
    txt = r.stderr.decode(errors="ignore")
    for line in txt.splitlines():
        if "Duration:" in line:
            h, m, s = line.split("Duration:")[1].split(",")[0].strip().split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    return 0.0


def has_audio(path: Path) -> bool:
    r = subprocess.run([ffmpeg_bin(), "-hide_banner", "-i", str(path)], capture_output=True)
    return "Audio:" in r.stderr.decode(errors="ignore")


def new_job(filename: str, data: bytes) -> Path:
    job = config.DATA_DIR / "studio" / uuid.uuid4().hex[:12]
    job.mkdir(parents=True, exist_ok=True)
    ext = Path(filename).suffix.lower() or ".mp4"
    (job / f"input{ext}").write_bytes(data)
    return job


def input_video(job: Path) -> Path:
    return next(p for p in job.iterdir() if p.name.startswith("input"))


def _pcm(path: Path, tempo: float = 1.0) -> np.ndarray:
    """İstənilən audio/video → mono float32 (SR). tempo > 1 olarsa, səs sürətləndirilir (ton dəyişmədən)."""
    af = ["-af", f"atempo={min(2.0, max(0.5, tempo)):.3f}"] if abs(tempo - 1) > 0.01 else []
    r = subprocess.run([ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-i", str(path), "-vn", *af,
                        "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"], capture_output=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg: " + r.stderr.decode(errors="ignore")[-300:])
    return np.frombuffer(r.stdout, dtype=np.float32).copy()


# ------------------------------------------------------------------ 1. səs → mətn
def transcribe(job: Path, on_step=lambda *_: None, dialog: bool = False) -> tuple[list[dict], str]:
    """Whisper: söz-söz vaxt nişanları ilə. dialog=True → danışanlar ayrılır (A, B, C…).
    Qaytarır: (cümlələr, dil)."""
    video = input_video(job)
    total = duration(video)
    if total > MAX_MINUTES * 60 + 5:
        raise RuntimeError(f"Video {MAX_MINUTES} dəqiqədən uzundur ({total / 60:.0f} dəq). Qısa hissəsini yüklə.")
    if not has_audio(video):
        raise RuntimeError("Bu videoda səs yoxdur — faylda yalnız görüntü var. YouTube-dan endirilən "
                           "'videoplayback.mp4' faylları çox vaxt səssiz olur. Səsi olan video yüklə.")
    audio = job / "speech.mp3"
    _run(["-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k", str(audio)])
    if dialog:
        on_step(f"Səs çıxarıldı ({total / 60:.1f} dəq). Kim nə vaxt danışır — ayrılır…")
        try:
            sents = speakers.to_sentences(speakers.diarize(audio))
            if sents:
                n = len({x["speaker"] for x in sents})
                on_step(f"{n} danışan tapıldı.")
                (job / "source.json").write_text(json.dumps({"lang": "", "sentences": sents}, ensure_ascii=False))
                return sents, ""
        except Exception as e:
            on_step(f"Danışanları ayırmaq alınmadı, adi rejimlə davam edirəm. ({str(e)[:140]})")
    on_step(f"Səs çıxarıldı ({total / 60:.1f} dəq). Whisper danışığı mətnə çevirir…")
    client = OpenAI(api_key=config.OPENAI_API_KEY, timeout=300)
    pieces = [(audio, 0.0)]
    if audio.stat().st_size > WHISPER_LIMIT:            # böyük fayl → 10 dəqiqəlik hissələr
        pieces = []
        for i, start in enumerate(range(0, int(total) + 1, 600)):
            part = job / f"speech_{i}.mp3"
            _run(["-ss", str(start), "-t", "600", "-i", str(audio), "-c", "copy", str(part)])
            pieces.append((part, float(start)))
    words, lang = [], ""
    for path, offset in pieces:
        with open(path, "rb") as f:
            r = client.audio.transcriptions.create(model="whisper-1", file=f, response_format="verbose_json",
                                                   timestamp_granularities=["word", "segment"])
        lang = lang or (getattr(r, "language", "") or "")
        for w in getattr(r, "words", None) or []:
            ww = w.word if hasattr(w, "word") else w["word"]
            st = (w.start if hasattr(w, "start") else w["start"]) + offset
            en = (w.end if hasattr(w, "end") else w["end"]) + offset
            words.append((float(st), float(en), str(ww).strip()))
    sents = segments.to_sentences(words)
    if not sents:
        raise RuntimeError("Videoda danışıq tapılmadı.")
    (job / "source.json").write_text(json.dumps({"lang": lang, "sentences": sents}, ensure_ascii=False))
    return sents, lang


# ------------------------------------------------------------------ 2. tərcümə
def translate(job: Path, sents: list[dict], title: str, lang: str, mode: str, glossary: dict) -> dict:
    a = chains._safe_analysis({"segments": sents, "title": title, "lang": lang})
    res = chains.translate_chain.invoke({"segments": sents, "title": title, "lang": lang, "mode": mode,
                                         "glossary": glossary, "analysis": a})
    (job / f"{lang}.srt").write_text(segments.to_srt(res["segments"], "tr"), encoding="utf-8")
    return res


# ------------------------------------------------------------------ 2b. dialoq: hər danışana səs
def speaker_voices(job: Path, res: dict, use_clone: bool, on_step=lambda *_: None) -> dict:
    segs = res["segments"]
    if not any(s.get("speaker") for s in segs):
        return {}
    full = _pcm16(job / "speech.mp3")
    info = speakers.assign_voices(full, segs, use_clone, job.name[:8], on_step)
    speakers.apply(segs, info)
    return info


def _pcm16(path: Path) -> np.ndarray:
    r = subprocess.run([ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-i", str(path), "-ac", "1",
                        "-ar", str(speakers.SR), "-f", "f32le", "-"], capture_output=True)
    return np.frombuffer(r.stdout, dtype=np.float32).copy()


# ------------------------------------------------------------------ 3a. altyazılı video
def subtitled_video(job: Path, lang: str) -> Path:
    video, srt, out = input_video(job), job / f"{lang}.srt", job / f"altyazili_{lang}.mp4"
    code = {"az": "aze", "tr": "tur", "ru": "rus", "en": "eng"}.get(lang, "und")
    try:   # video və səs olduğu kimi, altyazı ayrıca trek (QuickTime / VLC-də CC düyməsi)
        _run(["-i", str(video), "-i", str(srt), "-map", "0:v", "-map", "0:a?", "-map", "1:0", "-c:v", "copy",
              "-c:a", "copy", "-c:s", "mov_text", "-metadata:s:s:0", f"language={code}", str(out)])
    except RuntimeError:   # mp4-ə sığmayan kodek (məs. webm) → yenidən kodla
        _run(["-i", str(video), "-i", str(srt), "-map", "0:v", "-map", "0:a?", "-map", "1:0", "-c:v", "libx264",
              "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-c:s", "mov_text",
              "-metadata:s:s:0", f"language={code}", str(out)])
    return out


# ------------------------------------------------------------------ 3b. dublyajlı video
def dubbed_video(job: Path, res: dict, lang: str, voice: str, on_step=lambda *_: None) -> Path:
    segs = res["segments"]
    register = res["meta"].get("register", "neutral")
    on_step(f"{len(segs)} cümlə səsləndirilir ({'ElevenLabs' if tts.provider() == 'elevenlabs' else 'OpenAI'})…")
    tts.STATS.update(elevenlabs=0, openai=0)
    clips = tts.synth_many(segs, voice, lang, register, hq=True)
    video = input_video(job)
    total = duration(video)
    order = sorted(range(len(segs)), key=lambda i: segs[i]["s"])
    win = {}                                       # cümlənin sığmalı olduğu vaxt: növbəti cümlə başlayana qədər
    for n, i in enumerate(order):
        nxt = next((segs[j]["s"] for j in order[n + 1:] if segs[j]["s"] > segs[i]["s"] + 0.25), total)
        win[i] = max(0.7, nxt - segs[i]["s"])

    # vaxtına çox sığmayan cümlələr: LLM qısaldır → yenidən səsləndirilir (bir dəfə)
    pcms = {i: _pcm(tts.clip_path(c["key"])) for i, c in enumerate(clips) if c.get("key")}
    long_ = [i for i, x in pcms.items() if len(x) / SR > win[i] * 1.2 and len(segs[i]["tr"]) > 12]
    if long_:
        on_step(f"{len(long_)} cümlə vaxtına sığmır — qısaldılır…")
        lines = [{"id": i, "tr": segs[i]["tr"],
                  "max_chars": max(8, int(len(segs[i]["tr"]) * win[i] * 1.05 / (len(pcms[i]) / SR)))}
                 for i in long_]
        short = {}
        for k in range(0, len(lines), 30):
            try:
                r = chains.shorten_chain.invoke({"language": config.LANGS[lang],
                                                 "lines": json.dumps(lines[k:k + 30], ensure_ascii=False)})
                for it in r.get("items", []):
                    short[int(it["id"])] = str(it["tr"]).strip()
            except Exception:
                pass
        redo = [i for i in long_ if 0 < len(short.get(i, "")) < len(segs[i]["tr"])]
        for i in redo:
            segs[i]["tr"], segs[i]["shortened"] = short[i], True
        if redo:
            sub = [segs[i] for i in redo]
            for i, c in zip(redo, tts.synth_many(sub, voice, lang, register, hq=True)):
                if c.get("key"):
                    clips[i] = c
                    pcms[i] = _pcm(tts.clip_path(c["key"]))
            (job / f"{lang}.srt").write_text(segments.to_srt(segs, "tr"), encoding="utf-8")

    res["tts"] = dict(tts.STATS)
    if tts.provider() == "elevenlabs" and tts.STATS["openai"]:
        res["tts_warning"] = (f"{tts.STATS['openai']} cümlə ElevenLabs əvəzinə OpenAI ilə səsləndi. "
                              f"Səbəb: {tts.LAST_ERROR or 'naməlum'}")
        on_step("⚠️ " + res["tts_warning"])

    on_step("Səslər vaxtına yerləşdirilir, orijinal səs alçaldılır…")
    try:
        original = _pcm(video)
    except RuntimeError:
        original = np.zeros(int(total * SR), dtype=np.float32)
    # yerləşdirmə: hər cümlə öz anında başlayır. Əvvəlki cümlə hələ bitməyibsə:
    #   eyni adamdırsa → arxasınca davam edir; başqa adamdırsa → ən çox 0.4 san gözləyir,
    #   sonra əvvəlki səs yumşaq kəsilir. Beləcə səslər heç vaxt sürüşmür və başqasının vaxtına keçmir.
    placed: list[list] = []                         # [start_sample, pcm, speaker]
    trimmed = 0
    for i in order:
        if i not in pcms:
            continue
        raw = pcms[i]
        tempo = min(1.18, max(1.0, (len(raw) / SR) / win[i]))
        pcm = _pcm(tts.clip_path(clips[i]["key"]), tempo) if tempo > 1.02 else raw
        start = int(segs[i]["s"] * SR)
        if placed:
            p0, prev, who = placed[-1]
            end = p0 + len(prev)
            if end > start:
                if who == segs[i].get("speaker") or end - start <= int(0.4 * SR):
                    start = end + int(0.04 * SR)
                else:
                    keep = max(start - int(0.03 * SR) - p0, int(0.6 * SR))
                    if keep < len(prev):
                        fade = min(int(0.08 * SR), keep)
                        prev = prev[:keep].copy()
                        prev[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
                        placed[-1][1] = prev
                        trimmed += 1
                    start = max(start, p0 + len(prev) + int(0.02 * SR))
        placed.append([start, pcm, segs[i].get("speaker")])
    if trimmed:
        on_step(f"{trimmed} yerdə əvvəlki səs növbəti danışan üçün yumşaq kəsildi.")
    length = max([len(original)] + [p0 + len(x) for p0, x, _ in placed])
    track = np.zeros(length, dtype=np.float32)
    for p0, x, _ in placed:
        track[p0:p0 + len(x)] += x
    # orijinal səs: dublyaj danışanda 4%, fasilələrdə 15% (mühit səsi qalsın, ingiliscə danışıq qarışmasın)
    k = int(0.15 * SR)
    env = np.convolve((np.abs(track) > 0.01).astype(np.float32), np.ones(k, np.float32) / k, mode="same")
    gain = 0.15 - 0.11 * np.clip(env * 3, 0, 1)
    mix = track.copy()
    n = min(len(original), len(mix))
    mix[:n] += original[:n] * gain[:n]
    peak = float(np.max(np.abs(mix))) or 1.0
    if peak > 0.98:
        mix = mix * (0.98 / peak)
    wav = job / "dub.wav"
    p = subprocess.run([ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", "-f", "f32le", "-ar", str(SR),
                        "-ac", "1", "-i", "-", str(wav)], input=mix.astype(np.float32).tobytes(), capture_output=True)
    if p.returncode != 0:
        raise RuntimeError("ffmpeg: " + p.stderr.decode(errors="ignore")[-300:])

    on_step("Video yığılır…")
    out, srt = job / f"dublyaj_{lang}.mp4", job / f"{lang}.srt"
    base = ["-i", str(video), "-i", str(wav), "-i", str(srt), "-map", "0:v", "-map", "1:a", "-map", "2:0"]
    tail = ["-c:a", "aac", "-b:a", "160k", "-c:s", "mov_text", "-t", f"{duration(video):.2f}", str(out)]
    try:
        _run([*base, "-c:v", "copy", *tail])
    except RuntimeError:
        _run([*base, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", *tail])
    return out


# ------------------------------------------------------------------ 4. tarixçə
def save_result(job: Path, username: str, title: str, result: dict) -> None:
    """Nəticəni iş qovluğunda saxlayır — panel sonra "Əvvəlki işlər"dən yenidən aça bilsin."""
    data = {**result, "user": username, "title": title, "created": result.get("created") or time.time()}
    (job / "result.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def history(username: str, limit: int = 20) -> list[dict]:
    root = config.DATA_DIR / "studio"
    out = []
    for f in root.glob("*/result.json") if root.exists() else []:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if d.get("user") == username and Path(d.get("out", "")).exists():
            out.append(d)
    return sorted(out, key=lambda d: -d.get("created", 0))[:limit]
