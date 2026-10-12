// DubLens — YouTube səhifəsində altyazı, ikidilli rejim, dublyaj və söz kartı.
// DOM yalnız createElement / textContent ilə qurulur (YouTube-un Trusted Types qaydası innerHTML-i bloklayır).
(() => {
  if (window.__dublensContent) return;
  window.__dublensContent = true;

  const S = {
    cfg: null,            // uzantı ayarları
    gen: 0,               // hər yeni videoda artır — köhnə sorğuların cavabı atılır
    videoId: null,
    title: "",
    caps: new Map(),      // videoId → son tutulmuş altyazı faylı (mətn)
    segs: [],             // [{id, s, e, src, tr, fit}] vaxta görə sıralı
    byId: new Map(),
    total: 0, parts: 0, loaded: 0,
    style: "neutral",
    clips: new Map(),     // seg.id → {path, state}
    pending: new Set(),   // səsi istənilib, hələ gəlməyib
    autoPaused: false,    // səs gözlənildiyi üçün video dayandırılıb
    playing: null,        // {id, audio}
    lastRendered: null,
    ccTurnedOn: false,
    savedVolume: null,
    liveMode: false, liveCache: new Map(), liveCtx: [],
    timer: null
  };

  // ---------------------------------------------------------------- köməkçilər
  const $ = (sel, root = document) => root.querySelector(sel);
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };
  const send = (msg) => new Promise((res) => {
    try { chrome.runtime.sendMessage(msg, (r) => res(r || { ok: false, error: chrome.runtime.lastError?.message })); }
    catch (e) { res({ ok: false, error: "Uzantı yeniləndi — səhifəni yenilə." }); }
  });
  const api = (path, body, method = "POST") => send({ type: "api", path, body, method });
  const video = () => $("#movie_player video.html5-main-video") || $("video.html5-main-video") || $("video");
  const player = () => $("#movie_player");
  const currentId = () => {
    try { return new URL(location.href).searchParams.get("v"); } catch (e) { return null; }
  };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // ---------------------------------------------------------------- altyazı faylını tutmaq (inject.js-dən)
  window.addEventListener("message", (ev) => {
    const d = ev.data;
    if (ev.source !== window || !d || d.source !== "dublens" || d.type !== "timedtext") return;
    let vid = null;
    try { vid = new URL(d.url, location.origin).searchParams.get("v"); } catch (e) { /* */ }
    if (vid && d.text && d.text.length > 20) S.caps.set(vid, d.text);
  });

  function parseCaption(text) {
    try {
      const j = JSON.parse(text);
      if (j && Array.isArray(j.events)) return { format: "json3", data: { events: j.events } };
    } catch (e) { /* XML ola bilər */ }
    try {
      const xml = new DOMParser().parseFromString(text, "text/xml");
      const cues = [];
      xml.querySelectorAll("p").forEach((p) => {        // srv3
        const s = (+p.getAttribute("t") || 0) / 1000, d = (+p.getAttribute("d") || 0) / 1000;
        const t = p.textContent.trim();
        if (t) cues.push({ s, e: s + d, t });
      });
      if (!cues.length) xml.querySelectorAll("text").forEach((p) => {   // srv1
        const s = +p.getAttribute("start") || 0, d = +p.getAttribute("dur") || 0;
        const t = p.textContent.trim();
        if (t) cues.push({ s, e: s + d, t });
      });
      if (cues.length) return { format: "cues", cues };
    } catch (e) { /* */ }
    return null;
  }

  // ---------------------------------------------------------------- görünüş
  let root, chip, subs, trLine, srcLine, card;
  function ensureUI() {
    const p = player();
    if (!p) return false;
    if (root && root.isConnected && root.parentElement === p) return true;
    root = el("div", "dublens-root");
    chip = el("div", "dublens-chip");
    subs = el("div", "dublens-subs");
    trLine = el("div", "dl-tr");
    srcLine = el("div", "dl-src");
    subs.append(trLine, srcLine);
    card = el("div", "dublens-card");
    card.hidden = true;
    root.append(chip, subs, card);
    p.appendChild(root);
    applyStyle();
    return true;
  }
  function applyStyle() {
    if (!root) return;
    root.style.setProperty("--dl-size", (S.cfg?.fontSize || 26) + "px");
    root.dataset.mode = S.cfg?.mode || "sub";
    root.dataset.subs = S.cfg?.dubSubs ? "1" : "0";
  }
  function status(text, kind = "info", ms = 0) {
    if (!ensureUI()) return;
    chip.textContent = text;
    chip.dataset.kind = kind;
    chip.hidden = !text;
    clearTimeout(status._t);
    if (ms) status._t = setTimeout(() => { chip.hidden = true; }, ms);
  }
  function setActive(on) {
    const p = player();
    if (p) p.classList.toggle("dublens-active", on);
    if (root) root.hidden = !on;
  }

  // ---------------------------------------------------------------- seqmentlər
  function addSegments(list) {
    for (const s of list) {
      if (!S.byId.has(s.id)) { S.byId.set(s.id, s); S.segs.push(s); }
    }
    S.segs.sort((a, b) => a.s - b.s);
  }
  function findAt(t) {
    const a = S.segs;
    let lo = 0, hi = a.length - 1, best = -1;
    while (lo <= hi) {
      const m = (lo + hi) >> 1;
      if (a[m].s <= t) { best = m; lo = m + 1; } else hi = m - 1;
    }
    if (best >= 0 && t < a[best].e + 0.15) return a[best];
    return null;
  }

  function render(seg) {
    const key = seg ? seg.id : null;
    if (key === S.lastRendered) return;
    S.lastRendered = key;
    trLine.textContent = "";
    srcLine.textContent = "";
    subs.hidden = !seg;
    if (!seg) return;
    trLine.textContent = seg.tr || "";
    if ((S.cfg.mode || "sub") === "dual") {
      // orijinal cümlə: hər söz kliklənir → lüğət kartı
      const parts = (seg.src || "").split(/(\s+)/);
      for (const w of parts) {
        if (/^\s+$/.test(w) || !w) { srcLine.append(document.createTextNode(w)); continue; }
        const span = el("span", "dl-word", w);
        span.addEventListener("click", (e) => { e.stopPropagation(); wordCard(w, seg, span); });
        srcLine.append(span);
      }
    }
  }

  // ---------------------------------------------------------------- söz kartı
  async function wordCard(word, seg, span) {
    const v = video();
    if (v && !v.paused) v.pause();
    card.textContent = "";
    card.hidden = false;
    const close = el("button", "dl-close", "×");
    close.addEventListener("click", () => { card.hidden = true; });
    const head = el("div", "dl-c-head", word.replace(/[.,!?;:"“”()]/g, ""));
    const body = el("div", "dl-c-body", "Tərcümə olunur…");
    card.append(close, head, body);
    const r = await api("/api/word", { word, sentence: seg.src, video_id: S.videoId, title: S.title, t: seg.s,
                                       lang: S.cfg.lang });
    body.textContent = "";
    if (!r.ok) { body.textContent = r.error || "Alınmadı"; return; }
    const d = r.data;
    head.textContent = d.lemma + (d.pos ? "  ·  " + d.pos : "");
    body.append(el("div", "dl-c-tr", d.translation || ""));
    if (d.sentence_tr) body.append(el("div", "dl-c-sent", d.sentence_tr));
    if (d.example) body.append(el("div", "dl-c-ex", d.example));
    body.append(el("div", "dl-c-ok", "✓ Lüğətə əlavə olundu — sabah səhər kartlarda görəcəksən"));
  }

  // ---------------------------------------------------------------- tərcümə yükləmə
  async function translatePart(gen, source, part) {
    const r = await api("/api/translate", { video_id: S.videoId, title: S.title, lang: S.cfg.lang,
                                            mode: S.cfg.mode === "dub" ? "dub" : "sub", part, source });
    if (gen !== S.gen) return null;
    return r;
  }

  async function loadVideo(gen, source) {
    status("DubLens · tərcümə hazırlanır…", "busy");
    const first = await translatePart(gen, source, 0);
    if (!first) return;
    if (!first.ok) { status("DubLens · " + first.error, "error"); return; }
    const d = first.data;
    S.total = d.total; S.parts = d.parts; S.loaded = 1;
    S.style = (d.meta && d.meta.register) || "neutral";
    addSegments(d.segments);
    if (S.cfg.mode === "dub") queueDub(gen, d.segments);
    progress(d.meta);
    // izlənən yerin hissəsi əvvəl, sonra qalanlar
    const v = video();
    const idx = (d.index || []).findIndex((x) => v && x.e > v.currentTime);
    const cur = Math.max(0, Math.floor((idx < 0 ? 0 : idx) / 40));
    const order = [];
    for (let i = cur; i < S.parts; i++) if (i !== 0) order.push(i);
    for (let i = 1; i < cur; i++) order.push(i);
    for (const p of order) {
      const r = await translatePart(gen, source, p);
      if (!r) return;
      if (r.ok) {
        addSegments(r.data.segments);
        S.loaded++;
        if (S.cfg.mode === "dub") queueDub(gen, r.data.segments);
        progress(r.data.meta);
      }
    }
  }

  function progress(meta) {
    const topic = meta && meta.topic ? " · " + meta.topic : "";
    if (S.loaded < S.parts) status(`DubLens · ${S.loaded}/${S.parts} hissə hazırdır${topic}`, "busy");
    else status(`DubLens · hazırdır${topic}`, "ok", 3500);
  }

  // ---------------------------------------------------------------- dublyaj
  // Səslər bir-bir istənilir: 2 "işçi" növbədən həmişə videonun hazırkı yerinə ən yaxın cümləni götürür.
  // ElevenLabs-ın pulsuz planı eyni anda 2 sorğu qəbul edir — 2 işçi o 2 yeri daim dolu saxlayır,
  // hər cümlə hazır olan kimi oxunur (böyük paketin bitməsini gözləmir).
  const DUB_WORKERS = 2;
  const dubQ = { gen: -1, todo: new Map(), running: 0, first: true };

  function nextDub() {
    const v = video();
    const t = v ? v.currentTime : 0;
    let best = null;
    for (const s of dubQ.todo.values()) {               // əvvəl irəlidəkilər, ən yaxını
      if (s.e > t - 0.5 && (!best || s.s < best.s)) best = s;
    }
    if (!best) best = dubQ.todo.values().next().value || null;   // sonra keçmişdə qalanlar
    if (best) dubQ.todo.delete(best.id);
    return best;
  }

  async function dubWorker(gen) {
    dubQ.running++;
    try {
      for (let s = nextDub(); s && gen === S.gen; s = nextDub()) {
        if (S.clips.has(s.id)) { S.pending.delete(s.id); continue; }
        const r = await api("/api/dub", { video_id: S.videoId, lang: S.cfg.lang, voice: S.cfg.voice, style: S.style,
                                          segments: [{ id: s.id, s: s.s, e: s.e, tr: s.tr }] });
        if (gen !== S.gen) return;
        S.pending.delete(s.id);
        if (!r.ok) { status("DubLens · səs: " + r.error, "error", 5000); continue; }
        for (const c of r.data.clips) if (c.url && !S.clips.has(c.id)) S.clips.set(c.id, { path: c.url, state: "new" });
        if (dubQ.first) { dubQ.first = false; status("DubLens · dublyaj başladı", "ok", 2500); }
      }
    } finally {
      dubQ.running--;
      // köhnə video/rejimin işçisi çıxdısa, yeni növbəni boş saxlama
      if (dubQ.gen === S.gen && dubQ.todo.size && dubQ.running < DUB_WORKERS) dubWorker(S.gen);
    }
  }

  function queueDub(gen, segs) {
    if (dubQ.gen !== gen) { dubQ.gen = gen; dubQ.todo.clear(); dubQ.first = true; }
    for (const s of segs) {
      if (!S.clips.has(s.id) && String(s.tr || "").trim()) { dubQ.todo.set(s.id, s); S.pending.add(s.id); }
    }
    if (S.clips.size === 0) status("DubLens · səs hazırlanır…", "busy");
    while (dubQ.running < DUB_WORKERS && dubQ.todo.size) dubWorker(gen);
  }
  function preload(id) {
    const c = S.clips.get(id);
    if (!c || c.state !== "new") return;
    c.state = "ready";
    send({ type: "audio", cmd: "preload", path: c.path });
  }
  function stopAudio() {
    if (S.playing) send({ type: "audio", cmd: "stop" });
    S.playing = null;
  }
  function duck(on) {
    const v = video();
    if (!v) return;
    if (on && S.savedVolume == null) { S.savedVolume = v.volume; v.volume = Math.min(v.volume, 0.12); }
    if (!on && S.savedVolume != null) { v.volume = S.savedVolume; S.savedVolume = null; }
  }
  // Dublyaj sinxronu:
  //  - səs hələ gəlməyibsə video bufer kimi gözləyir ("səs gözlənilir…")
  //  - əvvəlki cümlənin səsi hələ bitməyibsə video qısa dayanır ki, cümlə kəsilməsin
  function holdVideo(v, until, reason) {
    S.hold = { until, reason, since: Date.now() };
    S.autoPaused = true;
    v.pause();
    if (reason === "wait") status("DubLens · səs gözlənilir…", "busy");
  }
  function dubTick(v, seg) {
    const i = seg ? S.segs.indexOf(seg) : S.segs.findIndex((x) => x.s > v.currentTime);
    for (let k = Math.max(0, i); k < Math.min(S.segs.length, i + 7); k++) preload(S.segs[k].id);

    if (S.autoPaused && S.hold) {
      const waited = Date.now() - S.hold.since;
      let go = waited > 12000;                                   // heç vaxt 12 saniyədən çox gözləmə
      if (S.hold.reason === "speech") go = go || performance.now() >= S.hold.until;
      if (S.hold.reason === "wait") {
        if (waited > 12000 && seg) S.pending.delete(seg.id);
        go = go || !seg || S.clips.has(seg.id) || !S.pending.has(seg.id);
      }
      if (go) {
        const wasWait = S.hold.reason === "wait";
        S.autoPaused = false; S.hold = null;
        if (wasWait) status("DubLens · dublyaj", "ok", 1500);
        v.play().catch(() => {});
      }
      return;
    }
    if (!seg || v.paused) return;
    if (S.playing && S.playing.id === seg.id) return;

    // əvvəlki cümlə hələ danışılır → video onu gözləsin (kəsilməsin)
    if (S.playing && S.audioEnd && performance.now() < S.audioEnd - 150) {
      holdVideo(v, S.audioEnd, "speech");
      return;
    }
    const c = S.clips.get(seg.id);
    if (!c) {
      if (S.pending.has(seg.id)) holdVideo(v, 0, "wait");
      return;
    }
    const remaining = seg.e - v.currentTime;
    if (remaining < 0.6) return;
    S.playing = { id: seg.id };
    S.audioEnd = performance.now() + remaining * 1000;          // təxmini; dəqiqi cavabdan gəlir
    const started = performance.now();
    send({ type: "audio", cmd: "play", path: c.path, slot: remaining, videoRate: v.playbackRate || 1 })
      .then((r) => {
        if (r && r.ok && r.dur) S.audioEnd = started + (r.dur / r.rate) * 1000;
        else if (r && r.ok === false && !S.audioErr) {
          S.audioErr = true;
          status("DubLens · səs oxunmadı: " + (r.error || ""), "error", 6000);
        }
      });
  }

  // ---------------------------------------------------------------- canlı sətir (fayl tutulmayanda)
  let liveObs = null;
  function startLive(gen) {
    S.liveMode = true;
    status("DubLens · canlı tərcümə (altyazı faylı tutulmadı)", "busy", 4000);
    const box = $(".ytp-caption-window-container") || player();
    if (!box) return;
    let last = "";
    liveObs = new MutationObserver(async () => {
      const line = Array.from(document.querySelectorAll(".ytp-caption-segment")).map((x) => x.textContent).join(" ").trim();
      if (!line || line === last) return;
      last = line;
      let tr = S.liveCache.get(line);
      if (!tr) {
        const r = await api("/api/line", { line, context: S.liveCtx.slice(-3), lang: S.cfg.lang });
        if (gen !== S.gen || !r.ok) return;
        tr = r.data.tr;
        S.liveCache.set(line, tr);
      }
      S.liveCtx.push(line);
      const v = video();
      const t = v ? v.currentTime : 0;
      S.lastRendered = null;
      render({ id: "live" + t, s: t, e: t + 4, src: line, tr });
    });
    liveObs.observe(box, { childList: true, subtree: true, characterData: true });
  }

  // ---------------------------------------------------------------- əsas dövr
  function tick() {
    if (!S.cfg || !S.cfg.enabled || !S.videoId || S.liveMode) return;
    const v = video();
    if (!v || !ensureUI()) return;
    const seg = findAt(v.currentTime);
    render(seg);
    if (S.cfg.mode === "dub") dubTick(v, seg);
  }

  function reset() {
    S.gen++;
    stopAudio();
    duck(false);
    S.segs = []; S.byId.clear(); S.clips.clear(); S.pending.clear(); S.autoPaused = false; S.hold = null; S.audioEnd = 0;
    S.total = S.parts = S.loaded = 0;
    S.lastRendered = null;
    S.liveMode = false; S.liveCtx = []; S.audioErr = false;
    if (liveObs) { liveObs.disconnect(); liveObs = null; }
    if (trLine) { trLine.textContent = ""; srcLine.textContent = ""; }
    if (card) card.hidden = true;
  }

  async function start() {
    reset();
    const gen = S.gen;
    S.videoId = currentId();
    if (!S.cfg.enabled || !S.videoId) { setActive(false); return; }
    if (!S.cfg.token) {
      ensureUI(); setActive(true);
      status("DubLens · tokeni uzantıya yapışdır (DubLens panelində «Uzantı» bölməsi)", "error");
      return;
    }
    for (let i = 0; i < 40 && !(video() && ensureUI()); i++) await sleep(250);
    if (gen !== S.gen) return;
    setActive(true);
    S.title = document.title.replace(/^\(\d+\)\s*/, "").replace(/\s*-\s*YouTube\s*$/, "");
    if (S.cfg.mode === "dub") duck(true);

    // 1) pleyer altyazını artıq yükləyibsə — hazırdır; 2) yoxsa CC düyməsini basırıq ki, yükləsin
    let text = S.caps.get(S.videoId);
    for (let i = 0; !text && i < 12; i++) {
      if (i === 2) {
        const btn = $(".ytp-subtitles-button");
        if (btn && btn.getAttribute("aria-pressed") === "false" && btn.style.display !== "none") {
          btn.click(); S.ccTurnedOn = true;
        }
      }
      await sleep(400);
      if (gen !== S.gen) return;
      text = S.caps.get(S.videoId);
    }
    if (!text) {
      if (document.querySelector(".ytp-caption-segment") || S.ccTurnedOn) { startLive(gen); return; }
      status("DubLens · bu videoda altyazı tapılmadı", "error", 6000);
      return;
    }
    const source = parseCaption(text);
    if (!source) { status("DubLens · altyazı faylı oxunmadı", "error", 6000); return; }
    loadVideo(gen, source);
  }

  // ---------------------------------------------------------------- hadisələr
  let lastUrl = location.href;
  function onNavigate() {
    if (currentId() !== S.videoId || location.href !== lastUrl) {
      lastUrl = location.href;
      if (currentId() !== S.videoId) start();
    }
  }
  document.addEventListener("yt-navigate-finish", () => setTimeout(onNavigate, 300));
  setInterval(onNavigate, 1500);

  document.addEventListener("seeking", (e) => {
    if (e.target && e.target.tagName === "VIDEO") { stopAudio(); S.audioEnd = 0; S.hold = null; S.autoPaused = false; S.lastRendered = null; }
  }, true);
  document.addEventListener("pause", (e) => {
    if (e.target && e.target.tagName === "VIDEO" && S.playing && !(S.hold && S.hold.reason === "speech"))
      send({ type: "audio", cmd: "pause" });
  }, true);
  document.addEventListener("play", (e) => {
    if (e.target && e.target.tagName === "VIDEO" && S.autoPaused && !S.hold) S.autoPaused = false;
    if (e.target && e.target.tagName === "VIDEO" && S.playing) {
      const seg = S.byId.get(S.playing.id);
      if (seg && e.target.currentTime < seg.e) send({ type: "audio", cmd: "resume" });
    }
  }, true);
  document.addEventListener("keydown", (e) => {
    if (e.altKey && e.code === "KeyD") chrome.storage.sync.set({ enabled: !S.cfg.enabled });   // Alt + D: aç/bağla
    if (e.key === "Escape" && card && !card.hidden) card.hidden = true;
  });

  chrome.storage.onChanged.addListener((ch) => {
    const before = S.cfg ? { ...S.cfg } : {};
    for (const [k, v] of Object.entries(ch)) S.cfg[k] = v.newValue;
    applyStyle();
    S.lastRendered = null;
    const restart = ["enabled", "lang", "token", "backend", "voice"].some((k) => k in ch && before[k] !== S.cfg[k])
      || ("mode" in ch && (before.mode === "dub") !== (S.cfg.mode === "dub"));
    if (restart) { S.videoId = null; if (!S.cfg.enabled) { reset(); setActive(false); } else start(); }
  });

  (async () => {
    S.cfg = await send({ type: "settings" });
    if (!S.cfg || S.cfg.ok === false) S.cfg = { enabled: true, mode: "sub", lang: "az", fontSize: 26 };
    S.timer = setInterval(tick, 100);
    onNavigate();
  })();
})();
