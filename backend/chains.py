"""DubLens LCEL chain-ləri.

translate_chain (altyazı və dublyaj):

    {segments, title, lang, mode, glossary}
      │
      ├─ RunnablePassthrough.assign(ctx = RunnableParallel(
      │        analysis = prompt | llm(JSON) | parser      ← mövzu, üslub, toxunulmaz terminlər
      │        glossary = RunnableLambda(...)))            ← istifadəçinin öz terminləri
      ├─ RunnableLambda(_translate_all)                    ← 35 cümləlik paketlər, paralel .batch(), əvvəlki kontekstlə
      │        └─ çatışmayan id-lər üçün ikinci keçid (Python yoxlayır)
      ├─ RunnableBranch(mode == "dub" → _fit_for_dub)      ← vaxta sığmayan cümlələr qısaldılır (Python sayır, LLM qısaldır)
      └─ RunnableLambda(_finalize)

Bütün LLM çağırışları: .with_retry(3) + .with_fallbacks([ehtiyat model]).
"""
import json

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableBranch, RunnableLambda, RunnableParallel, RunnablePassthrough
from langchain_openai import ChatOpenAI

from backend import config
from backend.segments import budget


def _llm(temperature: float = 0.2):
    main = ChatOpenAI(model=config.LLM_MODEL, temperature=temperature, api_key=config.OPENAI_API_KEY, timeout=60)
    backup = ChatOpenAI(model=config.LLM_FALLBACK_MODEL, temperature=temperature, api_key=config.OPENAI_API_KEY,
                        timeout=90)
    fmt = {"response_format": {"type": "json_object"}}
    return main.bind(**fmt).with_retry(stop_after_attempt=3).with_fallbacks([backup.bind(**fmt)])


# ------------------------------------------------------------------ 1. kontekst analizi
ANALYSIS = ChatPromptTemplate.from_messages([
    ("system",
     "You analyse a video transcript before it is translated into {language}. Return ONLY JSON:\n"
     '{{"source_language": "English", "topic": "short topic in Azerbaijani", "domain": "e.g. tech, cooking, finance",'
     ' "register": "formal | neutral | informal", "speakers": 1, "audience": "who it is for, in Azerbaijani",'
     ' "keep_terms": ["brand names, product names, code, people that must NOT be translated"],'
     ' "notes": "one sentence of advice for the translator"}}'),
    ("human", "Title: {title}\n\nTranscript sample:\n{sample}"),
])
analysis_chain = (RunnableLambda(lambda x: {"language": config.LANGS[x["lang"]], "title": x.get("title", ""),
                                            "sample": "\n".join(s["src"] for s in x["segments"][:70])[:6000]})
                  | ANALYSIS | _llm(0) | JsonOutputParser())


def _safe_analysis(x: dict) -> dict:
    if x.get("analysis"):                      # eyni video üçün artıq hesablanıb (keşdən)
        return x["analysis"]
    try:
        a = analysis_chain.invoke(x)
    except Exception:
        a = {}
    return {"source_language": a.get("source_language", "auto"), "topic": a.get("topic", ""),
            "domain": a.get("domain", ""), "register": a.get("register", "neutral"),
            "speakers": a.get("speakers", 1), "audience": a.get("audience", ""),
            "keep_terms": [t for t in a.get("keep_terms", []) if isinstance(t, str)][:40], "notes": a.get("notes", "")}


