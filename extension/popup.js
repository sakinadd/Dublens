// DubLens popup: ayarlar chrome.storage.sync-də saxlanır, content.js dəyişikliyi dərhal görür.
const DEFAULTS = { enabled: true, mode: "sub", lang: "az", voice: "nova", fontSize: 26, dubSubs: false,
                   backend: "http://localhost:8000", token: "" };
const $ = (id) => document.getElementById(id);
const msg = (t, kind = "") => { $("msg").textContent = t; $("msg").className = kind; };

async function load() {
  const s = { ...DEFAULTS, ...(await chrome.storage.sync.get(DEFAULTS)) };
  $("enabled").checked = s.enabled;
  document.querySelectorAll("input[name=mode]").forEach((r) => { r.checked = r.value === s.mode; });
  $("lang").value = s.lang;
  $("voice").value = s.voice;
  $("fontSize").value = s.fontSize;
  $("fontOut").textContent = s.fontSize;
  $("backend").value = s.backend;
  $("token").value = s.token;
  $("voiceRow").hidden = s.mode !== "dub";
  $("subsRow").hidden = s.mode !== "dub";
  $("dubSubs").checked = !!s.dubSubs;
  if (!s.token) { $("conn").open = true; msg("Əvvəlcə DubLens panelindən tokeni kopyala və bura yapışdır."); }
  else check(false);
}

const save = (patch) => chrome.storage.sync.set(patch);

$("enabled").addEventListener("change", (e) => save({ enabled: e.target.checked }));
document.querySelectorAll("input[name=mode]").forEach((r) => r.addEventListener("change", () => {
  save({ mode: r.value });
  $("voiceRow").hidden = r.value !== "dub";
  $("subsRow").hidden = r.value !== "dub";
}));
$("dubSubs").addEventListener("change", (e) => save({ dubSubs: e.target.checked }));
$("lang").addEventListener("change", (e) => save({ lang: e.target.value }));
$("voice").addEventListener("change", (e) => save({ voice: e.target.value }));
$("fontSize").addEventListener("input", (e) => { $("fontOut").textContent = e.target.value; save({ fontSize: +e.target.value }); });

async function check(saveFirst = true) {
  const backend = ($("backend").value || DEFAULTS.backend).trim().replace(/\/+$/, "");
  const token = $("token").value.trim();
  if (saveFirst) {
    if (backend.startsWith("https://")) {
      // uzaq server üçün icazə yalnız istifadəçi istəyəndə alınır
      const ok = await chrome.permissions.request({ origins: [new URL(backend).origin + "/*"] });
      if (!ok) { msg("Server ünvanına icazə verilmədi.", "err"); return; }
    }
    await save({ backend, token });
  }
  msg("Yoxlanılır…");
  const r = await chrome.runtime.sendMessage({ type: "api", method: "GET", path: "/api/me" });
  if (r && r.ok) {
    $("who").textContent = "· " + (r.data.name || r.data.username);
    msg(`Qoşuldu: ${r.data.name}. ${r.data.stats.videos} video, ${r.data.stats.words} söz.`, "ok");
  } else {
    $("who").textContent = "";
    msg((r && r.error) || "Qoşulmaq olmadı.", "err");
  }
}
$("check").addEventListener("click", () => check(true));
load();
