"""Video: öz videonu yüklə → DubLens soruşur: dublyaj, yoxsa tərcümə (altyazı)? → hazır MP4 + SRT."""
import hashlib
import html
import time

import streamlit as st

import common
from backend import config, db, events, speakers, studio, tts

# Backend faylları dəyişəndə panel yenidən başladılmadan yeni kodu götürsün
import importlib  # noqa: E402
import os  # noqa: E402
if not os.getenv("DUBLENS_NO_RELOAD"):          # serverdə (Docker) lazım deyil
    for _m in (tts, speakers, studio):
        importlib.reload(_m)

ss = st.session_state
u = db.get_user(ss.user)
common.page_header("Video", f"Öz videonu yüklə ({studio.MAX_MINUTES} dəqiqəyə qədər) — dublyaj edək, ya da altyazı "
                            "əlavə edək. Nəticə: yükləyə biləcəyin MP4 və SRT faylı.")

st.markdown("""<style>
.choice {border: 2px solid var(--line); border-radius: 16px; padding: 18px 20px; min-height: 128px; background: #fff;}
.choice.on {border-color: var(--ink); box-shadow: 5px 5px 0 var(--sun);}
.choice b {font-family: var(--display); font-size: 1.15rem; display: block; margin-bottom: 6px; color: var(--ink);}
.choice span {color: var(--muted); line-height: 1.5;}
</style>""", unsafe_allow_html=True)

MODE_AZ = {"dub": "Dublyaj", "sub": "Altyazı"}


def show_history():
    items = studio.history(u["username"])
    if not items:
        return
    common.h2("Əvvəlki işlər")
    for i, d in enumerate(items):
        a, b, c, e = st.columns([5, 2, 2, 1.4], vertical_alignment="center")
        a.markdown(f"**{html.escape(d.get('title') or 'Video')}**  \n"
                   f"<span style='color:var(--muted)'>{d.get('topic') or ''}</span>", unsafe_allow_html=True)
        b.markdown(f"{MODE_AZ.get(d['mode'], d['mode'])} · {config.LANG_NAMES_AZ.get(d['lang'], d['lang'])}")
        c.markdown("<span style='color:var(--muted)'>" +
                   time.strftime("%d.%m %H:%M", time.localtime(d.get("created", 0))) +
                   (f" · {len(d.get('cast') or {})} danışan" if d.get("cast") else "") + "</span>",
                   unsafe_allow_html=True)
        if e.button("Aç", key=f"hist_{i}", width="stretch"):
            ss.vid_result, ss.vid_open, ss.vid_fid = d, True, None
            st.rerun()


f = st.file_uploader("Video faylı", type=["mp4", "mov", "m4v", "webm", "mkv"], label_visibility="collapsed")
if not f and not (ss.get("vid_open") and ss.get("vid_result")):
    st.info("Videonu bura at. Sonra soruşacağam: dublyaj edim, yoxsa altyazı ilə tərcümə?")
    show_history()
    st.stop()

if f:
    data = f.getvalue()
    fid = hashlib.sha1(data[:2_000_000] + str(len(data)).encode()).hexdigest()[:12]
    if ss.get("vid_fid") != fid:                  # yeni video — köhnə nəticəni unut
        ss.vid_fid, ss.vid_job, ss.vid_result, ss.vid_choice = fid, str(studio.new_job(f.name, data)), None, None
        ss.vid_open = False
    job = studio.Path(ss.vid_job)

