"""Uzantı: Chrome-a quraşdırma addımları, token, server yoxlaması."""
import requests
import streamlit as st

import common
from backend import config, db

u = db.get_user(st.session_state.user)
common.page_header("Uzantı", "Chrome uzantısı YouTube-da işləyir və bu panelə tokenlə qoşulur.")

left, right = st.columns([3, 2], gap="large")
with left:
    common.h2("Quraşdırma (2 dəqiqə)")
    st.markdown(f"""<ol class="steps">
<li>Chrome-da ünvan sətrinə <code>chrome://extensions</code> yaz və aç.</li>
<li>Sağ yuxarıda <b>Developer mode</b> (Tərtibatçı rejimi) düyməsini aç.</li>
<li><b>Load unpacked</b> bas və bu qovluğu seç: <code>{config.ROOT / 'extension'}</code></li>
<li>Uzantılar ikonunda (pazl) DubLens-i sancaqla, sonra onu aç.</li>
<li><b>Bağlantı</b> bölməsində server ünvanını və aşağıdakı tokeni yapışdır, <b>Yadda saxla və yoxla</b> bas.</li>
<li>YouTube-da istənilən videonu aç — DubLens özü işə düşür. <kbd>Alt</kbd>+<kbd>D</kbd> aç/bağla.</li>
</ol>""", unsafe_allow_html=True)
with right:
    common.h2("Sənin tokenin")
    st.code(u["token"], language=None)
    st.caption("Bu token şifrə kimidir — paylaşma. Uzantı onunla sənin hesabına yazır.")
    if st.button("Yeni token yarat", icon=":material/autorenew:"):
        db.new_token(u["username"])
        st.toast("Yeni token yaradıldı — uzantıda da yenilə.")
        st.rerun()
    common.h2("Server")
    backend = st.text_input("Server ünvanı", value="http://localhost:8000")
    if st.button("Yoxla", icon=":material/network_check:"):
        try:
            r = requests.get(backend.rstrip("/") + "/health", timeout=4).json()
            st.success(f"Server işləyir · model {r['model']}")
        except Exception:
            st.error("Server cavab vermir. Terminalda backend-i işə sal: "
                     "`uvicorn backend.main:app --port 8000`")
