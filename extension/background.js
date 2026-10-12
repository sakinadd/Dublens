// DubLens — arxa plan (service worker). Bütün backend sorğuları buradan gedir:
// YouTube səhifəsinin CORS / mixed-content məhdudiyyətləri buna təsir etmir.

const DEFAULTS = {
  enabled: true, mode: "sub", lang: "az", voice: "nova", fontSize: 26, dubSubs: false,
  backend: "http://localhost:8000", token: ""
};

async function settings() {
  const s = await chrome.storage.sync.get(DEFAULTS);
  return { ...DEFAULTS, ...s };
}

chrome.runtime.onInstalled.addListener(async () => {
  const s = await chrome.storage.sync.get(null);
  await chrome.storage.sync.set({ ...DEFAULTS, ...s });
});

async function api(method, path, body) {
  const s = await settings();
  const base = (s.backend || DEFAULTS.backend).replace(/\/+$/, "");
  let res;
  try {
    res = await fetch(base + path, {
      method,
      headers: { "Content-Type": "application/json", "X-DubLens-Token": s.token || "" },
      body: body ? JSON.stringify(body) : undefined
    });
  } catch (e) {
    return { ok: false, status: 0, error: "Backend-ə qoşulmaq olmadı (" + base + "). Server işləyirmi?" };
  }
  let data = null;
  try { data = await res.json(); } catch (e) { /* boş cavab */ }
  if (!res.ok) {
    return { ok: false, status: res.status, error: (data && data.detail) || ("Xəta " + res.status) };
  }
  return { ok: true, status: res.status, data };
}

function toBase64(buf) {
  const bytes = new Uint8Array(buf);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  }
  return btoa(bin);
}

async function clip(path) {
  const s = await settings();
  const base = (s.backend || DEFAULTS.backend).replace(/\/+$/, "");
  try {
    const res = await fetch(base + path);
    if (!res.ok) return { ok: false, error: "Səs tapılmadı" };
    return { ok: true, dataUrl: "data:audio/mpeg;base64," + toBase64(await res.arrayBuffer()) };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}

// ---- dublyaj səsi: offscreen sənəd (uzantının öz gizli səhifəsi)
let creating = null;
async function ensureOffscreen() {
  if (await chrome.offscreen.hasDocument()) return;
  if (!creating) {
    creating = chrome.offscreen.createDocument({
      url: "offscreen.html", reasons: ["AUDIO_PLAYBACK"], justification: "DubLens dublyaj səsini oxumaq"
    }).catch(() => {}).finally(() => { creating = null; });
  }
  await creating;
}

async function audio(msg) {
  await ensureOffscreen();
  const s = await settings();
  const base = (s.backend || DEFAULTS.backend).replace(/\/+$/, "");
  try {
    return await chrome.runtime.sendMessage({ target: "offscreen", cmd: msg.cmd, url: msg.path ? base + msg.path : null,
                                              slot: msg.slot, videoRate: msg.videoRate });
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg.target === "offscreen") return false;          // offscreen sənədin öz mesajıdır
  if (msg.type === "audio") {
    audio(msg).then(reply);
    return true;
  }
  if (msg.type === "api") {
    api(msg.method || "POST", msg.path, msg.body).then(reply);
    return true;
  }
  if (msg.type === "clip") {
    clip(msg.path).then(reply);
    return true;
  }
  if (msg.type === "settings") {
    settings().then(reply);
    return true;
  }
  return false;
});
