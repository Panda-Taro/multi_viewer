function snapshotFields(ids) {
  const values = {};
  ids.forEach((id) => {
    const el = document.getElementById(id);
    values[id] = el.type === "checkbox" ? el.checked : el.value;
  });
  return values;
}

function restoreFields(values) {
  Object.entries(values).forEach(([id, val]) => {
    const el = document.getElementById(id);
    if (el.type === "checkbox") el.checked = val;
    else el.value = val;
  });
}

const PTP_FIELDS = ["ptp-domain"];
const NMOS_FIELDS = [
  "nmos-rds-discovery",
  "nmos-rds-address",
  "nmos-rds-port",
  "nmos-rds-version",
  "nmos-common-port",
  "nmos-source-port-mode",
  "nmos-source-port",
];

let ptpSnapshot;
let nmosSnapshot;

async function savePtp() {
  const status = document.getElementById("ptp-status");
  status.textContent = "保存中...";
  status.className = "save-status";
  const payload = { domain: parseInt(document.getElementById("ptp-domain").value, 10) };
  try {
    const res = await fetch("/api/ptp", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      status.textContent = "保存失敗: " + (body.detail || res.status);
      status.classList.add("err");
      restoreFields(ptpSnapshot);
      return;
    }
    status.textContent = "保存しました";
    status.classList.add("ok");
    ptpSnapshot = snapshotFields(PTP_FIELDS);
  } catch (e) {
    status.textContent = "保存失敗: " + e;
    status.classList.add("err");
    restoreFields(ptpSnapshot);
  }
}

async function saveNmos() {
  const status = document.getElementById("nmos-status");
  status.textContent = "保存中...";
  status.className = "save-status";

  const sourcePortRaw = document.getElementById("nmos-source-port").value;
  const payload = {
    rds_discovery: document.getElementById("nmos-rds-discovery").value,
    rds_static: {
      address: document.getElementById("nmos-rds-address").value,
      port: parseInt(document.getElementById("nmos-rds-port").value || "0", 10),
      api_version: document.getElementById("nmos-rds-version").value,
    },
    common_port: parseInt(document.getElementById("nmos-common-port").value || "0", 10),
    source_port_mode: document.getElementById("nmos-source-port-mode").value,
    source_port: sourcePortRaw === "" ? null : parseInt(sourcePortRaw, 10),
  };

  try {
    const res = await fetch("/api/nmos", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      status.textContent = "保存失敗: " + (body.detail || res.status);
      status.classList.add("err");
      restoreFields(nmosSnapshot);
      updateNmosFieldStates();
      return;
    }
    status.textContent = "保存しました";
    status.classList.add("ok");
    nmosSnapshot = snapshotFields(NMOS_FIELDS);
  } catch (e) {
    status.textContent = "保存失敗: " + e;
    status.classList.add("err");
    restoreFields(nmosSnapshot);
    updateNmosFieldStates();
  }
}

const NMOS_STATUS_LABELS = {
  disabled: "無効（未設定）",
  discovering: "mDNS発見中...",
  registering: "登録中...",
  registered: "登録済み",
  error: "エラー",
};

function formatTimestamp(iso) {
  return iso ? new Date(iso).toLocaleString() : "-";
}

async function refreshNmosStatus() {
  let status;
  try {
    const res = await fetch("/api/nmos/status");
    if (!res.ok) return;
    status = await res.json();
  } catch (e) {
    return; // best-effort polling; a failed poll should not disrupt the page
  }

  document.getElementById("nmos-registration-status").textContent =
    NMOS_STATUS_LABELS[status.registration_status] || status.registration_status || "-";
  document.getElementById("nmos-discovery-mode").textContent = status.discovery_mode || "-";
  document.getElementById("nmos-rds-url").textContent = status.rds_url || "-";
  document.getElementById("nmos-last-heartbeat").textContent = formatTimestamp(status.last_heartbeat_at);
  document.getElementById("nmos-last-error").textContent = status.last_error || "-";

  const section = document.getElementById("nmos-discovered-section");
  const rows = document.getElementById("nmos-discovered-rows");
  if (status.discovery_mode !== "auto") {
    section.hidden = true;
    return;
  }
  section.hidden = false;
  rows.innerHTML = "";
  const selectedName = status.selected_registry ? status.selected_registry.name : null;
  (status.discovered_registries || []).forEach((r) => {
    const tr = document.createElement("tr");
    const isSelected = r.name === selectedName;
    const addr = (r.addresses || []).join(", ") + ":" + r.port;
    tr.innerHTML =
      `<td>${isSelected ? '<span class="led on"></span>選択中' : ""}</td>` +
      `<td>${r.name}</td><td>${addr}</td><td>${r.priority === null ? "(未設定)" : r.priority}</td>`;
    rows.appendChild(tr);
  });
  if ((status.discovered_registries || []).length === 0) {
    rows.innerHTML = '<tr><td colspan="4">発見できたRDSはありません</td></tr>';
  }
}

// Dims (but does not disable) fields that the current RDS登録方式/送信元ポート
// selection means are not actually used -- the operator's value is kept
// editable and preserved for when they switch back, only the styling
// signals it is currently inactive.
function updateNmosFieldStates() {
  const rdsIsAuto = document.getElementById("nmos-rds-discovery").value === "auto";
  document.querySelectorAll('[data-gray-group="rds-static"]').forEach((row) => {
    row.classList.toggle("field-inactive", rdsIsAuto);
  });
  document.getElementById("nmos-rds-static-hint").hidden = !rdsIsAuto;

  const sourcePortIsAuto = document.getElementById("nmos-source-port-mode").value === "auto";
  document.querySelectorAll('[data-gray-group="source-port-number"]').forEach((row) => {
    row.classList.toggle("field-inactive", sourcePortIsAuto);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  ptpSnapshot = snapshotFields(PTP_FIELDS);
  nmosSnapshot = snapshotFields(NMOS_FIELDS);
  document.getElementById("ptp-save").addEventListener("click", savePtp);
  document.getElementById("nmos-save").addEventListener("click", saveNmos);

  document.getElementById("nmos-rds-discovery").addEventListener("change", updateNmosFieldStates);
  document.getElementById("nmos-source-port-mode").addEventListener("change", updateNmosFieldStates);
  updateNmosFieldStates();

  refreshNmosStatus();
  setInterval(refreshNmosStatus, 5000);
});
