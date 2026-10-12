"""Lüğət: videolardan saxlanılan sözlər öz cümlələri ilə; axtarış, filtr, CSV, silmək."""
import html

import pandas as pd
import streamlit as st

import common
from backend import db

u = db.get_user(st.session_state.user)
words = db.vocab(u["username"])
common.page_header("Lüğət", "Videolarda klikləyib saxladığın sözlər — hər biri eşitdiyin cümlə və anla birlikdə.")

if not words:
    st.info("Hələ söz yoxdur. Uzantıda «İkidilli» rejimi seç və orijinal altyazıdakı sözə kliklə.")
    st.stop()

c1, c2, c3 = st.columns([2, 1, 1])
q = c1.text_input("Axtar", placeholder="söz, tərcümə və ya video adı", label_visibility="collapsed")
level = c2.selectbox("Səviyyə", ["Hamısı", "Yeni (1–2)", "Öyrənilir (3)", "Mənimsənilib (4–5)"],
                     label_visibility="collapsed")
df = pd.DataFrame(words)[["lemma", "translation", "pos", "sentence", "sentence_tr", "title", "video_id", "t", "box", "created"]]
c3.download_button("CSV yüklə", df.to_csv(index=False).encode("utf-8"), "dublens_lugat.csv", "text/csv",
                   icon=":material/download:", width="stretch")

ql = (q or "").lower().strip()
rng = {"Yeni (1–2)": (1, 2), "Öyrənilir (3)": (3, 3), "Mənimsənilib (4–5)": (4, 5)}.get(level, (1, 5))
shown = [w for w in words if rng[0] <= w["box"] <= rng[1]
         and (not ql or ql in (w["lemma"] + " " + (w["translation"] or "") + " " + (w["title"] or "")).lower())]
st.caption(f"{len(shown)} / {len(words)} söz")

for w in shown[:200]:
    with st.container():
        a, b = st.columns([12, 1], vertical_alignment="center")
        a.markdown(f"""<div class="wcard"><span class="w">{html.escape(w['lemma'])}</span>
          <span class="tr">{html.escape(w['translation'] or '')}</span><span class="pos">{html.escape(w['pos'] or '')}</span>
          {common.box_html(w['box'])}
          <div class="s">{common.mark_word(w['sentence'], w['word'])}</div>
          <div class="st">{html.escape(w['sentence_tr'] or '')}</div>
          <div class="pos" style="margin:6px 0 0">{html.escape(w['title'] or '')} · {common.tc(w['t'])}
          {' · <a href="' + common.yt_link(w['video_id'], w['t']) + '" target="_blank">videoda aç</a>' if w['video_id'] else ''}</div>
        </div>""", unsafe_allow_html=True)
        if b.button("", icon=":material/delete:", key=f"del{w['id']}", help="Lüğətdən sil"):
            db.delete_vocab(w["id"], u["username"])
            st.rerun()