# ------------------------------------------------------------------ 2. paket tərcümə
TRANSLATE = ChatPromptTemplate.from_messages([
    ("system",
     "You are a professional audiovisual translator ({purpose}) into {language}.\n"
     "Video: \"{title}\". Topic: {topic}. Domain: {domain}. Register: {register}. Audience: {audience}.\n"
     "Translator note: {notes}\n"
     "Do NOT translate these, keep them exactly: {keep_terms}\n"
     "Glossary — you MUST use these translations: {glossary}\n"
     "Rules: natural spoken {language}, never word-for-word; the lines are consecutive parts of one speech, "
     "so keep meaning consistent across lines but translate EVERY id separately; keep numbers and units; "
     "fix speech-recognition errors silently; {length_rule}\n"
     'Return ONLY JSON: {{"items": [{{"id": 0, "tr": "..."}}]}} with exactly the same ids.'),
    ("human", "Previous lines (context only, do not translate):\n{context}\n\nTranslate these lines:\n{lines}"),
])
translate_batch_chain = TRANSLATE | _llm(0.2) | JsonOutputParser()


def _batch_inputs(x: dict, segs: list[dict]) -> list[dict]:
    a, lang = x["ctx"]["analysis"], x["lang"]
    gl = x["ctx"]["glossary"]
    dub = x.get("mode") == "dub"
    base = {
        "purpose": "dubbing voice-over" if dub else "subtitles", "language": config.LANGS[lang],
        "title": x.get("title", ""), "topic": a["topic"], "domain": a["domain"], "register": a["register"],
        "audience": a["audience"], "notes": a["notes"] or "-",
        "keep_terms": ", ".join(a["keep_terms"]) or "-",
        "glossary": "; ".join(f"{k} → {v}" for k, v in gl.items()) or "-",
        "length_rule": ("each line will be spoken in the same time as the original, so keep it about as short as "
                        "the original — prefer short words." if dub else "subtitle lines should be easy to read."),
    }
    out, size = [], config.TRANSLATE_BATCH
    index = {s["id"]: i for i, s in enumerate(x["segments"])}
    for i in range(0, len(segs), size):
        part = segs[i:i + size]
        first = index[part[0]["id"]]
        prev = x["segments"][max(0, first - 3):first] if first else x.get("before", [])[-3:]
        out.append({**base, "context": "\n".join(p["src"] for p in prev) or "-",
                    "lines": json.dumps([{"id": s["id"], "text": s["src"]} for s in part], ensure_ascii=False)})
    return out


def _run_batches(x: dict, segs: list[dict]) -> dict[int, str]:
    inputs = _batch_inputs(x, segs)
    results = translate_batch_chain.batch(inputs, config={"max_concurrency": config.MAX_CONCURRENCY},
                                          return_exceptions=True)
    got = {}
    for r in results:
        if isinstance(r, Exception):
            continue
        for it in r.get("items", []):
            try:
                if str(it.get("tr", "")).strip():
                    got[int(it["id"])] = str(it["tr"]).strip()
            except (KeyError, ValueError, TypeError):
                continue
    return got


def _translate_all(x: dict) -> dict:
    segs = x["segments"]
    got = _run_batches(x, segs)
    missing = [s for s in segs if s["id"] not in got]
    if missing:                                    # LLM bəzi sətirləri buraxıbsa — yalnız onlar üçün ikinci keçid
        got.update(_run_batches({**x}, missing))
    out = [{**s, "tr": got.get(s["id"], s["src"]), "ok": s["id"] in got} for s in segs]
    return {**x, "segments": out}


# ------------------------------------------------------------------ 3. dublyaj üçün vaxta sığışdırma
SHORTEN = ChatPromptTemplate.from_messages([
    ("system",
     "You shorten {language} dubbing lines so they can be spoken in the available time. Keep the meaning, keep "
     "names and numbers, sound natural. Each line has max_chars — the result MUST be at most that long.\n"
     'Return ONLY JSON: {{"items": [{{"id": 0, "tr": "..."}}]}}'),
    ("human", "{lines}"),
])
shorten_chain = SHORTEN | _llm(0.3) | JsonOutputParser()


