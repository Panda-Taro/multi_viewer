"""bridge/src/igmp.py

対応要件: ④-7, ⑦ (IGMPv3のみ、Amber/Blue両NICでjoin)

IS-05 activateで判明したマルチキャストグループ+送信元IPに対し、Amber/Blue
両方の10G NICでIGMPv3 (SSM: Source-Specific Multicast) のjoinを行う。

Linuxで送信元指定付きのマルチキャストjoin (IGMPv3 SSM) を行う標準的な方法は
`setsockopt(IPPROTO_IP, IP_ADD_SOURCE_MEMBERSHIP, ip_mreq_source)` であり、
`ip maddr add` コマンドでは送信元フィルタを表現できないため使用しない
(判断メモ)。本モジュールは実際にソケットオプションを発行する
`join_ssm_group()` と、そのための構造体組み立て・対象決定ロジック
(`plan_joins()`) を分離しており、後者はネットワークI/O無しでテスト可能。
"""
from __future__ import annotations

import socket
import struct
from dataclasses import dataclass


class IgmpError(RuntimeError):
    pass


@dataclass(frozen=True)
class SsmJoinPlan:
    group: str
    source: str
    interface_name: str
    interface_ip: str


def plan_joins(
    group: str,
    source: str,
    amber_iface: str,
    amber_ip: str,
    blue_iface: str,
    blue_ip: str,
) -> list[SsmJoinPlan]:
    """④-7: 「両方のNIC(Amber/Blue)でjoinをトリガー」の実行計画を作る。

    group/source が空、またはIPv4形式でない場合はIgmpErrorを送出する。
    """
    if not group or not source:
        raise IgmpError("マルチキャストグループ/送信元IPが指定されていません")
    for label, addr in (("group", group), ("source", source)):
        try:
            socket.inet_aton(addr)
        except OSError as e:
            raise IgmpError(f"不正なIPv4アドレス ({label}): {addr}") from e

    return [
        SsmJoinPlan(group=group, source=source, interface_name=amber_iface, interface_ip=amber_ip),
        SsmJoinPlan(group=group, source=source, interface_name=blue_iface, interface_ip=blue_ip),
    ]


def join_ssm_group(plan: SsmJoinPlan) -> socket.socket:
    """実際にIGMPv3 SSM joinを行うソケットを作成する (実機でのみ動作)。

    `IP_ADD_SOURCE_MEMBERSHIP` はLinux固有のソケットオプション (in.h の
    struct ip_mreq_source に対応)。本開発環境 (Windows) では該当ソケット
    オプションが存在しないため、呼び出し元がOSを判定して実機(Linux)でのみ
    利用すること。

    戻り値のソケットは、後でLeaveを発行するため呼び出し元(server.py)が
    保持し続けること (④-8-4-2-1の補足仕様: Receiver無効化時にIGMPv3 Leaveを
    送出するには、対応するJoin済みソケットが必要)。
    """
    IP_ADD_SOURCE_MEMBERSHIP = 39  # Linux <netinet/in.h> の値

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        mreq_source = struct.pack(
            "4s4s4s",
            socket.inet_aton(plan.group),
            socket.inet_aton(plan.source),
            socket.inet_aton(plan.interface_ip),
        )
        sock.setsockopt(socket.IPPROTO_IP, IP_ADD_SOURCE_MEMBERSHIP, mreq_source)
    except OSError as e:
        sock.close()
        raise IgmpError(
            f"IGMPv3 SSM joinに失敗しました (interface={plan.interface_name}): {e}"
        ) from e
    return sock


# Leave対象の決定ロジックはJoinと同一 (Amber/Blue両系統) であるため plan_joins()
# をそのまま再利用する。呼び出し元での可読性のためのエイリアス。
plan_leaves = plan_joins


def leave_ssm_group(plan: SsmJoinPlan, sock: socket.socket | None = None) -> None:
    """④-8-4-2-1の補足仕様: Receiver無効化時にIGMPv3 Leaveを送出する (実機でのみ動作)。

    `sock` にjoin_ssm_group()が返したソケットを渡した場合は、そのソケット上で
    明示的に `IP_DROP_SOURCE_MEMBERSHIP` を発行した後にcloseする(Linuxでは
    ソケットcloseだけでもメンバーシップは自動的に外れるが、要件が「IGMPv3 Leave
    メッセージを送出する」と明記しているため、close任せにせず明示的なdropを
    発行する)。`sock` を渡さない場合(bridge再起動直後などJoin時のソケットを
    保持していない場合)は、新規ソケットでadd即dropしてLeaveメッセージのみを
    送出する。
    """
    IP_DROP_SOURCE_MEMBERSHIP = 40  # Linux <netinet/in.h> の値
    IP_ADD_SOURCE_MEMBERSHIP = 39

    mreq_source = struct.pack(
        "4s4s4s",
        socket.inet_aton(plan.group),
        socket.inet_aton(plan.source),
        socket.inet_aton(plan.interface_ip),
    )

    owns_socket = sock is None
    if sock is None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.IPPROTO_IP, IP_ADD_SOURCE_MEMBERSHIP, mreq_source)
        except OSError:
            pass  # 既にJoinしていない状態でのLeaveはベストエフォートで許容する

    try:
        sock.setsockopt(socket.IPPROTO_IP, IP_DROP_SOURCE_MEMBERSHIP, mreq_source)
    except OSError as e:
        raise IgmpError(
            f"IGMPv3 SSM leaveに失敗しました (interface={plan.interface_name}): {e}"
        ) from e
    finally:
        sock.close()
