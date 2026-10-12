"""Dialoq rejimi: danışanları ayırma → səs tonu → hər danışana səs → dublyajlı video.
OpenAI və ElevenLabs çağırışları saxta cavablarla əvəz olunur (açar lazım deyil).

    python tests/test_dialog.py <qısa.mp3>
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("OPENAI_API_KEY", "test")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np  # noqa: E402

from backend import chains, config, speakers, studio, tts  # noqa: E402

SR = speakers.SR


def voice(f0: float, sec: float) -> np.ndarray:
    """Səsə bənzər siqnal: əsas ton + harmonikalar, hecalar kimi açılıb-bağlanır."""
    t = np.arange(int(sec * SR)) / SR
    x = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in range(1, 6))
    env = 0.5 + 0.5 * np.sign(np.sin(2 * np.pi * 3 * t))
    return (0.2 * x * env).astype(np.float32)


# 1) səs tonu → cins
for f0, want in [(110, "m"), (125, "m"), (210, "f"), (240, "f")]:
    hz = speakers._pitch(voice(f0, 3))
    got = "f" if hz >= 165 else "m"
    print(f"F0 {f0} → ölçülən {hz:.0f} Hz → {got}")
    assert got == want and abs(hz - f0) < 15

# 2) cümlələrə bölmə
parts = [{"speaker": "A", "s": 0.0, "e": 6.0, "text": "Salam, necəsən? Bu gün çox işim var, sonra danışaq."},
         {"speaker": "B", "s": 6.2, "e": 9.0, "text": "Yaxşı. Mən də gözləyirəm."},
         {"speaker": "C", "s": 9.2, "e": 12.0, "text": "Mən də buradayam!"}]
sents = speakers.to_sentences(parts)
print("cümlələr:", [(x["speaker"], x["s"], x["e"], x["src"]) for x in sents])
assert {x["speaker"] for x in sents} == {"A", "B", "C"}
assert all(b["s"] >= a["s"] for a, b in zip(sents, sents[1:]))

# 3) səs paylanması: A kişi, B qadın, C kişi → fərqli səslər
full = np.concatenate([voice(115, 6.1), np.zeros(int(0.1 * SR), np.float32), voice(220, 2.9),
                       np.zeros(int(0.2 * SR), np.float32), voice(130, 2.8)])
config.ELEVENLABS_API_KEY = "x"            # elevenlabs rejimi
cloned = []
speakers.clone = lambda name, pcm: cloned.append((name, len(pcm) / SR)) or f"vid_{name[-1]}"
info = speakers.assign_voices(full, sents, use_clone=False, tag="t")
print("hazır səslər:", speakers.describe(info))
assert info["A"]["gender"] == "m" and info["B"]["gender"] == "f" and info["C"]["gender"] == "m"
assert info["A"]["voice"] != info["C"]["voice"] and info["B"]["voice"].startswith("el_")
assert info["A"]["fallback"] in ("onyx", "echo", "fable") and info["B"]["fallback"] in ("nova", "shimmer", "coral")

msgs = []
speakers.CLONE_MIN_SEC = 4
info = speakers.assign_voices(full, sents, use_clone=True, tag="t", on_step=msgs.append)
print("klon:", speakers.describe(info), msgs)
assert info["A"]["cloned"] and info["A"]["voice"] == "elid:vid_A"
assert not info["B"]["cloned"] and not info["C"]["cloned"]     # 3 san < 4 san → hazır səs

config.ELEVENLABS_API_KEY = ""             # açar yoxdur → OpenAI səsləri
info = speakers.assign_voices(full, sents, use_clone=True, tag="t")
print("openai:", speakers.describe(info))
assert info["B"]["voice"] in ("nova", "shimmer", "coral") and not any(v["cloned"] for v in info.values())

# 4) tts: hər cümlə öz səsi ilə; klon xəta versə ehtiyat (cinsə uyğun) OpenAI səsi
calls = []
config.ELEVENLABS_API_KEY = "x"


def fake_el(text, v, lang, speed, **kw):
    calls.append(("el", v))
    if v.startswith("elid:bad"):
        raise RuntimeError("limit")
    return Path(sys.argv[1]).read_bytes()


def fake_oa(text, v, lang, register, speed, *a):
    calls.append(("oa", v))
    return Path(sys.argv[1]).read_bytes()


tts._elevenlabs, tts._openai = fake_el, fake_oa
config.TTS_DIR = Path("/tmp/dl_dialog_tts")
shutil.rmtree(config.TTS_DIR, ignore_errors=True)
segs = [{**x, "tr": f"cümlə {x['id']}"} for x in sents]
segs[0]["voice"], segs[0]["fallback"] = "elid:bad", "onyx"
segs[2]["voice"], segs[2]["fallback"] = "el_laura", "coral"
tts.synth_many(segs, "nova", "az", "neutral")
print("tts çağırışları:", calls)
assert ("el", "elid:bad") in calls and ("oa", "onyx") in calls and ("el", "el_laura") in calls

# 5) tam axın: video → (saxta) diarize → tərcümə → səslər → dublyajlı mp4
ff = studio.ffmpeg_bin()
work = Path("/tmp/dl_dialog")
shutil.rmtree(work, ignore_errors=True)
work.mkdir()
wav = work / "talk.wav"
import wave  # noqa: E402
with wave.open(str(wav), "wb") as w:
    w.setnchannels(1), w.setsampwidth(2), w.setframerate(SR)
    w.writeframes((full * 32767).astype(np.int16).tobytes())
video = work / "dialog.mp4"
subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=gray:s=320x240:d=12", "-i", str(wav),
                "-c:v", "libx264", "-c:a", "aac", "-shortest", str(video)], check=True)
config.DATA_DIR = work
job = studio.new_job("dialog.mp4", video.read_bytes())
speakers.diarize = lambda path: parts
src, _ = studio.transcribe(job, on_step=print, dialog=True)
assert len({x["speaker"] for x in src}) == 3
chains._safe_analysis = lambda x: {"source_language": "az", "topic": "dialoq", "register": "informal",
                                   "glossary": {}}
chains.translate_chain = SimpleNamespace(invoke=lambda x: {"segments": [{**s, "tr": "tərcümə " + s["src"]} for s in x["segments"]],
                                           "meta": {"register": "informal", "translated": len(x["segments"]),
                                                    "count": len(x["segments"])}})
res = studio.translate(job, src, "dialoq", "az", "dub", {})
calls.clear()
info = studio.speaker_voices(job, res, use_clone=False, on_step=print)
assert all(s.get("voice") for s in res["segments"])
out = studio.dubbed_video(job, res, "az", "nova", on_step=print)
used = {v for k, v in calls}
print("istifadə olunan səslər:", used, "→", out.name, f"{studio.duration(out):.1f} san")
assert len(used) == 3 and abs(studio.duration(out) - 12) < 0.3
print("OK")
