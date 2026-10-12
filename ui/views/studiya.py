"""Studiya: altyazı faylını (SRT/VTT) və ya YouTube transkriptini tərcümə et, SRT yüklə, dublyajı dinlə.

Uzantının istifadə etdiyi eyni LCEL chain işləyir — burada hər addım görünür.
"""
import html
import re

import streamlit as st

import common
from backend import chains, config, db, segments, tts

ss = st.session_state
u = db.get_user(ss.user)
common.page_header("Studiya", "Altyazı faylını və ya YouTube-dan kopyaladığın transkripti yüklə — tərcümə olunmuş SRT "
                              "faylı və dublyaj səsi al. Öz videon üçün hazır altyazı.")


def parse_transcript(text: str) -> list[dict]:
    """YouTube «Transkripti göstər» mətni: vaxt sətri, sonra mətn sətri."""
    lines = [l.strip() for l in text.replace("\r", "").split("\n") if l.strip()]
    cues, t = [], None
    for l in lines:
        m = re.fullmatch(r"(?:(\d+):)?(\d{1,2}):(\d{2})", l)
        if m:
            t = int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        elif t is not None:
            cues.append({"s": float(t), "t": l})
            t = None
    for a, b in zip(cues, cues[1:]):
        a["e"] = b["s"]
    if cues:
        cues[-1]["e"] = cues[-1]["s"] + 4
    return cues


src_tab, paste_tab = st.tabs(["SRT / VTT faylı", "YouTube transkripti"])
cues = []
with src_tab:
    f = st.file_uploader("Altyazı faylı", type=["srt", "vtt"], label_visibility="collapsed")
    if f:
        cues = segments.parse_srt(f.read().decode("utf-8", errors="ignore"))
with paste_tab:
    st.caption("YouTube-da videonun altında «…» → «Transkripti göstər», mətni seç, kopyala və bura yapışdır.")
    txt = st.text_area("Transkript", height=160, label_visibility="collapsed", placeholder="0:00\nHello everyone…\n0:04\n…")
    if txt and not cues:
        cues = parse_transcript(txt)

c1, c2, c3 = st.columns([2, 1, 1])
title = c1.text_input("Video adı", placeholder="məs. Neural networks explained", help="Kontekst üçün — tərcümə keyfiyyətini artırır")
lang = c2.selectbox("Dil", list(config.LANGS), index=list(config.LANGS).index(u.get("lang") or "az"),
                    format_func=lambda k: config.LANG_NAMES_AZ[k])
mode = c3.selectbox("Məqsəd", ["sub", "dub"], format_func=lambda m: {"sub": "Altyazı", "dub": "Dublyaj (qısa)"}[m])

if cues:
    st.caption(f"{len(cues)} sətir oxundu.")
if st.button("Tərcümə et", type="primary", icon=":material/translate:", disabled=not cues):
    if not config.OPENAI_API_KEY:
        st.error("`.env` faylında OPENAI_API_KEY yoxdur.")
        st.stop()
    with st.status("Tərcümə gedir…", expanded=True) as status:
        sents = segments.to_sentences(segments.words_from_cues(cues))
        st.write(f"1. {len(cues)} sətir → {len(sents)} cümlə birləşdirildi (tərcümə üçün tam cümlə lazımdır)")
        st.write("2. Kontekst analizi: mövzu, üslub, toxunulmaz terminlər…")
        a = chains._safe_analysis({"segments": sents, "title": title, "lang": lang})
        st.write(f"   → {a['topic'] or '—'} · üslub: {a['register']} · terminlər: {', '.join(a['keep_terms'][:6]) or '—'}")
        n = -(-len(sents) // config.TRANSLATE_BATCH)
        st.write(f"3. {n} paket paralel tərcümə olunur (eyni anda {config.MAX_CONCURRENCY})" +
                 (", sonra vaxta sığmayanlar qısaldılır" if mode == "dub" else ""))
        try:
            res = chains.translate_chain.invoke({"segments": sents, "title": title, "lang": lang, "mode": mode,
                                                 "glossary": db.glossary(u["username"]), "analysis": a})
        except Exception as e:
            status.update(label="Alınmadı", state="error")
            st.error(str(e))
            st.stop()
        m = res["meta"]
        st.write(f"4. Hazırdır: {m['translated']}/{m['count']} cümlə" +
                 (f", {m['shortened']} cümlə qısaldıldı" if mode == "dub" else ""))
        status.update(label="Tərcümə hazırdır", state="complete", expanded=False)
    ss.studio = {"res": res, "lang": lang, "mode": mode, "title": title or "video"}

res = ss.get("studio", {}).get("res")
if res:
    segs, meta = res["segments"], res["meta"]
    common.h2("Nəticə")
    d1, d2, d3 = st.columns(3)
    name = re.sub(r"[^\w-]+", "_", ss.studio["title"]).strip("_")[:40] or "video"
    d1.download_button("Tərcümə SRT", segments.to_srt(segs, "tr").encode("utf-8"), f"{name}.{ss.studio['lang']}.srt",
                       icon=":material/download:", width="stretch")
    dual = [{**s, "both": f"{s['tr']}\n{s['src']}"} for s in segs]
    d2.download_button("İkidilli SRT", segments.to_srt(dual, "both").encode("utf-8"), f"{name}.dual.srt",
                       icon=":material/download:", width="stretch")
    if d3.button("İlk 3 cümləni səsləndir", icon=":material/record_voice_over:", width="stretch"):
        with st.spinner("Səs yaradılır…"):
            ss.studio["clips"] = [(s, tts.synth(s["tr"], u.get("voice") or "nova", ss.studio["lang"],
                                                meta.get("register", "neutral"))) for s in segs[:3]]
    for s, key in ss.studio.get("clips", []):
        st.caption(f"{common.tc(s['s'])} · {s['tr']}")
        st.audio(str(tts.clip_path(key)), format="audio/mp3")

    rows = []
    for s in segs[:400]:
        fit = s.get("fit")
        col = "" if fit is None else (common.OK if fit <= 1.05 else ("#B7791F" if fit <= 1.3 else common.BAD))
        rows.append(f'<div class="seg"><div class="tc">{common.tc(s["s"])}</div><div>{html.escape(s["src"])}</div>'
                    f'<div><b>{html.escape(s["tr"])}</b></div>'
                    f'<div class="fit" style="color:{col}">{"" if fit is None else f"{fit:.2f}"}</div></div>')
    if meta.get("mode") == "dub":
        st.caption("Sağdakı rəqəm: cümlənin vaxta sığması (1.00 = tam sığır; 1.3-dən çox olanlar sürətli oxunacaq).")
    st.markdown("".join(rows), unsafe_allow_html=True)
