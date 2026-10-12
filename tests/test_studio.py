"""Video studiyası: Whisper və TTS saxta, ffmpeg real."""
import os, sys, json, shutil, tempfile, types
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-test"); os.environ["DATA_DIR"] = tempfile.mkdtemp()
from langchain_core.runnables import RunnableLambda
from backend import chains, studio, tts, config
chains.translate_batch_chain = RunnableLambda(lambda x: {"items": [{"id": it["id"], "tr": "AZ " + it["text"]} for it in json.loads(x["lines"])]})
chains.analysis_chain = RunnableLambda(lambda x: {"topic": "Test", "register": "neutral"})
chains.shorten_chain = RunnableLambda(lambda x: {"items": []})
W = [("Hello", 0.5), ("everyone,", 0.9), ("welcome", 1.3), ("to", 1.6), ("the", 1.7), ("lesson.", 2.0),
     ("Today", 4.0), ("we", 4.3), ("learn", 4.5), ("Python", 4.9), ("basics.", 5.4), ("Let's", 8.0), ("start", 8.3), ("now.", 8.6)]
class FakeOpenAI:
    def __init__(self, **k):
        self.audio = types.SimpleNamespace(transcriptions=types.SimpleNamespace(create=lambda **kw: types.SimpleNamespace(
            language="english", words=[types.SimpleNamespace(word=w, start=t, end=t + 0.3) for w, t in W])))
studio.OpenAI = FakeOpenAI
BEEP = sys.argv[1]
def fake_synth(text, voice="nova", lang="az", register="neutral", slot=None, **kw):
    key = tts._key(text, voice, lang, register, 1.0, "mock"); config.TTS_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy(BEEP, tts.clip_path(key)); return key
tts.synth = fake_synth
data = open(sys.argv[2], "rb").read()
job = studio.new_job("talk.mp4", data)
sents, lang = studio.transcribe(job, on_step=print)
print("sentences:", [s["src"] for s in sents], lang)
res = studio.translate(job, sents, "Python dərsi", "az", "sub", {})
out = studio.subtitled_video(job, "az"); print("sub video:", out.name, out.stat().st_size, round(studio.duration(out), 1))
res = studio.translate(job, sents, "Python dərsi", "az", "dub", {})
out2 = studio.dubbed_video(job, res, "az", "nova", on_step=print); print("dub video:", out2.name, out2.stat().st_size, round(studio.duration(out2), 1))
r = studio.subprocess.run([studio.ffmpeg_bin(), "-hide_banner", "-i", str(out2)], capture_output=True).stderr.decode()
print("streams:", [l.strip()[:60] for l in r.splitlines() if "Stream #" in l])
