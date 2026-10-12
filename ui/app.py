"""DubLens paneli. İşə sal: streamlit run ui/app.py

Giriş → Panel · Lüğət · Kartlar · Studiya · Uzantı · Ayarlar (st.navigation, yuxarıda).
Panel backend-in verilənlər bazası ilə birbaşa işləyir (backend/db.py).
"""
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "ui"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

st.set_page_config(page_title="DubLens", page_icon="🎬", layout="wide")

import common  # noqa: E402
from backend import db  # noqa: E402

db.init()
common.inject_css()
ss = st.session_state

if not ss.get("user"):
    import login  # noqa: E402
    login.render()
    common.footer()
    st.stop()

u = db.get_user(ss.user)
if not u:                       # hesab silinib və ya baza dəyişib
    ss.clear()
    st.rerun()

pages = [
    st.Page("views/panel.py", title="Panel", icon=":material/movie:", default=True),
    st.Page("views/video.py", title="Video", icon=":material/video_file:"),
    st.Page("views/lugat.py", title="Lüğət", icon=":material/book_2:"),
    st.Page("views/kartlar.py", title="Kartlar", icon=":material/style:"),
    st.Page("views/studiya.py", title="Studiya", icon=":material/subtitles:"),
    st.Page("views/uzanti.py", title="Uzantı", icon=":material/extension:"),
    st.Page("views/ayarlar.py", title="Ayarlar", icon=":material/tune:"),
]
nav = st.navigation(pages, position="top")

with st.sidebar:
    st.markdown('<div class="brand"><span class="mark">D</span>DubLens</div>'
                '<div class="brand-sub">Videonu öz dilində izlə, sözləri yadda saxla</div>', unsafe_allow_html=True)
    st.markdown(f"**{u['name']}**  \n@{u['username']}")
    s = db.stats(u["username"])
    st.caption(f"{s['videos']} video · {s['words']} söz · {s['streak']} gün ardıcıl")
    if st.button("Çıxış", icon=":material/logout:", width="stretch"):
        ss.clear()
        st.rerun()

nav.run()
common.footer()
