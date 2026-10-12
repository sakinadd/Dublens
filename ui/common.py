"""DubLens panelinin ortaq hissələri: stil, başlıq, film kadrı, köməkçilər."""
import html
import re

import streamlit as st

INK, SUN, PAPER, LINE, MUTED, OK, BAD = "#0D0D12", "#FFD23F", "#FFFFFF", "#E6E6EA", "#62626E", "#1A7F4B", "#C0362C"


def inject_css():
    st.markdown(f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Unbounded:wght@500;700;800&family=Onest:wght@400;500;600;700&display=swap');
:root {{--ink:{INK}; --sun:{SUN}; --line:{LINE}; --muted:{MUTED};
        --display:'Unbounded', system-ui, sans-serif; --ui:'Onest', system-ui, sans-serif;}}
html, body, .stMarkdown, .stMarkdown p, label, input, textarea, button p, [data-testid="stMetricLabel"],
[data-testid="stCaptionContainer"], [data-testid="stPageLink"] p, .stTabs button p {{font-family: var(--ui) !important;}}
h1, h2, h3, [data-testid="stMetricValue"] {{font-family: var(--display) !important; letter-spacing: -.02em;}}
.stApp {{background: #fff;}}
.block-container {{max-width: 1120px; padding-top: 4rem; padding-bottom: 4rem;}}
[data-testid="stSidebar"] {{background: var(--ink);}}
[data-testid="stSidebar"] * {{color: #EDEDF2;}}
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] {{background: #1d1d26; border-color: #33333f;}}
.stButton button, .stDownloadButton button, .stFormSubmitButton button {{border-radius: 10px; font-weight: 600;}}
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"] {{
  background: var(--ink) !important; border-color: var(--ink) !important; color: #fff !important;}}
[data-testid="stBaseButton-primary"]:hover, [data-testid="stBaseButton-primaryFormSubmit"]:hover {{
  box-shadow: inset 0 -3px 0 var(--sun);}}
button:focus-visible, a:focus-visible, input:focus-visible {{outline: 2px solid var(--ink) !important; outline-offset: 2px;}}
header [data-testid="stNavLink"][aria-current="page"], [data-testid="stTopNavLink"][aria-current="page"] {{
  box-shadow: inset 0 -3px 0 var(--sun); background: transparent !important;}}
[data-testid="stMetric"] {{border: 1px solid var(--line); border-radius: 12px; padding: 12px 14px;}}
.brand {{font-family: var(--display); font-weight: 800; font-size: 1.35rem; display: flex; align-items: center; gap: 10px;}}
.brand .mark {{width: 30px; height: 30px; border-radius: 8px; background: var(--sun); color: var(--ink) !important;
  display: inline-flex; align-items: center; justify-content: center; font-weight: 800;}}
.brand-sub {{opacity: .65; font-size: .88rem; margin: 4px 0 18px;}}
.page-title {{font-family: var(--display); font-weight: 800; font-size: 2.1rem; color: var(--ink); letter-spacing: -.03em;
  line-height: 1.12; margin: 0 0 .35rem;}}
.page-sub {{color: var(--muted); max-width: 66ch; font-size: 1.02rem; line-height: 1.55; margin-bottom: 1.3rem;}}
.h2 {{font-family: var(--display); font-weight: 700; font-size: 1.15rem; margin: 2rem 0 .7rem; color: var(--ink);}}

/* film kadrı — panelin əsas elementi */
.frame {{background: var(--ink); border-radius: 18px; padding: 26px 30px 24px; color: #fff; position: relative;
  overflow: hidden; min-height: 230px; display: flex; flex-direction: column; justify-content: flex-end;}}
.frame::before, .frame::after {{content: ""; position: absolute; left: 0; right: 0; height: 12px;
  background: repeating-linear-gradient(90deg, #22222c 0 14px, transparent 14px 26px);}}
.frame::before {{top: 10px;}} .frame::after {{bottom: 10px;}}
.frame .meta {{position: absolute; top: 34px; left: 30px; right: 30px; display: flex; justify-content: space-between;
  font-size: .85rem; color: #9b9baa;}}
.frame .tc {{font-variant-numeric: tabular-nums; color: var(--sun);}}
.frame .line-tr {{font-size: 1.55rem; font-weight: 600; line-height: 1.45; text-align: center; margin: 0 auto 8px; max-width: 34ch;}}
.frame .line-src {{font-size: 1.02rem; color: #cfcfd8; text-align: center; margin: 0 auto 20px; max-width: 60ch;}}
.frame mark {{background: var(--sun); color: var(--ink); padding: 0 .18em; border-radius: 4px;}}
.frame .word {{text-align: center; font-family: var(--display); font-size: .95rem; color: #fff; opacity: .9;}}
.frame .word b {{color: var(--sun);}}

.vrow {{display: grid; grid-template-columns: 1fr auto; gap: 4px 16px; padding: 12px 0; border-bottom: 1px solid var(--line);}}
.vrow .t {{font-weight: 600; color: var(--ink);}} .vrow .m {{color: var(--muted); font-size: .88rem;}}
.vrow a {{color: var(--ink); text-decoration: none; border-bottom: 2px solid var(--sun);}}
.wcard {{border: 1px solid var(--line); border-radius: 14px; padding: 14px 16px; margin-bottom: 10px; background: #fff;}}
.wcard .w {{font-family: var(--display); font-weight: 700; font-size: 1.15rem;}}
.wcard .tr {{font-weight: 600; margin-left: 8px; color: var(--ink);}}
.wcard .pos {{color: var(--muted); font-size: .8rem; margin-left: 6px;}}
.wcard .s {{color: #3b3b46; margin-top: 6px;}} .wcard .s mark {{background: #FFF1B3; padding: 0 .12em; border-radius: 3px;}}
.wcard .st {{color: var(--muted); font-style: italic; font-size: .92rem;}}
.box {{display: inline-flex; gap: 3px; vertical-align: middle; margin-left: 8px;}}
.box i {{width: 9px; height: 9px; border-radius: 2px; background: #E6E6EA; display: inline-block;}}
.box i.on {{background: var(--ink);}}
.flash {{border: 2px solid var(--ink); border-radius: 18px; padding: 34px 30px; text-align: center; background: #fff;
  box-shadow: 6px 6px 0 var(--sun);}}
.flash .w {{font-family: var(--display); font-weight: 800; font-size: 2.4rem; letter-spacing: -.02em;}}
.flash .s {{color: var(--muted); margin-top: 10px; font-size: 1.05rem;}}
.flash .a {{font-size: 1.6rem; font-weight: 700; margin-top: 16px;}}
.seg {{display: grid; grid-template-columns: 70px 1fr 1fr 48px; gap: 12px; padding: 9px 0; border-bottom: 1px solid var(--line);
  font-size: .94rem; align-items: start;}}
.seg .tc {{font-variant-numeric: tabular-nums; color: var(--muted);}}
.seg .fit {{text-align: right; font-weight: 700; font-variant-numeric: tabular-nums;}}
.steps li {{margin-bottom: .55rem; line-height: 1.5;}}
.footer {{margin-top: 3rem; padding-top: 1rem; border-top: 1px solid var(--line); color: #9b9baa; font-size: .82rem;}}
@media (max-width: 760px) {{.seg {{grid-template-columns: 56px 1fr;}} .seg .fit {{display: none;}}
  .frame .line-tr {{font-size: 1.2rem;}}}}
</style>""", unsafe_allow_html=True)


def page_header(title: str, sub: str = ""):
    st.markdown(f'<div class="page-title">{html.escape(title)}</div>'
                + (f'<div class="page-sub">{html.escape(sub)}</div>' if sub else ""), unsafe_allow_html=True)


def h2(text: str):
    st.markdown(f'<div class="h2">{html.escape(text)}</div>', unsafe_allow_html=True)


def tc(sec: float) -> str:
    sec = int(sec or 0)
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60:02d}:{sec % 60:02d}"


def mark_word(sentence: str, word: str) -> str:
    s = html.escape(sentence or "")
    w = html.escape(word or "")
    if not w:
        return s
    return re.sub(rf"(?i)\b({re.escape(w)})\b", r"<mark>\1</mark>", s, count=1)


def box_html(box: int) -> str:
    return '<span class="box" title="Yaddaş qutusu ' + str(box) + '/5">' + "".join(
        f'<i class="{"on" if i <= box else ""}"></i>' for i in range(1, 6)) + "</span>"


def yt_link(video_id: str, t: float = 0) -> str:
    return f"https://www.youtube.com/watch?v={video_id}" + (f"&t={int(t)}s" if t else "")


def footer():
    st.markdown('<div class="footer">DubLens · tərcümə və dublyaj AI tərəfindən edilir (OpenAI, ElevenLabs). '
                'Yüklədiyin videolar yalnız sənin serverində saxlanılır.</div>', unsafe_allow_html=True)