if not ss.vid_result:
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.video(data)
    with right:
        common.h2("Bu videonu nə edək?")
        c1, c2 = st.columns(2)
        ch = ss.get("vid_choice")
        c1.markdown(f'<div class="choice {"on" if ch == "dub" else ""}"><b>Dublyaj</b><span>Video seçdiyin dildə '
                    'danışır, orijinal səs arxa fonda qalır.</span></div>', unsafe_allow_html=True)
        c2.markdown(f'<div class="choice {"on" if ch == "sub" else ""}"><b>Tərcümə</b><span>Səs olduğu kimi qalır, '
                    'videoya altyazı əlavə olunur.</span></div>', unsafe_allow_html=True)
        if c1.button("Dublyaj et", icon=":material/record_voice_over:", width="stretch",
                     type="primary" if ch == "dub" else "secondary"):
            ss.vid_choice = "dub"
            st.rerun()
        if c2.button("Tərcümə et", icon=":material/subtitles:", width="stretch",
                     type="primary" if ch == "sub" else "secondary"):
            ss.vid_choice = "sub"
            st.rerun()

        if ch:
            title = st.text_input("Video haqqında bir neçə söz", placeholder="məs. Python dərsi, məhsul təqdimatı",
                                  help="Kontekst tərcümənin keyfiyyətini artırır")
            a, b = st.columns(2)
            lang = a.selectbox("Hansı dilə?", list(config.LANGS), index=list(config.LANGS).index(u.get("lang") or "az"),
                               format_func=lambda k: config.LANG_NAMES_AZ[k])
            voice = u.get("voice") or "nova"
            dialog = clone = False
            if ch == "dub":
                dialog = st.toggle("Danışanları özü tapsın (dialoq, 2–4 nəfər)", value=True,
                                   help="Kim nə vaxt danışır ayrılır, hər danışana öz səsi verilir: "
                                        "qadına qadın, kişiyə kişi səsi, hər kəsə fərqli.")
                if dialog and tts.provider() == "elevenlabs":
                    clone = st.checkbox("Hər kəs öz səsi ilə danışsın (səs klonu)",
                                        help="ElevenLabs Instant Voice Clone — Starter və ya daha yüksək plan "
                                             "lazımdır. Alınmasa, hazır səslər istifadə olunur. Klonlar iş "
                                             "bitən kimi ElevenLabs hesabından silinir.")
                    if clone:
                        st.caption("Yalnız səsini istifadə etməyə icazən olan insanların videosunu klonla "
                                   "(özün, razılığı olan həmsöhbətin).")
            if ch == "dub" and not dialog:
                opts = (list(tts.EL_VOICES) if tts.provider() == "elevenlabs" else []) + list(tts.OPENAI_VOICES)
                voice = b.selectbox("Səs", opts, index=0,
                                    format_func=lambda v: tts.EL_VOICES[v][1] + " · ElevenLabs" if v in tts.EL_VOICES
                                    else v.capitalize() + " · OpenAI")
            if ch == "dub" and tts.provider() == "elevenlabs":
                with st.expander("ElevenLabs işləyirmi? Yoxla"):
                    if st.button("Yoxla", key="el_check"):
                        st.code(tts.check(), language=None)
            go = st.button("Başla", type="primary", icon=":material/play_arrow:", width="stretch")
            st.caption("10 dəqiqəlik video üçün təxminən 1–3 dəqiqə çəkir." +
                       (" Səs: ElevenLabs." if tts.provider() == "elevenlabs" and ch == "dub" else ""))
            today = time.strftime("%Y-%m-%d")
            used = sum(1 for d in studio.history(u["username"], limit=200)
                       if time.strftime("%Y-%m-%d", time.localtime(d.get("created", 0))) == today)
            if go and used >= config.STUDIO_DAILY_LIMIT:
                st.warning(f"Bu gün {used} video etmisən — gündəlik limit {config.STUDIO_DAILY_LIMIT}. Sabah yenə.")
                go = False
            if go:
                if not config.OPENAI_API_KEY:
                    st.error("`.env` faylında OPENAI_API_KEY yoxdur.")
                    st.stop()
                with st.status("Hazırlanır…", expanded=True) as status:
                    try:
                        status.update(label="1/3 · Danışıq mətnə çevrilir")
                        sents, src_lang = studio.transcribe(job, on_step=st.write, dialog=dialog)
                        st.write(f"{len(sents)} cümlə tapıldı (dil: {src_lang or 'avtomatik'}).")
                        status.update(label="2/3 · Tərcümə")
                        res = studio.translate(job, sents, title, lang, ch, db.glossary(u["username"]))
                        m = res["meta"]
                        st.write(f"Mövzu: {m.get('topic') or '—'} · {m['translated']}/{m['count']} cümlə tərcümə olundu")
                        status.update(label="3/3 · " + ("Dublyaj" if ch == "dub" else "Altyazı əlavə olunur"))
                        cast = {}
                        if ch == "dub":
                            cast = studio.speaker_voices(job, res, clone, on_step=st.write) if dialog else {}
                            if cast:
                                st.write("Səslər: " + speakers.describe(cast))
                            try:
                                out = studio.dubbed_video(job, res, lang, voice, on_step=st.write)
                            finally:
                                speakers.delete_clones([v["voice"][5:] for v in cast.values() if v["cloned"]])
                        else:
                            out = studio.subtitled_video(job, lang)
                        status.update(label="Hazırdır", state="complete", expanded=False)
                    except Exception as e:
                        status.update(label="Alınmadı", state="error")
                        st.error(str(e))
                        st.stop()
                ss.vid_result = {"out": str(out), "srt": str(job / f"{lang}.srt"), "mode": ch, "lang": lang,
                                 "segments": res["segments"], "topic": res["meta"].get("topic", ""),
                                 "cast": cast, "warning": res.get("tts_warning", ""),
                                 "res": res, "voice": voice, "title": title or f.name}
                studio.save_result(job, u["username"], title or f.name, ss.vid_result)
                vid = "studio-" + job.name[:8]
                db.add_video(u["username"], vid, title or f.name, lang, ch, res["segments"], ss.vid_result["topic"])
                events.send("video", u["username"], video_id=vid, title=title or f.name, lang=lang, mode=ch,
                            seconds=round(res["segments"][-1]["e"]), topic=ss.vid_result["topic"])
                st.rerun()
    st.stop()

