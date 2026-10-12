"""DubLens API (FastAPI). Chrome uzantısı və Streamlit paneli bunu istifadə edir.

İşə sal:  uvicorn backend.main:app --port 8000
Uzantı hər sorğuda X-DubLens-Token başlığı göndərir (token Streamlit panelində görünür).

Uzun videolar hissə-hissə tərcümə olunur: uzantı əvvəl izlənən yerin hissəsini istəyir (5–8 san),
qalan hissələr arxa planda gəlir. Hər hissə keşlənir — eyni videonu ikinci dəfə açmaq pulsuzdur.
"""
import hashlib
import json

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend import chains, config, db, events, segments, tts

app = FastAPI(title="DubLens API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
db.init()

PART = 40   # bir hissədə neçə cümlə


def user(x_dublens_token: str = Header(default="")) -> dict:
    u = db.user_by_token(x_dublens_token)
    if not u:
        raise HTTPException(401, "Token yanlışdır. DubLens panelindən tokeni kopyala və uzantıya yapışdır.")
    return u


def _h(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:24]


# ------------------------------------------------------------------ modellər
class Source(BaseModel):
    format: str = Field("json3", description="json3 (YouTube) | cues ([{s,e,t}]) | srt")
    data: dict | None = None
    cues: list[dict] | None = None
    text: str | None = None


class TranslateReq(BaseModel):
    video_id: str
    title: str = ""
    lang: str = "az"
    mode: str = "sub"          # sub | dub
    part: int = 0
    source: Source


class DubReq(BaseModel):
    video_id: str
    lang: str = "az"
    voice: str | None = None
    style: str = "neutral"     # formal | neutral | informal (kontekst analizindən)
    segments: list[dict]


class WordReq(BaseModel):
    word: str
    sentence: str
    video_id: str = ""
    title: str = ""
    t: float = 0
    lang: str = "az"


class LineReq(BaseModel):
    line: str
    context: list[str] = []
    lang: str = "az"


# ------------------------------------------------------------------ köməkçilər
def sentences_from(src: Source) -> list[dict]:
    if src.format == "json3" and src.data:
        words = segments.words_from_json3(src.data)
    elif src.format == "srt" and src.text:
        words = segments.words_from_cues(segments.parse_srt(src.text))
    elif src.cues:
        words = segments.words_from_cues(src.cues)
    else:
        raise HTTPException(400, "Altyazı mənbəyi boşdur.")
    sents = segments.to_sentences(words)
    if not sents:
        raise HTTPException(422, "Bu videonun altyazısında mətn tapılmadı.")
    return sents


def analysis_for(video_id: str, lang: str, title: str, sents: list[dict]) -> dict:
    key = "an:" + _h(video_id, lang, len(sents), sents[0]["src"])
    a = db.cache_get(key)
    if a is None:
        a = chains._safe_analysis({"segments": sents, "title": title, "lang": lang})
        db.cache_set(key, a)
    return a


def translate_part(u: dict, video_id: str, title: str, lang: str, mode: str, sents: list[dict], part: int) -> dict:
    if lang not in config.LANGS:
        raise HTTPException(400, f"Dil dəstəklənmir: {lang}")
    parts = max(1, -(-len(sents) // PART))
    part = max(0, min(part, parts - 1))
    chunk = sents[part * PART:(part + 1) * PART]
    gl = db.glossary(u["username"])
    key = "tr:" + _h(video_id, lang, mode, part, json.dumps([c["src"] for c in chunk], ensure_ascii=False),
                     json.dumps(gl, sort_keys=True, ensure_ascii=False))
    cached = db.cache_get(key)
    if cached is None:
        a = analysis_for(video_id, lang, title, sents)
        res = chains.translate_chain.invoke({"segments": chunk, "before": sents[max(0, part * PART - 3):part * PART],
                                             "title": title, "lang": lang, "mode": mode, "glossary": gl,
                                             "analysis": a})
        cached = res
        if res["meta"]["translated"] > 0:
            db.cache_set(key, res)
    if part == 0:
        db.add_video(u["username"], video_id, title, lang, mode, sents, cached["meta"].get("topic", ""))
        events.send("video", u["username"], video_id=video_id, title=title, lang=lang, mode=mode,
                    seconds=round(sents[-1]["e"] - sents[0]["s"]), topic=cached["meta"].get("topic", ""))
    return {**cached, "part": part, "parts": parts, "total": len(sents),
            "index": [{"s": s["s"], "e": s["e"]} for s in sents] if part == 0 else None}


# ------------------------------------------------------------------ endpoint-lər
@app.get("/health")
def health():
    return {"ok": True, "model": config.LLM_MODEL, "langs": list(config.LANGS), "tts": tts.provider()}


@app.get("/api/me")
def me(u: dict = Depends(user)):
    return {**db.public_profile(u), "stats": db.stats(u["username"])}


@app.post("/api/translate")
def translate(req: TranslateReq, u: dict = Depends(user)):
    sents = sentences_from(req.source)
    return translate_part(u, req.video_id, req.title, req.lang, req.mode, sents, req.part)


@app.post("/api/dub")
def dub(req: DubReq, u: dict = Depends(user)):
    segs = [s for s in req.segments if str(s.get("tr", "")).strip()][:PART]
    clips = tts.synth_many(segs, req.voice or u.get("voice") or "nova", req.lang, req.style)
    return {"clips": [{**c, "url": f"/api/clip/{c['key']}.mp3" if c.get("key") else None} for c in clips]}


@app.get("/api/clip/{key}.mp3")
def clip(key: str):
    if not key.isalnum():
        raise HTTPException(400, "Yanlış açar")
    path = tts.clip_path(key)
    if not path.exists():
        raise HTTPException(404, "Səs tapılmadı")
    return FileResponse(path, media_type="audio/mpeg", headers={"Cache-Control": "public, max-age=31536000"})


@app.post("/api/word")
def word(req: WordReq, u: dict = Depends(user)):
    w = req.word.strip(" .,!?;:\"'()[]«»“”").strip()
    if not w or len(w) > 60:
        raise HTTPException(400, "Söz boşdur.")
    key = "w:" + _h(w.lower(), req.sentence, req.lang)
    info = db.cache_get(key)
    if info is None:
        info = chains.word_chain.invoke({"word": w, "sentence": req.sentence, "lang": req.lang})
        db.cache_set(key, info)
    item = db.add_vocab(u["username"], {
        "word": w, "lemma": (info.get("lemma") or w).lower(), "translation": info.get("translation", ""),
        "pos": info.get("pos", ""), "sentence": req.sentence, "sentence_tr": info.get("sentence_tr", ""),
        "example": f"{info.get('example', '')} — {info.get('example_tr', '')}".strip(" —"),
        "video_id": req.video_id, "title": req.title, "t": req.t, "lang": req.lang})
    events.send("vocab", u["username"], word=item["word"], lemma=item["lemma"], translation=item["translation"],
                sentence=item["sentence"], example=item["example"], video_id=req.video_id, title=req.title,
                lang=req.lang)
    return item


@app.post("/api/line")
def line(req: LineReq, u: dict = Depends(user)):
    key = "ln:" + _h(req.line, req.lang)
    r = db.cache_get(key)
    if r is None:
        r = chains.line_chain.invoke({"line": req.line, "context": "\n".join(req.context[-3:]) or "-",
                                      "lang": req.lang})
        db.cache_set(key, r)
    return r


@app.get("/api/vocab")
def vocab(u: dict = Depends(user)):
    return db.vocab(u["username"])
