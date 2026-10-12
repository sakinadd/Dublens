"""Panel: son öyrəndiyin söz film kadrında, statistika, bugünkü təkrar, son videolar."""
import html
from collections import Counter
from datetime import date, timedelta

import plotly.graph_objects as go
import streamlit as st

import common
from backend import db

u = db.get_user(st.session_state.user)
s = db.stats(u["username"])
words = db.vocab(u["username"])
vids = db.videos(u["username"], 50)
due = db.due_vocab(u["username"], 200)

common.page_header(f"Salam, {u['name']}",
                   "Son izlədiklərin, öyrəndiyin sözlər və bugünkü təkrar.")

# ---- film kadrı: son saxlanılan söz öz cümləsində
if words:
    w = words[0]
    st.markdown(f"""<div class="frame">
      <div class="meta"><span>{html.escape(w.get('title') or 'Video')}</span><span class="tc">{common.tc(w.get('t'))}</span></div>
      <div class="line-tr">{html.escape(w.get('sentence_tr') or '')}</div>
      <div class="line-src">{common.mark_word(w.get('sentence'), w.get('word'))}</div>
      <div class="word"><b>{html.escape(w['lemma'])}</b> — {html.escape(w.get('translation') or '')}</div>
    </div>""", unsafe_allow_html=True)
    if w.get("video_id"):
        st.link_button("Bu anı videoda aç", common.yt_link(w["video_id"], w.get("t") or 0), icon=":material/play_arrow:")
else:
    st.markdown("""<div class="frame"><div class="meta"><span>Hələ söz yoxdur</span><span class="tc">00:00</span></div>
      <div class="line-tr">YouTube-da video aç, «İkidilli» rejimdə bilmədiyin sözə klikləyin.</div>
      <div class="line-src">Söz burada, öz cümləsi ilə görünəcək.</div></div>""", unsafe_allow_html=True)
    st.page_link("views/uzanti.py", label="Uzantını qur", icon=":material/extension:")

st.write("")
c = st.columns(5)
c[0].metric("Video", s["videos"])
c[1].metric("Dəqiqə", s["minutes"])
c[2].metric("Söz", s["words"])
c[3].metric("Mənimsənilib", s["mastered"], help="Yaddaş qutusu 4 və 5 olan sözlər")
c[4].metric("Ardıcıl gün", s["streak"])

left, right = st.columns([1, 1], gap="large")
with left:
    common.h2("Bu gün təkrar")
    if due:
        st.markdown(f"**{len(due)}** sözün təkrar vaxtı çatıb. 3 dəqiqəlik işdir.")
        st.page_link("views/kartlar.py", label="Kartlara başla", icon=":material/style:")
    else:
        st.markdown("Bu gün təkrarlanacaq söz yoxdur." + (" Yeni video izlə." if not words else " Sabah yenə bax."))
    # son 14 gündə saxlanan sözlər
    days = Counter((w["created"] or "")[:10] for w in words)
    span = [(date.today() - timedelta(days=i)).isoformat() for i in range(13, -1, -1)]
    fig = go.Figure(go.Bar(x=[d[5:] for d in span], y=[days.get(d, 0) for d in span], marker_color=common.INK,
                           hovertemplate="%{x}: %{y} söz<extra></extra>"))
    fig.update_layout(height=190, margin=dict(l=4, r=4, t=8, b=4), paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)", font=dict(family="Onest", color=common.MUTED, size=11),
                      yaxis=dict(gridcolor="#EFEFF2", dtick=1 if max(days.values() or [0]) < 6 else None),
                      xaxis=dict(showgrid=False))
    st.caption("Son 14 gündə saxlanılan sözlər")
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
with right:
    common.h2("Son videolar")
    if not vids:
        st.caption("Uzantı ilə izlədiyin videolar burada görünəcək.")
    for v in vids[:7]:
        mode = {"sub": "altyazı", "dub": "dublyaj"}.get(v["mode"], v["mode"])
        st.markdown(f'<div class="vrow"><div class="t"><a href="{common.yt_link(v["video_id"])}" target="_blank">'
                    f'{html.escape(v["title"] or v["video_id"])}</a></div><div class="m">{common.tc(v["seconds"])}</div>'
                    f'<div class="m">{html.escape(v.get("topic") or "")}</div><div class="m">{mode} · {v["lang"]}</div></div>',
                    unsafe_allow_html=True)
