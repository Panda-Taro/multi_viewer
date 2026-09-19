// webgui/app/static/js/viewer.js
// 対応要件: ④-4 (視聴ページ自身からの表示モード切替), ④-6 (WHEP再生)
//
// MediaMTXのWHEPエンドポイント (webrtcAddress:8889, パスは viewer_path) に対し
// ブラウザのWebRTC (RTCPeerConnection) でWHEPネゴシエーションを行う。
// 実機のMediaMTXが起動していない開発環境では接続エラーになるのが正常。

(function () {
  const script = document.currentScript;
  const viewerPath = script.dataset.viewerPath || "monitor01";
  const video = document.getElementById("whep-video");
  const toggleBtn = document.getElementById("mode-toggle");
  const alarmEl = document.getElementById("alarm");

  async function startWhep() {
    const pc = new RTCPeerConnection();
    pc.ontrack = (event) => {
      video.srcObject = event.streams[0];
    };
    pc.addTransceiver("video", { direction: "recvonly" });
    pc.addTransceiver("audio", { direction: "recvonly" });

    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);

    // MediaMTXのWHEPエンドポイント。1G制御NICと同じホストのポート8889。
    const whepUrl = `${location.protocol}//${location.hostname}:8889/${viewerPath}/whep`;

    try {
      const res = await fetch(whepUrl, {
        method: "POST",
        headers: { "Content-Type": "application/sdp" },
        body: offer.sdp,
      });
      if (!res.ok) throw new Error(`WHEP negotiation failed: ${res.status}`);
      const answerSdp = await res.text();
      await pc.setRemoteDescription({ type: "answer", sdp: answerSdp });
    } catch (e) {
      console.error("WHEP接続に失敗しました(実機のMediaMTXが必要です):", e);
    }
  }

  toggleBtn.addEventListener("click", async () => {
    try {
      const res = await fetch("/api/display-mode/toggle", { method: "POST" });
      const data = await res.json();
      console.log("display mode ->", data.mode);
    } catch (e) {
      console.error("表示モード切替に失敗しました:", e);
    }
  });

  // フォーマット不統一アラームのポーリング表示 (簡易実装。実機ではSSE/WSに置換可)
  async function pollStatus() {
    try {
      const res = await fetch("/api/status");
      if (res.ok) {
        // 現状 /api/status はアラーム状態を返さないため、将来的に拡張する。
      }
    } catch (e) {
      /* ignore */
    }
    setTimeout(pollStatus, 5000);
  }

  startWhep();
  pollStatus();
})();
