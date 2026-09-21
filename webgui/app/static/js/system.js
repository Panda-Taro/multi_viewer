function readNicForm(panel) {
  const get = (field) => panel.querySelector(`[data-field="${field}"]`);
  const value = (field) => {
    const el = get(field);
    if (!el) return undefined;
    if (el.type === "checkbox") return el.checked;
    if (field === "prefix") return parseInt(el.value || "24", 10);
    return el.value;
  };
  return {
    target: panel.dataset.target,
    interface: value("interface"),
    mode: value("mode"),
    address: value("address"),
    prefix: value("prefix"),
    gateway: value("gateway"),
    confirmed_risk: value("confirmed_risk") || false,
  };
}

async function applyNic(panel) {
  const status = panel.querySelector('[data-role="status"]');
  const payload = readNicForm(panel);

  if (!payload.interface) {
    status.textContent = "インターフェースを選択してください";
    status.className = "save-status err";
    return;
  }
  if (payload.mode === "static" && !payload.address) {
    status.textContent = "静的IPの場合はIPアドレスが必要です";
    status.className = "save-status err";
    return;
  }

  const isHighRisk = panel.querySelector('[data-field="confirmed_risk"]') !== null;
  if (isHighRisk && !payload.confirmed_risk) {
    status.textContent = "リスクを理解した旨のチェックが必要です";
    status.className = "save-status err";
    return;
  }

  const warningMessage =
    `NIC (${payload.interface}) の設定を変更し、すぐにサーバーを再起動します。\n` +
    `再起動後、この設定はそのまま維持されます（自動的なロールバックはありません）。\n` +
    `続行しますか？`;
  if (!confirm(warningMessage)) {
    return;
  }

  status.textContent = "適用中...";
  status.className = "save-status";
  try {
    const res = await fetch("/api/network/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      status.textContent = "適用失敗: " + (body.detail || res.status);
      status.className = "save-status err";
      return;
    }
    status.textContent = "適用しました。再起動しています...";
    status.className = "save-status ok";
  } catch (e) {
    status.textContent = "適用失敗: " + e;
    status.className = "save-status err";
  }
}

async function saveStreaming() {
  const status = document.getElementById("streaming-status");
  const payload = {
    bitrate_mbps: parseInt(document.getElementById("streaming-bitrate").value, 10),
    url_path: document.getElementById("streaming-url-path").value,
  };
  status.textContent = "保存中...";
  status.className = "save-status";
  try {
    const res = await fetch("/api/streaming", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      status.textContent = "保存失敗: " + (body.detail || res.status);
      status.className = "save-status err";
      return;
    }
    status.textContent = "保存しました";
    status.className = "save-status ok";
  } catch (e) {
    status.textContent = "保存失敗: " + e;
    status.className = "save-status err";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll('#nic-forms [data-role="apply"]').forEach((btn) => {
    btn.addEventListener("click", () => applyNic(btn.closest(".panel")));
  });
  document.getElementById("streaming-save").addEventListener("click", saveStreaming);
});
