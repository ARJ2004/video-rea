// live board: refresh the board partial every 4 s while the tab is visible
(function () {
  const el = document.getElementById("live"); if (!el) return;
  const url = el.dataset.src;
  async function tick() {
    if (document.visibilityState === "visible") {
      try { const r = await fetch(url, {credentials: "same-origin"}); if (r.ok) el.innerHTML = await r.text(); } catch (e) {}
    }
    setTimeout(tick, 4000);
  }
  setTimeout(tick, 4000);
})();
