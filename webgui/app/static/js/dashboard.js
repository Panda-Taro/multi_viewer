function ledClass(receiver) {
  return receiver.enabled ? "led on" : "led";
}

async function refreshDashboard() {
  const res = await fetch("/api/dashboard/status");
  if (!res.ok) return;
  const data = await res.json();

  document.getElementById("cpu-percent").textContent =
    data.cpu_percent === null ? "N/A" : data.cpu_percent.toFixed(1) + " %";
  document.getElementById("mem-percent").textContent =
    data.memory_percent === null ? "N/A" : data.memory_percent.toFixed(1) + " %";

  const nicText = (nic) => {
    const addr = nic.live_addresses.map((a) => `${a.address}/${a.prefix}`).join(", ") || "未設定";
    return `${nic.interface || "(未設定)"} - ${nic.link_state} - ${addr}`;
  };
  document.getElementById("nic-control").textContent = nicText(data.nics.control);
  document.getElementById("nic-amber").textContent = nicText(data.nics.media_amber);
  document.getElementById("nic-blue").textContent = nicText(data.nics.media_blue);

  const nmosLabels = {
    disabled: "無効（未設定 または mDNS自動発見は未実装）",
    registering: "登録中...",
    registered: "登録済み",
    error: "エラー",
  };
  const nmos = data.nmos || {};
  const nmosText = nmosLabels[nmos.registration_status] || nmos.registration_status || "不明";
  document.getElementById("nmos-status").textContent =
    nmos.rds_url ? `${nmosText} (${nmos.rds_url})` : nmosText;

  const videoRows = document.getElementById("video-led-rows");
  videoRows.innerHTML = "";
  data.video_receivers.forEach((r) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>映像 CH${r.id}</td><td><span class="${ledClass(r)}"></span>${r.enabled ? "有効" : "無効"}</td>`;
    videoRows.appendChild(tr);
  });

  const audioRows = document.getElementById("audio-led-rows");
  audioRows.innerHTML = "";
  data.audio_receivers.forEach((r) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>音声 CH${r.id}</td><td><span class="${ledClass(r)}"></span>${r.enabled ? "有効" : "無効"}</td>`;
    audioRows.appendChild(tr);
  });

  document.getElementById("viewer-url").textContent = data.viewer_url_path;
  document.getElementById("display-mode-select").value = data.display_mode;
  document.getElementById("single-source-select").value = data.single_source;
}

async function applyDisplayMode() {
  const mode = document.getElementById("display-mode-select").value;
  const singleSource = parseInt(document.getElementById("single-source-select").value, 10);
  const status = document.getElementById("display-mode-status");
  status.textContent = "";
  status.className = "save-status";
  try {
    const res = await fetch("/api/display", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: mode, single_source: singleSource }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      status.textContent = "保存失敗: " + (body.detail || res.status);
      status.classList.add("err");
      return;
    }
    status.textContent = "保存しました";
    status.classList.add("ok");
    updatePreview(mode, singleSource);
  } catch (e) {
    status.textContent = "保存失敗: " + e;
    status.classList.add("err");
  }
}

function updatePreview(mode, singleSource) {
  const quad = document.getElementById("preview-quad");
  if (mode === "single") {
    quad.querySelectorAll("div").forEach((div, i) => {
      div.style.display = i + 1 === singleSource ? "flex" : "none";
    });
    quad.style.gridTemplateColumns = "1fr";
    quad.style.gridTemplateRows = "1fr";
  } else {
    quad.querySelectorAll("div").forEach((div) => (div.style.display = "flex"));
    quad.style.gridTemplateColumns = "1fr 1fr";
    quad.style.gridTemplateRows = "1fr 1fr";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("display-mode-apply").addEventListener("click", applyDisplayMode);
  document.getElementById("preview-box").addEventListener("click", () => {
    const select = document.getElementById("display-mode-select");
    select.value = select.value === "quad" ? "single" : "quad";
    applyDisplayMode();
  });
  refreshDashboard();
  setInterval(refreshDashboard, 5000);
});