# ---- nəticə
r = ss.vid_result
out = studio.Path(r["out"])
srt = studio.Path(r["srt"])
common.h2("Dublyaj hazırdır" if r["mode"] == "dub" else "Altyazılı video hazırdır")
left, right = st.columns([3, 2], gap="large")
with left:
    st.video(str(out), subtitles={config.LANG_NAMES_AZ[r["lang"]]: str(srt)} if r["mode"] == "sub" else None)
with right:
    st.download_button("MP4 yüklə", out.read_bytes(), out.name, "video/mp4", icon=":material/download:",
                       type="primary", width="stretch")
    st.download_button("SRT altyazı yüklə", srt.read_bytes(), srt.name, "text/plain", icon=":material/subtitles:",
                       width="stretch")
    if r.get("warning"):
        st.warning(r["warning"], icon=":material/warning:")
    if r.get("cast"):
        st.markdown("**Danışanlar**")
        el = tts.provider() == "elevenlabs"
        opts = (list(tts.EL_VOICES) if el else list(tts.OPENAI_VOICES))
        name = (lambda v: "Öz səsi (klon)" if v.startswith("elid:") else
                tts.EL_VOICES[v][1] if v in tts.EL_VOICES else v.capitalize())
        picked = {}
        for who, v in r["cast"].items():
            cur = v["voice"]
            choices = ([cur] if cur not in opts else []) + opts
            picked[who] = st.selectbox(f"{v['n']}. {speakers.GENDER_AZ[v['gender']]} · {v['seconds']} san",
                                       choices, index=choices.index(cur), format_func=name, key=f"spk_{who}")
        changed = {w: x for w, x in picked.items() if x != r["cast"][w]["voice"]}
        if changed and r.get("res") and st.button("Səsləri yenilə", type="primary",
                                                  icon=":material/record_voice_over:", width="stretch"):
            with st.status("Seçdiyin səslərlə yenidən səsləndirilir…", expanded=True) as status:
                for w, x in changed.items():
                    r["cast"][w].update(voice=x, cloned=False, label=name(x).split(" —")[0],
                                        fallback=tts.EL_TO_OPENAI.get(x, x))
                speakers.apply(r["res"]["segments"], r["cast"])
                studio.dubbed_video(studio.Path(r["out"]).parent, r["res"], r["lang"], r["voice"],
                                    on_step=st.write)
                r["warning"] = r["res"].get("tts_warning", "")
                studio.save_result(studio.Path(r["out"]).parent, u["username"], r.get("title", ""), r)
                status.update(label="Hazırdır", state="complete")
            st.rerun()
    st.caption("MP4-də altyazı ayrıca trek kimidir: QuickTime / VLC-də CC düyməsi ilə açılır.")
    if st.button("Başqa variant" if not ss.get("vid_open") else "Siyahıya qayıt",
                 icon=":material/replay:", width="stretch"):
        ss.vid_result, ss.vid_choice, ss.vid_open = None, None, False
        st.rerun()
num = {k: v["n"] for k, v in (r.get("cast") or {}).items()}
rows = "".join(f'<div class="seg"><div class="tc">{common.tc(s["s"])}'
               f'{"<br>👤 " + str(num[s["speaker"]]) if s.get("speaker") in num else ""}</div>'
               f'<div>{html.escape(s["src"])}</div>'
               f'<div><b>{html.escape(s["tr"])}</b></div><div></div></div>' for s in r["segments"][:200])
with st.expander("Mətn: orijinal və tərcümə"):
    st.markdown(rows, unsafe_allow_html=True)
