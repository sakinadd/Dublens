// DubLens — dublyaj səsi uzantının öz gizli səhifəsində oxunur (offscreen document).
// YouTube səhifəsinin CSP və autoplay məhdudiyyətləri buna təsir etmir.
const cache = new Map();
let cur = null;

function get(url) {
  let a = cache.get(url);
  if (!a) {
    a = new Audio(url);
    a.preload = "auto";
    cache.set(url, a);
    if (cache.size > 80) cache.delete(cache.keys().next().value);
  }
  return a;
}

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (!msg || msg.target !== "offscreen") return false;
  switch (msg.cmd) {
    case "preload":
      get(msg.url);
      reply({ ok: true });
      return false;
    case "play": {
      if (cur) cur.pause();
      const a = get(msg.url);
      cur = a;
      const go = () => {
        const slot = Math.max(0.8, msg.slot || 1);
        const d = isFinite(a.duration) && a.duration > 0 ? a.duration : slot;
        // səs bir az uzundursa yüngülcə sürətləndir (təbii qalsın deyə ən çox 1.2x); qalanını video gözləyir
        a.playbackRate = Math.min(1.2, Math.max(1, d / slot)) * (msg.videoRate || 1);
        a.volume = 1;
        a.currentTime = 0;
        a.play().then(() => reply({ ok: true, dur: d, rate: a.playbackRate }))
                .catch((e) => reply({ ok: false, error: String(e) }));
      };
      if (a.readyState >= 1) go();
      else {
        a.addEventListener("loadedmetadata", go, { once: true });
        a.addEventListener("error", () => reply({ ok: false, error: "Səs faylı yüklənmədi" }), { once: true });
        a.load();
      }
      return true;
    }
    case "pause":
      if (cur) cur.pause();
      reply({ ok: true });
      return false;
    case "resume":
      if (cur && cur.currentTime > 0 && !cur.ended) cur.play().catch(() => {});
      reply({ ok: true });
      return false;
    case "state":
      reply({ ok: true, playing: !!cur && !cur.paused, time: cur ? cur.currentTime : 0, rate: cur ? cur.playbackRate : 0 });
      return false;
    case "stop":
      if (cur) cur.pause();
      cur = null;
      reply({ ok: true });
      return false;
  }
  return false;
});
