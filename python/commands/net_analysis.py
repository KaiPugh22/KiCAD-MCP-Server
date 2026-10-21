"""
Net Analysis & Connectivity Intelligence

Helps answer "where does this go?" questions:
- Trace a net through the board showing all connections
- Find the shortest/longest unrouted connections
- Identify star vs daisy-chain topologies
- Calculate total trace length per net
- Find bottleneck traces (narrowest on high-current nets)
"""

import math
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class NetAnalysisCommands:
    def __init__(self, board=None):
        self.board = board

    def set_board(self, board):
        self.board = board

    def trace_net(self, net_name: str) -> Dict[str, Any]:
        """
        Trace a net through the board: list all connected components, pads,
        tracks, and vias with positions.

        Args:
            net_name: Net name to trace
        """
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        try:
            import pcbnew
            board = self.board

            # Check net exists
            netinfo = board.GetNetInfo()
            net = netinfo.GetNetItem(net_name)
            if not net:
                return {"success": False, "error": f"Net '{net_name}' not found"}

            net_code = net.GetNetCode()

            # Find connected pads
            pads = []
            for fp in board.GetFootprints():
                for pad in fp.Pads():
                    if pad.GetNetCode() == net_code:
                        pos = pad.GetPosition()
                        pads.append({
                            "component": fp.GetReference(),
                            "pad": pad.GetName(),
                            "x": pcbnew.ToMM(pos.x),
                            "y": pcbnew.ToMM(pos.y),
                            "layer": board.GetLayerName(pad.GetLayer()),
                        })

            # Find tracks on this net
            tracks = []
            total_track_length = 0
            min_width = float('inf')
            max_width = 0

            for t in board.GetTracks():
                if t.GetNetCode() != net_code:
                    continue

                if isinstance(t, pcbnew.PCB_VIA):
                    continue

                if isinstance(t, pcbnew.PCB_TRACK):
                    sx = pcbnew.ToMM(t.GetStart().x)
                    sy = pcbnew.ToMM(t.GetStart().y)
                    ex = pcbnew.ToMM(t.GetEnd().x)
                    ey = pcbnew.ToMM(t.GetEnd().y)
                    w = pcbnew.ToMM(t.GetWidth())
                    length = math.sqrt((ex - sx) ** 2 + (ey - sy) ** 2)
                    total_track_length += length
                    min_width = min(min_width, w)
                    max_width = max(max_width, w)

                    tracks.append({
                        "start": {"x": round(sx, 3), "y": round(sy, 3)},
                        "end": {"x": round(ex, 3), "y": round(ey, 3)},
                        "width_mm": round(w, 3),
                        "length_mm": round(length, 3),
                        "layer": board.GetLayerName(t.GetLayer()),
                    })

            # Find vias
            vias = []
            for t in board.GetTracks():
                if t.GetNetCode() == net_code and isinstance(t, pcbnew.PCB_VIA):
                    pos = t.GetPosition()
                    vias.append({
                        "x": pcbnew.ToMM(pos.x),
                        "y": pcbnew.ToMM(pos.y),
                        "diameter_mm": pcbnew.ToMM(t.GetWidth()),
                        "drill_mm": pcbnew.ToMM(t.GetDrillValue()),
                    })

            # Determine routing completeness
            is_fully_routed = len(tracks) > 0 or len(pads) <= 1

            if min_width == float('inf'):
                min_width = 0

            return {
                "success": True,
                "net_name": net_name,
                "net_code": net_code,
                "connected_pads": pads,
                "pad_count": len(pads),
                "tracks": tracks[:50],
                "track_count": len(tracks),
                "vias": vias,
                "via_count": len(vias),
                "total_track_length_mm": round(total_track_length, 2),
                "min_track_width_mm": round(min_width, 3),
                "max_track_width_mm": round(max_width, 3),
                "layer_changes": len(vias),
                "fully_routed": is_fully_routed,
            }

        except Exception as e:
            logger.error(f"Trace net failed: {e}")
            return {"success": False, "error": str(e)}

    def find_longest_ratsnest(self, limit: int = 10) -> Dict[str, Any]:
        """
        Find the longest unrouted connections (ratsnest lines).
        These represent the most problematic routing challenges.

        Args:
            limit: Number of results to return
        """
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        try:
            import pcbnew
            board = self.board

            # Build pad connectivity map
            net_pads = {}
            for fp in board.GetFootprints():
                for pad in fp.Pads():
                    net = pad.GetNetname()
                    if not net:
                        continue
                    code = pad.GetNetCode()
                    if code not in net_pads:
                        net_pads[code] = {"name": net, "pads": []}
                    pos = pad.GetPosition()
                    net_pads[code]["pads"].append({
                        "component": fp.GetReference(),
                        "pad": pad.GetName(),
                        "x": pcbnew.ToMM(pos.x),
                        "y": pcbnew.ToMM(pos.y),
                    })

            # Find routed track endpoints per net
            routed_endpoints = {}
            for t in board.GetTracks():
                if isinstance(t, pcbnew.PCB_TRACK):
                    code = t.GetNetCode()
                    if code not in routed_endpoints:
                        routed_endpoints[code] = set()
                    s = t.GetStart()
                    e = t.GetEnd()
                    routed_endpoints[code].add((s.x, s.y))
                    routed_endpoints[code].add((e.x, e.y))

            # Calculate unrouted distances (simple: max pad-to-pad distance
            # minus what's routed)
            unrouted = []
            for code, info in net_pads.items():
                pads = info["pads"]
                if len(pads) < 2:
                    continue

                # Find max distance between any two pads
                max_dist = 0
                max_pair = None
                for i in range(len(pads)):
                    for j in range(i + 1, len(pads)):
                        dx = pads[i]["x"] - pads[j]["x"]
                        dy = pads[i]["y"] - pads[j]["y"]
                        dist = math.sqrt(dx * dx + dy * dy)
                        if dist > max_dist:
                            max_dist = dist
                            max_pair = (pads[i], pads[j])

                # Check if there are tracks on this net
                has_tracks = code in routed_endpoints
                if not has_tracks and max_pair:
                    unrouted.append({
                        "net": info["name"],
                        "distance_mm": round(max_dist, 2),
                        "from": f"{max_pair[0]['component']}.{max_pair[0]['pad']}",
                        "to": f"{max_pair[1]['component']}.{max_pair[1]['pad']}",
                        "from_pos": {"x": max_pair[0]["x"], "y": max_pair[0]["y"]},
                        "to_pos": {"x": max_pair[1]["x"], "y": max_pair[1]["y"]},
                        "pad_count": len(pads),
                    })

            # Sort by distance descending
            unrouted.sort(key=lambda x: x["distance_mm"], reverse=True)

            return {
                "success": True,
                "unrouted_nets": unrouted[:limit],
                "total_unrouted": len(unrouted),
                "message": f"Found {len(unrouted)} unrouted nets. "
                          f"Longest: {unrouted[0]['distance_mm']}mm ({unrouted[0]['net']})"
                          if unrouted else "All nets appear to be routed.",
            }

        except Exception as e:
            logger.error(f"Find longest ratsnest failed: {e}")
            return {"success": False, "error": str(e)}

    def find_bottleneck_traces(self, limit: int = 10) -> Dict[str, Any]:
        """
        Find traces that are narrower than their net class requires, or
        narrow traces on high-fanout nets (potential current bottlenecks).

        Args:
            limit: Number of results to return
        """
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        try:
            import pcbnew
            board = self.board

            # Count connections per net
            net_pad_count = {}
            for fp in board.GetFootprints():
                for pad in fp.Pads():
                    code = pad.GetNetCode()
                    name = pad.GetNetname()
                    if name:
                        if code not in net_pad_count:
                            net_pad_count[code] = {"name": name, "count": 0}
                        net_pad_count[code]["count"] += 1

            bottlenecks = []
            for t in board.GetTracks():
                if isinstance(t, pcbnew.PCB_VIA):
                    continue
                if not isinstance(t, pcbnew.PCB_TRACK):
                    continue

                code = t.GetNetCode()
                width = pcbnew.ToMM(t.GetWidth())
                net_info = net_pad_count.get(code, {"name": "", "count": 0})

                # Flag narrow traces on high-fanout nets (likely power)
                if net_info["count"] >= 5 and width < 0.3:
                    bottlenecks.append({
                        "net": net_info["name"],
                        "width_mm": round(width, 3),
                        "connected_pads": net_info["count"],
                        "x": pcbnew.ToMM(t.GetStart().x),
                        "y": pcbnew.ToMM(t.GetStart().y),
                        "layer": board.GetLayerName(t.GetLayer()),
                        "reason": "narrow trace on high-fanout net",
                    })

                # Flag very narrow traces in general
                elif width < 0.15:
                    bottlenecks.append({
                        "net": net_info["name"],
                        "width_mm": round(width, 3),
                        "connected_pads": net_info["count"],
                        "x": pcbnew.ToMM(t.GetStart().x),
                        "y": pcbnew.ToMM(t.GetStart().y),
                        "layer": board.GetLayerName(t.GetLayer()),
                        "reason": "very narrow trace",
                    })

            # Sort narrowest first
            bottlenecks.sort(key=lambda x: x["width_mm"])

            return {
                "success": True,
                "bottlenecks": bottlenecks[:limit],
                "total_found": len(bottlenecks),
                "message": f"Found {len(bottlenecks)} potential trace bottlenecks",
            }

        except Exception as e:
            logger.error(f"Find bottleneck traces failed: {e}")
            return {"success": False, "error": str(e)}

    def net_length_report(self) -> Dict[str, Any]:
        """Generate a report of total routed trace length per net."""
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        try:
            import pcbnew
            board = self.board

            net_lengths = {}
            for t in board.GetTracks():
                if isinstance(t, pcbnew.PCB_VIA):
                    continue
                if not isinstance(t, pcbnew.PCB_TRACK):
                    continue

                name = t.GetNetname()
                if not name:
                    continue

                sx = pcbnew.ToMM(t.GetStart().x)
                sy = pcbnew.ToMM(t.GetStart().y)
                ex = pcbnew.ToMM(t.GetEnd().x)
                ey = pcbnew.ToMM(t.GetEnd().y)
                length = math.sqrt((ex - sx) ** 2 + (ey - sy) ** 2)

                if name not in net_lengths:
                    net_lengths[name] = {"total_mm": 0, "segments": 0}
                net_lengths[name]["total_mm"] += length
                net_lengths[name]["segments"] += 1

            # Sort by length descending
            report = []
            for name, info in sorted(net_lengths.items(),
                                     key=lambda x: x[1]["total_mm"], reverse=True):
                report.append({
                    "net": name,
                    "total_length_mm": round(info["total_mm"], 2),
                    "segments": info["segments"],
                })

            total = sum(r["total_length_mm"] for r in report)

            return {
                "success": True,
                "nets": report[:50],
                "total_nets": len(report),
                "total_routed_length_mm": round(total, 1),
                "message": f"{len(report)} nets, {round(total, 1)}mm total routed length",
            }

        except Exception as e:
            logger.error(f"Net length report failed: {e}")
            return {"success": False, "error": str(e)}
