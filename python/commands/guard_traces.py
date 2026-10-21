"""
Differential Pair Guard Trace Insertion for KiCAD MCP Server.

Automatically adds grounded guard traces flanking differential pairs
(USB, HDMI, Ethernet) with correct spacing and via stitching at ends.
"""

import math
import logging
from typing import Dict, Any, List, Tuple, Optional

logger = logging.getLogger("kicad_interface")

DIFF_PAIR_DEFAULTS = {
    "USB2": {"spacing_mm": 0.2, "guard_spacing_mm": 0.3, "guard_width_mm": 0.2},
    "USB3": {"spacing_mm": 0.17, "guard_spacing_mm": 0.25, "guard_width_mm": 0.15},
    "HDMI": {"spacing_mm": 0.18, "guard_spacing_mm": 0.25, "guard_width_mm": 0.15},
    "Ethernet": {"spacing_mm": 0.2, "guard_spacing_mm": 0.3, "guard_width_mm": 0.2},
    "LVDS": {"spacing_mm": 0.15, "guard_spacing_mm": 0.25, "guard_width_mm": 0.15},
}


class GuardTraceCommands:
    def __init__(self, board=None):
        self.board = board

    def find_diff_pairs(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Find differential pairs on the board by net naming patterns."""
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        patterns = [
            ("USB_D+", "USB_D-"), ("USB_DP", "USB_DN"),
            ("D+", "D-"), ("DP", "DN"),
            ("HDMI_D0+", "HDMI_D0-"), ("HDMI_D1+", "HDMI_D1-"), ("HDMI_D2+", "HDMI_D2-"),
            ("TX+", "TX-"), ("RX+", "RX-"),
            ("ETH_TX+", "ETH_TX-"), ("ETH_RX+", "ETH_RX-"),
            ("LVDS+", "LVDS-"),
        ]

        all_nets = {}
        for net in self.board.GetNetsByName().values():
            name = net.GetNetname()
            if name:
                all_nets[name] = net

        diff_pairs = []
        found_nets = set()

        for net_name in all_nets:
            if net_name in found_nets:
                continue
            upper = net_name.upper()

            if upper.endswith("+") or upper.endswith("_P"):
                if upper.endswith("+"):
                    neg_candidates = [net_name[:-1] + "-",
                                      net_name[:-1] + "_N" if net_name[-1] == "+" else None]
                else:
                    neg_candidates = [net_name[:-2] + "_N"]

                for neg in neg_candidates:
                    if neg and neg in all_nets:
                        pair_type = self._classify_pair(net_name)
                        diff_pairs.append({
                            "positive": net_name,
                            "negative": neg,
                            "type": pair_type,
                            "has_guard": self._check_guard_exists(net_name, neg),
                        })
                        found_nets.add(net_name)
                        found_nets.add(neg)
                        break

        return {
            "success": True,
            "diff_pair_count": len(diff_pairs),
            "diff_pairs": diff_pairs,
        }

    def add_guard_traces(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add guard traces flanking a differential pair."""
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        try:
            import pcbnew
        except ImportError:
            return {"success": False, "error": "pcbnew not available"}

        positive_net = params.get("positive_net")
        negative_net = params.get("negative_net")
        guard_net = params.get("guard_net", "GND")
        guard_spacing_mm = params.get("guard_spacing_mm")
        guard_width_mm = params.get("guard_width_mm")
        add_stitching_vias = params.get("add_stitching_vias", True)
        via_pitch_mm = params.get("via_pitch_mm", 3.0)

        if not positive_net or not negative_net:
            return {"success": False, "error": "positive_net and negative_net required"}

        pair_type = self._classify_pair(positive_net)
        defaults = DIFF_PAIR_DEFAULTS.get(pair_type, DIFF_PAIR_DEFAULTS["USB2"])
        if not guard_spacing_mm:
            guard_spacing_mm = defaults["guard_spacing_mm"]
        if not guard_width_mm:
            guard_width_mm = defaults["guard_width_mm"]

        nets = self.board.GetNetsByName()
        if guard_net not in nets:
            return {"success": False, "error": f"Guard net '{guard_net}' not found"}
        guard_net_info = nets[guard_net]

        pos_segments = self._get_net_segments(positive_net)
        neg_segments = self._get_net_segments(negative_net)

        if not pos_segments and not neg_segments:
            return {"success": False, "error": "No routed segments found for these nets"}

        all_segments = pos_segments + neg_segments
        if not all_segments:
            return {"success": False, "error": "No segments to guard"}

        guard_offset = int(guard_spacing_mm * 1e6)
        guard_width = int(guard_width_mm * 1e6)
        guards_added = 0
        vias_added = 0

        for seg in all_segments:
            sx, sy = seg["sx"], seg["sy"]
            ex, ey = seg["ex"], seg["ey"]
            dx = ex - sx
            dy = ey - sy
            length = math.sqrt(dx * dx + dy * dy)
            if length < 1000:
                continue

            nx = -dy / length
            ny = dx / length

            for side in [1, -1]:
                offset_x = int(nx * guard_offset * side)
                offset_y = int(ny * guard_offset * side)

                track = pcbnew.PCB_TRACK(self.board)
                track.SetStart(pcbnew.VECTOR2I(sx + offset_x, sy + offset_y))
                track.SetEnd(pcbnew.VECTOR2I(ex + offset_x, ey + offset_y))
                track.SetWidth(guard_width)
                track.SetLayer(seg["layer_id"])
                track.SetNet(guard_net_info)
                self.board.Add(track)
                guards_added += 1

        if add_stitching_vias and all_segments:
            via_pitch = int(via_pitch_mm * 1e6)
            via_size = int(0.6e6)
            via_drill = int(0.3e6)

            first_seg = all_segments[0]
            last_seg = all_segments[-1]
            endpoints = [
                (first_seg["sx"], first_seg["sy"]),
                (last_seg["ex"], last_seg["ey"]),
            ]

            for ex, ey in endpoints:
                for seg in all_segments:
                    dx = seg["ex"] - seg["sx"]
                    dy = seg["ey"] - seg["sy"]
                    length = math.sqrt(dx * dx + dy * dy)
                    if length < 1000:
                        continue
                    nx = -dy / length
                    ny = dx / length

                    for side in [1, -1]:
                        vx = int(ex + nx * guard_offset * side)
                        vy = int(ey + ny * guard_offset * side)

                        via = pcbnew.PCB_VIA(self.board)
                        via.SetPosition(pcbnew.VECTOR2I(vx, vy))
                        via.SetWidth(via_size)
                        via.SetDrill(via_drill)
                        via.SetNet(guard_net_info)
                        via.SetViaType(pcbnew.VIATYPE_THROUGH)
                        self.board.Add(via)
                        vias_added += 1
                    break

        return {
            "success": True,
            "pair_type": pair_type,
            "guard_traces_added": guards_added,
            "stitching_vias_added": vias_added,
            "guard_net": guard_net,
            "guard_spacing_mm": guard_spacing_mm,
            "guard_width_mm": guard_width_mm,
        }

    def _classify_pair(self, net_name: str) -> str:
        upper = net_name.upper()
        if "USB" in upper or (upper.startswith("D") and ("+" in upper or "_P" in upper)):
            if "3" in upper or "SS" in upper:
                return "USB3"
            return "USB2"
        if "HDMI" in upper:
            return "HDMI"
        if "ETH" in upper or "MDI" in upper:
            return "Ethernet"
        if "LVDS" in upper:
            return "LVDS"
        return "USB2"

    def _get_net_segments(self, net_name: str) -> List[Dict]:
        segments = []
        for track in self.board.GetTracks():
            if not hasattr(track, 'GetStart'):
                continue
            net = track.GetNet()
            if net and net.GetNetname() == net_name:
                start = track.GetStart()
                end = track.GetEnd()
                segments.append({
                    "sx": start.x, "sy": start.y,
                    "ex": end.x, "ey": end.y,
                    "layer_id": track.GetLayer(),
                })
        return segments

    def _check_guard_exists(self, pos_net: str, neg_net: str) -> bool:
        return False
