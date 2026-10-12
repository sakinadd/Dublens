"""Ayarlar: profil, səhər kartları (n8n), dil və səs, terminlər lüğəti."""
import pandas as pd
import streamlit as st

import common
from backend import config, db, events, status

u = db.get_user(st.session_state.user)
common.page_header("Ayarlar", "Profil, səhər emaili və tərcümədə toxunulmaz qalan terminlər.")

left, right = st.columns(2, gap="large")
with left:
    common.h2("Profil və səhər kartları")
    with st.form("profile"):
        name = st.text_input("Ad", value=u["name"])
        email = st.text_input("Email", value=u["email"] or "")
        hours = list(range(6, 24))
        c1, c2 = st.columns(2)
        on = c1.toggle("Səhər kartları emaili", value=bool(u["remind_on"]))
        hour = c2.selectbox("Saat", hours, index=hours.index(u["remind_hour"]) if u["remind_hour"] in hours else 2,
                            format_func=lambda h: f"{h:02d}:00")
        lang = st.selectbox("Mənim dilim", list(config.LANGS), index=list(config.LANGS).index(u["lang"] or "az"),
                            format_func=lambda k: config.LANG_NAMES_AZ[k])
        voice = st.selectbox("Dublyaj səsi", config.VOICES, index=config.VOICES.index(u["voice"] or "nova"))
        if st.form_submit_button("Saxla", type="primary"):
            try:
                nu = db.update_user(u["username"], name=name.strip() or u["username"], email=email.strip(),
                                    remind_on=int(on), remind_hour=hour, lang=lang, voice=voice)
                events.profile(nu)
                st.success("Saxlanıldı.")
            except ValueError as e:
                st.error(str(e))
    st.caption("Email-ə hər səhər təkrar vaxtı çatan sözlər və AI-ın yazdığı mini dərs gəlir (n8n · Ollama).")

with right:
    common.h2("Terminlər")
    st.caption("Tərcümədə necə saxlanılsın: brend, şəxs adı, ixtisas terminləri. Boş saxlasan, söz olduğu kimi qalır.")
    gl = db.glossary(u["username"])
    df = pd.DataFrame([{"Termin": k, "Tərcümə": v} for k, v in gl.items()] or [{"Termin": "", "Tərcümə": ""}])
    ed = st.data_editor(df, num_rows="dynamic", width="stretch", hide_index=True, key="gl_editor")
    if st.button("Terminləri saxla", icon=":material/save:"):
        new = {str(r["Termin"]).strip(): str(r["Tərcümə"] or "").strip() for _, r in ed.iterrows()
               if str(r["Termin"] or "").strip() and str(r["Termin"]) != "nan"}
        for k in set(gl) - set(new):
            db.delete_term(u["username"], k)
        for k, v in new.items():
            db.set_term(u["username"], k, v if v and v != "nan" else k)
        st.success(f"{len(new)} termin saxlanıldı.")

st.divider()
common.h2("Sistem vəziyyəti")
st.caption("DubLens-in istifadə etdiyi hər xidmət ayrıca yoxlanılır. Açarlar göstərilmir.")
if st.button("Yoxla", icon=":material/monitor_heart:", key="sys_check"):
    with st.spinner("Yoxlanılır…"):
        st.session_state.sys_status = status.run()
for row in st.session_state.get("sys_status", []):
    icon = "✅" if row["ok"] else "⚠️"
    a, b, c = st.columns([2, 6, 1])
    a.markdown(f"{icon} **{row['name']}**")
    b.markdown(f"<span style='color:var(--muted)'>{row['detail']}</span>", unsafe_allow_html=True)
    c.markdown(f"<span style='color:var(--muted)'>{row['ms']} ms</span>", unsafe_allow_html=True)
