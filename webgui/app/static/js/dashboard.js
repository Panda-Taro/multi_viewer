// webgui/app/static/js/dashboard.js
// 対応要件: ④-4, ④-8-4-1-1-1-2 (映像プレビュー画面クリックで4分割⇔単一表示を
// 切替、1秒以内反映。従来のボタンクリックと同じAPIを呼ぶ)
document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("toggle-mode-btn");
  const label = document.getElementById("mode-label");
  const preview = document.getElementById("preview");

  const toggleMode = async () => {
    const res = await fetch("/api/display-mode/toggle", { method: "POST" });
    if (!res.ok) return;
    const data = await res.json();
    if (label) label.textContent = data.mode === "quad" ? "4分割" : "シングル";
    if (btn) btn.dataset.mode = data.mode;
    if (preview) preview.dataset.mode = data.mode;
  };

  if (btn) btn.addEventListener("click", toggleMode);

  if (preview) {
    preview.addEventListener("click", toggleMode);
    preview.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        toggleMode();
      }
    });
  }

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
