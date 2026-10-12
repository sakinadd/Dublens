import os, sys, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["N8N_EVENT_WEBHOOK"] = ""
from langchain_core.runnables import RunnableLambda
from backend import config, chains, segments, db
config.N8N_EVENT_WEBHOOK = ""

# --- json3 avtomatik altyazı nümunəsi
words = "so today we are going to talk about machine learning and why it matters for your career".split() + \
        "first let me show you the basics. neural networks are simple ideas stacked together".split()
events, t = [], 1000
for i in range(0, len(words), 4):
    segs = [{"utf8": (" " if j else "") + w, "tOffsetMs": j * 300} for j, w in enumerate(words[i:i+4])]
    events.append({"tStartMs": t, "dDurationMs": 1600, "segs": segs})
    events.append({"tStartMs": t + 1500, "dDurationMs": 10, "segs": [{"utf8": "\n"}]})
    t += 1300 if i != 16 else 2500
sample = {"events": events}
ws = segments.words_from_json3(sample)
sents = segments.to_sentences(ws)
print("words", len(ws), "sentences", len(sents)); [print(" ", s) for s in sents]
assert all(a["e"] <= b["s"] for a, b in zip(sents, sents[1:]))

calls = {"tr": 0}
def fake_tr(x):
    calls["tr"] += 1
    items = json.loads(x["lines"])
    # birini buraxırıq — ikinci keçid yoxlanılsın
    out = [{"id": it["id"], "tr": "AZ: " + it["text"] * (3 if x["purpose"].startswith("dub") else 1)} for it in items]
    if calls["tr"] == 1 and len(out) > 1: out = out[1:]
    return {"items": out}
chains.translate_batch_chain = RunnableLambda(fake_tr)
chains.analysis_chain = RunnableLambda(lambda x: {"topic": "Maşın öyrənməsi", "domain": "tech", "register": "informal", "keep_terms": ["Python"]})
chains.shorten_chain = RunnableLambda(lambda x: {"items": [{"id": it["id"], "tr": it["tr"][:it["max_chars"]]} for it in json.loads(x["lines"])]})
chains.word_chain = RunnableLambda(lambda x: {"lemma": x["word"].lower(), "translation": "öyrənmə", "pos": "noun", "sentence_tr": "AZ cümlə", "example": "I learn.", "example_tr": "Öyrənirəm."})
chains.line_chain = RunnableLambda(lambda x: {"tr": "AZ " + x["line"]})

r = chains.translate_chain.invoke({"segments": sents, "title": "ML", "lang": "az", "mode": "sub", "glossary": {"career": "karyera"}})
print("sub meta", r["meta"]); assert all(s["ok"] for s in r["segments"]), "missing ids not retried"
r2 = chains.translate_chain.invoke({"segments": sents, "title": "ML", "lang": "az", "mode": "dub", "glossary": {}})
print("dub shortened", r2["meta"]["shortened"], [s["fit"] for s in r2["segments"]])

from fastapi.testclient import TestClient
from backend import main
c = TestClient(main.app)
print(db.register("sakina", "secret1", "Səkinə", "s@x.az"))
tok = db.get_user("sakina")["token"]
H = {"X-DubLens-Token": tok}
assert c.post("/api/translate", json={"video_id": "v1", "source": {"format": "json3", "data": sample}}).status_code == 401
j = c.post("/api/translate", headers=H, json={"video_id": "v1", "title": "ML", "source": {"format": "json3", "data": sample}}).json()
print("api parts", j["part"], j["parts"], j["total"], j["segments"][0]["tr"][:40], len(j["index"]))
n = calls["tr"]; c.post("/api/translate", headers=H, json={"video_id": "v1", "title": "ML", "source": {"format": "json3", "data": sample}})
assert calls["tr"] == n, "cache miss"
w = c.post("/api/word", headers=H, json={"word": "Learning,", "sentence": sents[0]["src"], "video_id": "v1", "title": "ML"}).json()
print("word", w["lemma"], w["translation"], w["box"])
print("vocab", len(c.get("/api/vocab", headers=H).json()), "me", c.get("/api/me", headers=H).json()["stats"])
srt = segments.to_srt(j["segments"]); back = segments.parse_srt(srt); print("srt roundtrip", len(back) == len(j["segments"]))
print("line", c.post("/api/line", headers=H, json={"line": "hello"}).json())
print("review", db.review(w["id"], "sakina", True))
