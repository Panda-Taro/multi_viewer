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
