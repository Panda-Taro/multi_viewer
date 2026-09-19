// webgui/app/static/js/dashboard.js
// 対応要件: ④-4 (WebGUIから表示モードをクリックでトグル、1秒以内反映)
document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("toggle-mode-btn");
  const label = document.getElementById("mode-label");
  if (!btn) return;

  btn.addEventListener("click", async () => {
    const res = await fetch("/api/display-mode/toggle", { method: "POST" });
    if (!res.ok) return;
    const data = await res.json();
    label.textContent = data.mode === "quad" ? "4分割" : "シングル";
    btn.dataset.mode = data.mode;
  });

  // 5秒ごとにシステム状態を更新 (帯域/CPU/Receiver LED)
  setInterval(async () => {
    try {
      const res = await fetch("/api/status");
      if (!res.ok) return;
      // 簡易実装: フル再読み込みはせず今後の拡張余地として残す
    } catch (e) {
      /* ネットワーク一時断は無視 */
    }
  }, 5000);
});
