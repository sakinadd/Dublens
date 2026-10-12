"""Kartlar: Leitner sistemi (5 qutu). Bilsən söz növbəti qutuya keçir və daha gec qayıdır, bilməsən 1-ci qutuya."""
import html

import streamlit as st

import common
from backend import db

ss = st.session_state
u = db.get_user(ss.user)
common.page_header("Kartlar", "Vaxtı çatan sözlər. Əvvəl özün xatırla, sonra cavabı aç və dürüst qiymət ver.")

if "deck" not in ss or ss.get("deck_user") != u["username"]:
    ss.deck, ss.deck_user, ss.flip, ss.score = db.due_vocab(u["username"], 20), u["username"], False, [0, 0]

deck = ss.deck
if not deck:
    done = sum(ss.score)
    if done:
        st.success(f"Bu günlük bitdi: {ss.score[0]} / {done} düzgün. Sabah yeni kartlar gələcək.")
    else:
        st.info("Bu gün təkrarlanacaq söz yoxdur.")
    if st.button("Yenidən yoxla", icon=":material/refresh:"):
        ss.pop("deck", None)
        st.rerun()
    st.stop()

w = deck[0]
st.progress(sum(ss.score) / (sum(ss.score) + len(deck)), text=f"{len(deck)} kart qalıb")
blank = common.mark_word(w["sentence"], w["word"]).replace("<mark>", "<mark style='background:#FFF1B3'>")
answer = ""
if ss.flip:
    answer = (f'<div class="a">{html.escape(w["translation"] or "")}</div>'
              f'<div class="s">{html.escape(w["sentence_tr"] or "")}</div>'
              + (f'<div class="s" style="font-size:.92rem">{html.escape(w["example"])}</div>' if w.get("example") else ""))
st.markdown(f'<div class="flash"><div class="w">{html.escape(w["lemma"])}</div>'
            f'<div class="s">{blank}</div>{answer}</div>', unsafe_allow_html=True)
st.write("")
if not ss.flip:
    if st.button("Cavabı göstər", type="primary", width="stretch", icon=":material/visibility:"):
        ss.flip = True
        st.rerun()
else:
    a, b = st.columns(2)
    if a.button("Bilmədim", width="stretch", icon=":material/close:"):
        db.review(w["id"], u["username"], False)
        ss.score[1] += 1
        ss.deck, ss.flip = deck[1:], False
        st.rerun()
    if b.button("Bildim", type="primary", width="stretch", icon=":material/check:"):
        r = db.review(w["id"], u["username"], True)
        ss.score[0] += 1
        ss.deck, ss.flip = deck[1:], False
        st.toast(f"«{w['lemma']}» qutu {r['box']}-ə keçdi, növbəti təkrar {r['due']}", icon=":material/trending_up:")
        st.rerun()
st.caption(f"Yaddaş qutusu: {w['box']}/5 · {w.get('title') or ''}")
