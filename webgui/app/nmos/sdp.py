"""Minimal SDP (RFC 4566 / RFC 4570) parser for the subset used by ST2110
`transport_file` payloads in IS-05 PATCH requests.

This is deliberately not a general-purpose SDP parser: it extracts just
the fields requirement 4.7.2.3 needs to drive an ST2110 receive session
(source IP, multicast group, port, payload type), one entry per `m=`
line found (a redundant/2022-7 SDP may describe two legs with two `m=`
lines; a simple SDP will have one).
"""
from __future__ import annotations

import re
from typing import Optional, TypedDict


class SdpLeg(TypedDict):
    media: str  # "video" | "audio" | other
    port: int
    payload_type: Optional[int]
    group_ip: Optional[str]
    source_ip: Optional[str]


_M_LINE_RE = re.compile(r"^m=(\S+)\s+(\d+)\s+RTP/AVP\s+(\d+)")
_C_LINE_RE = re.compile(r"^c=IN IP4 ([0-9.]+)(?:/\d+)?")
_SOURCE_FILTER_RE = re.compile(r"^a=source-filter:\s*incl\s+IN\s+IP4\s+\S+\s+([0-9.]+)")


def parse_sdp(text: str) -> list[SdpLeg]:
    legs: list[SdpLeg] = []
    current: Optional[SdpLeg] = None
    session_group_ip: Optional[str] = None

    for raw_line in text.splitlines():
        line = raw_line.strip()

        m_match = _M_LINE_RE.match(line)
        if m_match:
            if current is not None:
                legs.append(current)
            current = {
                "media": m_match.group(1),
                "port": int(m_match.group(2)),
                "payload_type": int(m_match.group(3)),
                "group_ip": session_group_ip,
                "source_ip": None,
            }
            continue

        c_match = _C_LINE_RE.match(line)
        if c_match:
            if current is not None:
                current["group_ip"] = c_match.group(1)
            else:
                session_group_ip = c_match.group(1)
            continue

        sf_match = _SOURCE_FILTER_RE.match(line)
        if sf_match and current is not None:
            current["source_ip"] = sf_match.group(1)
            continue

    if current is not None:
        legs.append(current)

    return legs
