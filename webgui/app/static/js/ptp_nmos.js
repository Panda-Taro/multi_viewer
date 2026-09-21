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
      return;
    }
    status.textContent = "保存しました";
    status.classList.add("ok");
    nmosSnapshot = snapshotFields(NMOS_FIELDS);
  } catch (e) {
    status.textContent = "保存失敗: " + e;
    status.classList.add("err");
    restoreFields(nmosSnapshot);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  ptpSnapshot = snapshotFields(PTP_FIELDS);
  nmosSnapshot = snapshotFields(NMOS_FIELDS);
  document.getElementById("ptp-save").addEventListener("click", savePtp);
  document.getElementById("nmos-save").addEventListener("click", saveNmos);
});
