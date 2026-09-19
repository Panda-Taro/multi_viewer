"""nmos/receiver_model.py

対応要件: ④-7, ⑥, ⑦ (NMOS Receiverロールのみ)

nmos-cpp (C++) 側の node_implementation が構築するリソースツリーと同一の
構造・ID導出規則をPythonで表現した「設計台帳」。ハードウェア・nmos-cppの
実バイナリなしに、以下をテストする:

  - 常に "video x4 + audio x1" のReceiverのみが存在し、Senderは一切含まれない
  - Receiver IDが seed_id から決定論的に導出される (再起動をまたいで安定)
  - IS-04 v1.1-v1.3 / IS-05 v1.0-v1.1 のバージョン文字列が要件通り公開される
  - IS-05 activate要求 (staged PATCH) が active へ正しくマージされる
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field


IS04_VERSIONS = ["v1.1", "v1.2", "v1.3"]
IS05_VERSIONS = ["v1.0", "v1.1"]

VIDEO_RECEIVER_COUNT = 4
AUDIO_RECEIVER_COUNT = 1


class NmosModelError(ValueError):
    pass


def derive_receiver_id(seed_id: str, kind: str, index: int) -> str:
    """seed_idから決定論的にUUIDv5を導出する (nmos-cpp側make_stable_receiver_idに対応)。"""
    name = f"{seed_id}-{kind}-{index}"
    namespace = uuid.UUID(hashlib.md5(seed_id.encode()).hexdigest())
    return str(uuid.uuid5(namespace, name))


@dataclass
class ReceiverResource:
    id: str
    kind: str  # "video" | "audio"
    label: str
    format: str  # "urn:x-nmos:format:video" | "urn:x-nmos:format:audio"
    media_type: str


@dataclass
class NodeResourceSet:
    """IS-04が公開するリソースセット全体 (④-7: Senderは絶対に含めない)。"""

    seed_id: str
    receivers: list[ReceiverResource] = field(default_factory=list)

    @classmethod
    def build(cls, seed_id: str) -> "NodeResourceSet":
        receivers = []
        for i in range(VIDEO_RECEIVER_COUNT):
            receivers.append(
                ReceiverResource(
                    id=derive_receiver_id(seed_id, "video", i),
                    kind="video",
                    label=f"Video Receiver {i + 1}",
                    format="urn:x-nmos:format:video",
                    media_type="video/raw",
                )
            )
        for i in range(AUDIO_RECEIVER_COUNT):
            receivers.append(
                ReceiverResource(
                    id=derive_receiver_id(seed_id, "audio", i),
                    kind="audio",
                    label=f"Audio Receiver {i + 1}",
                    format="urn:x-nmos:format:audio",
                    media_type="audio/L24",
                )
            )
        return cls(seed_id=seed_id, receivers=receivers)

    def validate_receiver_only(self) -> None:
        """⑦: Sender資源が存在しないこと、Receiver数が4+1であることを検証する。"""
        video = [r for r in self.receivers if r.kind == "video"]
        audio = [r for r in self.receivers if r.kind == "audio"]
        if len(video) != VIDEO_RECEIVER_COUNT:
            raise NmosModelError(f"映像Receiverは4系統でなければならない: {len(video)}")
        if len(audio) != AUDIO_RECEIVER_COUNT:
            raise NmosModelError(f"音声Receiverは1系統でなければならない: {len(audio)}")
        if len(self.receivers) != VIDEO_RECEIVER_COUNT + AUDIO_RECEIVER_COUNT:
            raise NmosModelError("Receiver以外のリソース種別が混入している")

    def ids_are_stable(self, other_seed_run: "NodeResourceSet") -> bool:
        """同一seed_idからの2回のビルドでIDが一致すること(再起動をまたぐ安定性)。"""
        return {r.id for r in self.receivers} == {r.id for r in other_seed_run.receivers}


@dataclass
class ConnectionResource:
    """IS-05 Connection API の staged/active ペア。"""

    receiver_id: str
    staged: dict = field(default_factory=lambda: {"master_enable": False, "sender_id": None, "transport_params": []})
    active: dict = field(default_factory=lambda: {"master_enable": False, "sender_id": None, "transport_params": []})

    def patch_staged(self, patch: dict) -> None:
        self.staged.update(patch)

    def activate(self, activation_mode: str = "activate_immediate") -> dict:
        """PATCH staged {"activation": {"mode": "activate_immediate"}} を模した処理。

        戻り値: activeへ反映された内容 (bridgeがMTL設定へ適用する入力となる)。
        """
        if activation_mode not in ("activate_immediate", "activate_scheduled_absolute", "activate_scheduled_relative"):
            raise NmosModelError(f"不明なactivation mode: {activation_mode}")
        self.active = dict(self.staged)
        return self.active


def supported_is04_versions() -> list[str]:
    return list(IS04_VERSIONS)


def supported_is05_versions() -> list[str]:
    return list(IS05_VERSIONS)
