"""Minimal SDP (RFC 4566 / RFC 4570) parser for the subset used by ST2110
`transport_file` payloads in IS-05 PATCH requests.

This is deliberately not a general-purpose SDP parser: it extracts just
the fields requirement 4.7.2.3 needs to drive an ST2110 receive session
(source IP, multicast group, port, payload type), one entry per `m=`
line found (a redundant/2022-7 SDP may describe two legs with two `m=`
lines; a simple SDP will have one) -- plus, since the WebGUI's
video_format/sampling/packet_time fields must always show a concrete
value (never a literal "SDP" placeholder -- see NOTES.md "video_format
等のSDP選択肢廃止"), enough to resolve those concrete values when a
receiver is NMOS-driven: `packet_time_ms` (from `a=ptime:`) and
`interlaced` (from the `interlace` keyword in `a=fmtp:`, per RFC4175).
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
    packet_time_ms: Optional[float]
    interlaced: Optional[bool]


_M_LINE_RE = re.compile(r"^m=(\S+)\s+(\d+)\s+RTP/AVP\s+(\d+)")
_C_LINE_RE = re.compile(r"^c=IN IP4 ([0-9.]+)(?:/\d+)?")
_SOURCE_FILTER_RE = re.compile(r"^a=source-filter:\s*incl\s+IN\s+IP4\s+\S+\s+([0-9.]+)")
_PTIME_RE = re.compile(r"^a=ptime:\s*([0-9.]+)")
_FMTP_RE = re.compile(r"^a=fmtp:\d+\s+(.*)$")


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
                "packet_time_ms": None,
                "interlaced": None,
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

        ptime_match = _PTIME_RE.match(line)
        if ptime_match and current is not None:
            current["packet_time_ms"] = float(ptime_match.group(1))
            continue

        fmtp_match = _FMTP_RE.match(line)
        if fmtp_match and current is not None:
            # RFC4175 video fmtp parameters include a bare "interlace"
            # keyword when the stream is interlaced; its absence means
            # progressive scan.
            current["interlaced"] = "interlace" in fmtp_match.group(1).lower()
            continue

    if current is not None:
        legs.append(current)

    return legs