def _fit_for_dub(x: dict) -> dict:
    segs = x["segments"]
    long_ = [s for s in segs if len(s["tr"]) > budget(s, config.CHARS_PER_SEC) * 1.1]
    if long_:
        chunks = [long_[i:i + 30] for i in range(0, len(long_), 30)]
        inputs = [{"language": config.LANGS[x["lang"]],
                   "lines": json.dumps([{"id": s["id"], "tr": s["tr"], "max_chars": budget(s, config.CHARS_PER_SEC)}
                                        for s in ch], ensure_ascii=False)} for ch in chunks]
        res = shorten_chain.batch(inputs, config={"max_concurrency": config.MAX_CONCURRENCY}, return_exceptions=True)
        short = {}
        for r in res:
            if not isinstance(r, Exception):
                for it in r.get("items", []):
                    try:
                        short[int(it["id"])] = str(it["tr"]).strip()
                    except (KeyError, ValueError, TypeError):
                        pass
        for s in segs:
            if s["id"] in short and 0 < len(short[s["id"]]) < len(s["tr"]):
                s["tr"], s["shortened"] = short[s["id"]], True
    for s in segs:
        s["fit"] = round(len(s["tr"]) / budget(s, config.CHARS_PER_SEC), 2)   # 1-dən böyükdürsə, sürətli oxunacaq
    return x


def _finalize(x: dict) -> dict:
    segs = x["segments"]
    return {"segments": segs, "meta": {**x["ctx"]["analysis"], "lang": x["lang"], "mode": x.get("mode", "sub"),
                                       "count": len(segs), "translated": sum(s.get("ok", False) for s in segs),
                                       "shortened": sum(s.get("shortened", False) for s in segs)}}


translate_chain = (
    RunnablePassthrough.assign(ctx=RunnableParallel(analysis=RunnableLambda(_safe_analysis),
                                                    glossary=RunnableLambda(lambda x: x.get("glossary") or {})))
    | RunnableLambda(_translate_all)
    | RunnableBranch((lambda x: x.get("mode") == "dub", RunnableLambda(_fit_for_dub)), RunnableLambda(lambda x: x))
    | RunnableLambda(_finalize)
)


# ------------------------------------------------------------------ söz izahı (lüğət üçün)
WORD = ChatPromptTemplate.from_messages([
    ("system",
     "You are a bilingual dictionary for a learner whose language is {language}. The learner clicked a word in a "
     "video subtitle. Explain the word AS USED IN THIS SENTENCE. Return ONLY JSON:\n"
     '{{"lemma": "dictionary form in the source language, lowercase", "translation": "short {language} translation", '
     '"pos": "noun | verb | adjective | adverb | phrase | other", '
     '"sentence_tr": "the whole sentence translated into {language}", '
     '"example": "one new short example sentence in the source language", '
     '"example_tr": "its {language} translation"}}'),
    ("human", "Word: {word}\nSentence: {sentence}"),
])
word_chain = (RunnableLambda(lambda x: {**x, "language": config.LANGS[x.get("lang", "az")]})
              | WORD | _llm(0) | JsonOutputParser())


# ------------------------------------------------------------------ canlı sətir (altyazı faylı tapılmayanda)
LINE = ChatPromptTemplate.from_messages([
    ("system", "You translate LIVE speech captions into natural spoken {language}. The captions are auto-generated: "
               "they may lack punctuation, contain fillers (uh, um, you know), repeated words or misrecognised words. "
               "Translate ONLY the last chunk. Earlier chunks are context: use them to understand the meaning and to fix "
               "obvious recognition errors, but never translate or repeat them. Drop fillers and stutters, keep names "
               "and numbers. If the chunk is an unfinished thought, translate it as a natural fragment that continues "
               "the previous chunk. Keep it short — it is shown as a subtitle. "
               'Return ONLY JSON: {{"tr": "..."}}'),
    ("human", "Context:\n{context}\n\nLine: {line}"),
])
line_chain = (RunnableLambda(lambda x: {**x, "language": config.LANGS[x.get("lang", "az")]})
              | LINE | _llm(0.2) | JsonOutputParser())
