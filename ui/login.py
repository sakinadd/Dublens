"""Giriş və qeydiyyat. Qeydiyyatda email məcburidir — səhər kartları ora gəlir (n8n)."""
import streamlit as st

from backend import db, events

HOURS = list(range(6, 24))


def _enter(u: dict):
    st.session_state.user = u["username"]
    st.rerun()


def render():
    st.markdown("""<style>
      [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] {display:none;}
      .block-container {max-width: 1060px; padding-top: 8vh;}
      .lg-title {font-family: var(--display); font-weight: 800; font-size: 2.9rem; letter-spacing: -.04em;
                 line-height: 1.05; color: var(--ink); margin: 14px 0 12px;}
      .lg-lead {color: var(--muted); font-size: 1.1rem; line-height: 1.6; max-width: 42ch; margin-bottom: 22px;}
    </style>""", unsafe_allow_html=True)
    left, _, right = st.columns([1.15, .1, 1], vertical_alignment="center")
    with left:
        st.markdown('<div class="brand" style="font-size:1.5rem"><span class="mark">D</span>DubLens</div>'
                    '<div class="lg-title">İngiliscə video.<br>Azərbaycanca baxış.</div>'
                    '<div class="lg-lead">Chrome uzantısı YouTube videosunu sənin dilində altyazı və ya dublyajla '
                    'göstərir. Bilmədiyin sözə klikləyirsən — lüğətə düşür, səhər emailinə kart kimi gəlir.</div>',
                    unsafe_allow_html=True)
        st.markdown('<div class="frame" style="min-height:215px"><div class="meta"><span>Neural networks, explained'
                    '</span><span class="tc">04:12</span></div><div class="line-tr">Sonra bu neyronları bir-birinin '
                    'üstünə <mark>yığırıq</mark>.</div><div class="line-src" style="margin-bottom:6px">Then we '
                    '<mark>stack</mark> many of them together.</div></div>', unsafe_allow_html=True)
    with right, st.container(border=True):
        t_in, t_up = st.tabs(["Daxil ol", "Qeydiyyat"])
        with t_in:
            with st.form("login"):
                un = st.text_input("İstifadəçi adı", autocomplete="username")
                pw = st.text_input("Şifrə", type="password", autocomplete="current-password")
                go = st.form_submit_button("Daxil ol", type="primary", width="stretch")
            if go:
                u = db.login(un, pw)
                if u:
                    _enter(u)
                st.error("İstifadəçi adı və ya şifrə yanlışdır.")
        with t_up:
            with st.form("register"):
                name = st.text_input("Adın", placeholder="Səkinə")
                un = st.text_input("İstifadəçi adı", placeholder="sakina", help="3–20 simvol: kiçik latın hərfləri, rəqəm, _ -")
                email = st.text_input("Email *", placeholder="ad@gmail.com", help="Səhər kartları bu ünvana gəlir")
                p1 = st.text_input("Şifrə", type="password", autocomplete="new-password", help="Ən azı 6 simvol")
                p2 = st.text_input("Şifrəni təkrarla", type="password", autocomplete="new-password")
                c1, c2 = st.columns(2)
                lang = c1.selectbox("Mənim dilim", ["az", "tr", "ru", "en"],
                                    format_func=lambda k: {"az": "Azərbaycan dili", "tr": "Türk dili",
                                                           "ru": "Rus dili", "en": "İngilis dili"}[k])
                hour = c2.selectbox("Səhər kartları", HOURS, index=HOURS.index(8), format_func=lambda h: f"{h:02d}:00")
                go = st.form_submit_button("Hesab yarat", type="primary", width="stretch")
            if go:
                if p1 != p2:
                    st.error("Şifrələr eyni deyil.")
                else:
                    ok, msg = db.register(un, p1, name, email, hour, lang)
                    if ok:
                        u = db.login(un, p1)
                        events.profile(u)
                        _enter(u)
                    st.error(msg)
        st.caption("Şifrə açıq saxlanmır (PBKDF2 hash). Uzantı ayrıca tokenlə qoşulur.")
