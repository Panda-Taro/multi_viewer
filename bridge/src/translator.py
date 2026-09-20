"""bridge/src/translator.py

対応要件: ④-7

IS-05 activate要求 (staged PATCHのペイロード、Sender SDPを含む) を受けて、
(1) mtl.rxctl.RxSystemConfig を更新するJSONを生成し、
(2) IGMPv3 join対象 (multicast group, source ip, 対象NIC=Amber/Blue) を
決定するロジック。ネットワークI/Oは行わず、決定論的な変換のみを担当するため
テスト容易。
"""
from __future__ import annotations

import sys
import os
from dataclasses import dataclass
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
# server.pyがbridge.src.translatorとしてパッケージ経由でimportした場合でも
# 同ディレクトリ内のsdpモジュールを解決できるよう、自身のディレクトリも
# sys.pathへ明示的に追加する (server.py側の同種の対応と合わせる)。
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "..", "..", "mtl"))

from sdp import parse_sdp, ParsedSdp, SdpParseError  # noqa: E402
from rxctl import RxSystemConfig, ConfigValidationError  # noqa: E402


class ActivateTranslationError(ValueError):
    pass


@dataclass
class IgmpJoinRequest:
    """activate結果として判明したjoin対象 (Amber/Blue両NICへのjoinはこの1件を
    元に igmp.plan_joins() が展開するため、ここでは1系統分のみを保持する)。
    """

    multicast_group: str
    source_ip: str


RECEIVER_KIND_VIDEO = "video"
RECEIVER_KIND_AUDIO = "audio"


def receiver_kind_and_index(receiver_role: str) -> tuple[str, int]:
    """NMOS Receiver ID/roleラベル (例 "video-receiver-2", "audio-receiver-1") から
    種別とインデックス(0始まり)を決定する。

    bridge/src/server.py が nmos側から受け取るペイロードには
    {"receiver_role": "video-receiver-2", "sdp": "..."} の形式を想定する
    (判断メモ: NMOSリソースIDそのものはUUIDで意味を持たないため、
    nmos側実装がactivate通知にreceiver_roleラベルを付与して送る設計とした)。
    """
    if receiver_role.startswith("video-receiver-"):
        idx = int(receiver_role.rsplit("-", 1)[1]) - 1
        return RECEIVER_KIND_VIDEO, idx
    if receiver_role.startswith("audio-receiver-"):
        idx = int(receiver_role.rsplit("-", 1)[1]) - 1
        return RECEIVER_KIND_AUDIO, idx
    raise ActivateTranslationError(f"不明なreceiver_role: {receiver_role}")


def apply_activate_request(
    config: RxSystemConfig, receiver_role: str, sdp_text: str
) -> tuple[RxSystemConfig, list[IgmpJoinRequest], Optional[str]]:
    """activate要求をRxSystemConfigへ適用し、IGMPv3 join要求一覧と
    フォーマット不統一アラーム(あれば)を返す。
    """
    try:
        parsed: ParsedSdp = parse_sdp(sdp_text)
    except SdpParseError as e:
        raise ActivateTranslationError(f"SDP解析に失敗しました: {e}") from e

    kind, index = receiver_kind_and_index(receiver_role)

    if kind == RECEIVER_KIND_VIDEO and parsed.media_type != "video":
        raise ActivateTranslationError(
            f"receiver_role={receiver_role} はvideoだがSDPのメディア種別が{parsed.media_type}"
        )
    if kind == RECEIVER_KIND_AUDIO and parsed.media_type != "audio":
        raise ActivateTranslationError(
            f"receiver_role={receiver_role} はaudioだがSDPのメディア種別が{parsed.media_type}"
        )

    try:
        config.apply_sdp(kind, index, parsed)
    except ConfigValidationError as e:
        raise ActivateTranslationError(str(e)) from e

    join_requests = [
        IgmpJoinRequest(
            multicast_group=parsed.multicast_group,
            source_ip=parsed.source_ip,
        )
    ]

    alarm = config.check_format_uniformity() if kind == RECEIVER_KIND_VIDEO else None
    return config, join_requests, alarm


def apply_deactivate_request(
    config: RxSystemConfig, receiver_role: str
) -> tuple[RxSystemConfig, IgmpJoinRequest]:
    """④-8-4-2-1補足仕様: Receiver無効化(WebGUI手動トグル、またはIS-05
    activate要求のmaster_enable=false)を適用する。

    ソースIP・マルチキャストアドレス・ポート・ペイロードID等の設定値は変更せず
    保持したまま`enabled`のみFalseにする。戻り値のIgmpJoinRequestは、無効化前の
    (保持されている)マルチキャストグループ/送信元IPを元にした
    IGMPv3 Leave対象であり、呼び出し元(server.py)がigmp.plan_leaves()に渡す。
    """
    kind, index = receiver_kind_and_index(receiver_role)
    target = config.receiver_by_kind(kind, index)
    leave_request = IgmpJoinRequest(
        multicast_group=target.multicast_group_amber,
        source_ip=target.source_ip,
    )
    config.set_enabled(kind, index, False)
    return config, leave_request


def apply_enable_request(
    config: RxSystemConfig, receiver_role: str
) -> tuple[RxSystemConfig, IgmpJoinRequest]:
    """④-8-4-2-1補足仕様: Receiver再有効化(WebGUI手動トグル、またはIS-05
    activate要求のmaster_enable=true)。

    補足仕様により、再有効化時はNMOSから再度SDPを取得し直さず、保持済みの
    設定値(ソースIP・マルチキャストアドレス・ポート等)でIGMP Joinをし直す。
    新しいSDPが伴うNMOS activateは apply_activate_request() 側で処理される
    (そちらは内部で target.enabled = True を設定する)。
    """
    kind, index = receiver_kind_and_index(receiver_role)
    target = config.receiver_by_kind(kind, index)
    config.set_enabled(kind, index, True)
    join_request = IgmpJoinRequest(
        multicast_group=target.multicast_group_amber,
        source_ip=target.source_ip,
    )
    return config, join_request
