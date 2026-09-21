// Shared across every /mgmt/ page: shows the "network change pending
// confirmation" banner (requirement: warn the operator that an unconfirmed
// IP change will auto-rollback) and lets them confirm from any page.

async function pollNetworkState() {
  const banner = document.getElementById("network-pending-banner");
  const text = document.getElementById("network-pending-text");
  const btn = document.getElementById("network-confirm-btn");
  if (!banner) return;

  try {
    const res = await fetch("/api/network/state");
    const state = await res.json();
    if (state.status === "pending_confirm") {
      const remaining = Math.max(0, Math.round(state.seconds_remaining || 0));
      const minutes = Math.floor(remaining / 60);
      const seconds = remaining % 60;
      text.textContent =
        `ネットワーク設定が変更されました。あと ${minutes}分${seconds}秒 以内にこの設定を確定しないと、` +
        `自動的に以前の設定へロールバックして再起動します。（対象: ${(state.changed_targets || []).join(", ")}）`;
      banner.hidden = false;
    } else {
      banner.hidden = true;
    }
  } catch (e) {
    // Network status is best-effort; a failed poll should not break the page.
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("network-confirm-btn");
  if (btn) {
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        const res = await fetch("/api/network/confirm", { method: "POST" });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          alert("確定に失敗しました: " + (body.detail || res.status));
        }
      } finally {
        btn.disabled = false;
        pollNetworkState();
      }
    });
  }
  pollNetworkState();
  setInterval(pollNetworkState, 10000);
});
