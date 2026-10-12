import os, sys, json, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "ui")]
os.environ.setdefault("OPENAI_API_KEY", "sk-test"); os.environ["DATA_DIR"] = tempfile.mkdtemp(); os.environ["N8N_EVENT_WEBHOOK"] = ""
from langchain_core.runnables import RunnableLambda
from backend import chains, db, config, events
config.N8N_EVENT_WEBHOOK = ""
chains.translate_batch_chain = RunnableLambda(lambda x: {"items": [{"id": it["id"], "tr": "AZ " + it["text"]} for it in json.loads(x["lines"])]})
chains.analysis_chain = RunnableLambda(lambda x: {"topic": "Test", "register": "neutral", "keep_terms": ["YouTube"]})
from streamlit.testing.v1 import AppTest
APP = os.path.join(ROOT, "ui", "app.py")
at = AppTest.from_file(APP, default_timeout=30); at.run()
print("login tabs:", [t.label for t in at.tabs], at.exception)
ti = at.text_input
ti[2].set_value("Səkinə"); ti[3].set_value("sakina"); ti[4].set_value("s@x.az"); ti[5].set_value("secret1"); ti[6].set_value("secret1")
[b for b in at.button if b.label == "Hesab yarat"][0].click().run()
print("logged:", at.session_state["user"], at.exception)
db.add_vocab("sakina", {"word": "stack", "lemma": "stack", "translation": "yığmaq", "pos": "verb", "sentence": "Then we stack them.", "sentence_tr": "Sonra onları yığırıq.", "video_id": "abc", "title": "NN", "t": 252})
db.add_video("sakina", "abc", "Neural networks", "az", "sub", [{"s": 0, "e": 600}], "Neyron şəbəkələr")
for page in ["views/panel.py", "views/lugat.py", "views/kartlar.py", "views/studiya.py", "views/uzanti.py", "views/ayarlar.py"]:
    a = AppTest.from_file(APP, default_timeout=30); a.session_state["user"] = "sakina"; a.run(); a.switch_page(page); a.run()
    print(page, "EXC " + str(a.exception[0].message)[:200] if a.exception else "ok")
# kartlar axını
a = AppTest.from_file(APP, default_timeout=30); a.session_state["user"] = "sakina"; a.run(); a.switch_page("views/kartlar.py"); a.run()
[b for b in a.button if b.label == "Cavabı göstər"][0].click().run()
[b for b in a.button if b.label == "Bildim"][0].click().run()
print("after review box:", db.vocab("sakina")[0]["box"], [s.value for s in a.success][:1])
# studiya: transkript yapışdır və tərcümə et
a = AppTest.from_file(APP, default_timeout=30); a.session_state["user"] = "sakina"; a.run(); a.switch_page("views/studiya.py"); a.run()
a.text_area[0].set_value("0:00\nHello everyone and welcome.\n0:03\nToday we talk about YouTube.\n0:07\nLet us start.").run()
[b for b in a.button if b.label == "Tərcümə et"][0].click().run()
print("studio:", a.exception, [d.label for d in a.get("download_button")])
