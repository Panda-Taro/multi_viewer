// Requirement 4.8.3.1: if saving fails, show an error and keep the
// previous value. We snapshot each card's field values right after a
// successful save (and on load) and restore that snapshot on failure.

function readCard(card) {
  const get = (field) => card.querySelector(`[data-field="${field}"]`);
  const value = (field) => {
    const el = get(field);
    if (!el) return undefined;
    if (el.type === "checkbox") return el.checked;
    if (el.type === "number") return el.value === "" ? 0 : parseInt(el.value, 10);
    return el.value;
  };
  return {
    enabled: value("enabled"),
    payload_id: value("payload_id"),
    ...(card.dataset.kind === "video"
      ? { video_format: value("video_format"), color_format: value("color_format") }
      : { sampling: value("sampling"), packet_time: value("packet_time") }),
    amber: {
      source_ip: value("amber.source_ip"),
      group_ip: value("amber.group_ip"),
      port: value("amber.port"),
    },
    blue: {
      source_ip: value("blue.source_ip"),
      group_ip: value("blue.group_ip"),
      port: value("blue.port"),
    },
  };
}

function writeCard(card, data) {
  const set = (field, val) => {
    const el = card.querySelector(`[data-field="${field}"]`);
    if (!el) return;
    if (el.type === "checkbox") el.checked = !!val;
    else el.value = val;
  };
  set("enabled", data.enabled);
  set("payload_id", data.payload_id);
  if (card.dataset.kind === "video") {
    set("video_format", data.video_format);
    set("color_format", data.color_format);
  } else {
    set("sampling", data.sampling);
    set("packet_time", data.packet_time);
  }
  set("amber.source_ip", data.amber.source_ip);
  set("amber.group_ip", data.amber.group_ip);
  set("amber.port", data.amber.port);
  set("blue.source_ip", data.blue.source_ip);
  set("blue.group_ip", data.blue.group_ip);
  set("blue.port", data.blue.port);
}

const snapshots = new WeakMap();

async function saveCard(card) {
  const status = card.querySelector('[data-role="status"]');
  const payload = readCard(card);
  const kind = card.dataset.kind;
  const index = card.dataset.index;

  status.textContent = "保存中...";
  status.className = "save-status";

  try {
    const res = await fetch(`/api/media/${kind}/${index}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      status.textContent = "保存失敗: " + (body.detail || res.status);
      status.classList.add("err");
      const previous = snapshots.get(card);
      if (previous) writeCard(card, previous);
      return;
    }
    status.textContent = "保存しました";
    status.classList.add("ok");
    snapshots.set(card, payload);
  } catch (e) {
    status.textContent = "保存失敗: " + e;
    status.classList.add("err");
    const previous = snapshots.get(card);
    if (previous) writeCard(card, previous);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".receiver-card").forEach((card) => {
    snapshots.set(card, readCard(card));
    card.querySelector('[data-role="save"]').addEventListener("click", () => saveCard(card));
  });
});
