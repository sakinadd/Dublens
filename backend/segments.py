"""YouTube altyazısını (json3) cümlələrə çevirir — tərcümə yaxşı olsun deyə qırıq parçalar birləşdirilir.

YouTube-un avtomatik altyazısı sözləri ayrı-ayrı vaxtlarla verir və durğu işarəsi qoymur. Hər sözü
mütləq vaxtı ilə çıxarırıq, sonra pauza, durğu işarəsi, uzunluq və müddətə görə cümlələrə bölürük.
"""
import re

END_PUNCT = re.compile(r"[.!?…]['\")\]]?$")
MAX_CHARS = 110
MAX_DUR = 7.0
GAP = 0.75


def words_from_json3(data: dict) -> list[tuple[float, float, str]]:
    """[(başlanğıc_san, son_san, söz)] — avtomatik və əl ilə yazılmış altyazı üçün."""
    out = []
    for ev in data.get("events", []) or []:
        segs = ev.get("segs")
        if not segs:
            continue
        t0 = ev.get("tStartMs", 0) / 1000
        dur = ev.get("dDurationMs", 0) / 1000
        texts = [(s.get("utf8") or "", s.get("tOffsetMs")) for s in segs]
        if all(t.strip() in ("", "\n") for t, _ in texts):
            continue
        if any(off is not None for _, off in texts) or len(texts) > 1:
            for txt, off in texts:
                w = txt.replace("\n", " ").strip()
                if w:
                    st = t0 + (off or 0) / 1000
                    out.append((st, st + 0.3, w))
        else:  # əl ilə yazılmış altyazı: bütün mətn bir parçadır
            w = texts[0][0].replace("\n", " ").strip()
            if w:
                out.append((t0, t0 + max(dur, 0.3), w))
    out.sort(key=lambda x: x[0])
    # dublikatları at (avtomatik altyazıda pəncərələr üst-üstə düşür)
    dedup = []
    for w in out:
        if dedup and abs(w[0] - dedup[-1][0]) < 0.01 and w[2] == dedup[-1][2]:
            continue
        dedup.append(w)
    return dedup


def words_from_cues(cues: list[dict]) -> list[tuple[float, float, str]]:
    """[{s, e, t}] formatı (SRT/VTT və ya DOM-dan oxunan sətirlər)."""
    return [(float(c["s"]), float(c["e"]), str(c["t"]).replace("\n", " ").strip())
            for c in cues if str(c.get("t", "")).strip()]


def to_sentences(words: list[tuple[float, float, str]]) -> list[dict]:
    """Sözləri cümlələrə bölür: [{id, s, e, src}]."""
    segs, cur = [], []

    def flush(next_start: float | None):
        if not cur:
            return
        s = cur[0][0]
        e = max(w[1] for w in cur)
        if next_start is not None:
            e = max(e, min(next_start, s + MAX_DUR + 1.5))
        text = re.sub(r"\s+", " ", " ".join(w[2] for w in cur)).strip()
        text = re.sub(r"\s+([,.!?;:])", r"\1", text)
        segs.append({"id": len(segs), "s": round(s, 2), "e": round(max(e, s + 0.6), 2), "src": text})
        cur.clear()

    for i, w in enumerate(words):
        if cur:
            gap = w[0] - cur[-1][1]
            length = sum(len(x[2]) + 1 for x in cur)
            if gap > GAP or length + len(w[2]) > MAX_CHARS or w[0] - cur[0][0] > MAX_DUR:
                flush(w[0])
        cur.append(w)
        if END_PUNCT.search(w[2]) and sum(len(x[2]) + 1 for x in cur) > 25:
            nxt = words[i + 1][0] if i + 1 < len(words) else None
            flush(nxt)
    flush(None)
    # növbəti cümlə başlayana qədər uzat, amma üst-üstə düşməsin
    for a, b in zip(segs, segs[1:]):
        a["e"] = round(min(max(a["e"], a["s"] + 0.6), b["s"]), 2)
    return segs


def budget(seg: dict, cps: float) -> int:
    """Dublyaj üçün bu cümləyə sığan maksimal simvol sayı."""
    return max(12, int((seg["e"] - seg["s"]) * cps))


def parse_srt(text: str) -> list[dict]:
    """SRT və ya VTT faylını [{s, e, t}] formatına çevirir."""
    def ts(x: str) -> float:
        x = x.strip().replace(",", ".")
        parts = x.split(":")
        parts = [0.0] * (3 - len(parts)) + [float(p) for p in parts]
        return parts[0] * 3600 + parts[1] * 60 + parts[2]

    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r", "")):
        lines = [l for l in block.strip().split("\n") if l.strip()]
        for i, l in enumerate(lines):
            if "-->" in l:
                a, b = l.split("-->")
                body = " ".join(lines[i + 1:])
                body = re.sub(r"<[^>]+>", "", body).strip()
                if body:
                    cues.append({"s": ts(a), "e": ts(b.split()[0]), "t": body})
                break
    return cues


def to_srt(segments: list[dict], key: str = "tr") -> str:
    def f(t: float) -> str:
        ms = int(round(t * 1000))
        h, ms = divmod(ms, 3_600_000)
        m, ms = divmod(ms, 60_000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    return "\n".join(f"{i}\n{f(s['s'])} --> {f(s['e'])}\n{s.get(key) or s.get('src', '')}\n"
                     for i, s in enumerate(segments, 1))
