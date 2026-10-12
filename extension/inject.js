// DubLens — səhifənin öz kontekstində işləyir (MAIN world).
// YouTube pleyeri altyazını /api/timedtext ünvanından yükləyəndə cavabın surətini götürüb
// content.js-ə ötürür. Heç nə dəyişdirmir, yalnız oxuyur.
(() => {
  if (window.__dublensInjected) return;
  window.__dublensInjected = true;

  const isCaption = (url) => typeof url === "string" && url.includes("/api/timedtext");
  const post = (url, text) => {
    try {
      window.postMessage({ source: "dublens", type: "timedtext", url: String(url), text }, "*");
    } catch (e) { /* səssiz */ }
  };

  const origFetch = window.fetch;
  window.fetch = async function (input, init) {
    const res = await origFetch.apply(this, arguments);
    try {
      const url = typeof input === "string" ? input : input && input.url;
      if (isCaption(url)) res.clone().text().then((t) => t && post(url, t)).catch(() => {});
    } catch (e) { /* səssiz */ }
    return res;
  };

  const origOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url) {
    this.__dublensUrl = url;
    return origOpen.apply(this, arguments);
  };
  const origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function () {
    if (isCaption(this.__dublensUrl)) {
      this.addEventListener("load", () => {
        try {
          const t = this.responseType === "" || this.responseType === "text" ? this.responseText : null;
          if (t) post(this.__dublensUrl, t);
        } catch (e) { /* səssiz */ }
      });
    }
    return origSend.apply(this, arguments);
  };
})();
