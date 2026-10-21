"""
Via Stitching for KiCAD MCP Server.

Automatically places ground vias in a grid or around signal traces for:
- Ground plane stitching (EMC best practice)
- Signal shielding via fences
- Thermal via arrays under power pads
"""

import math
import logging
from typing import Dict, Any, List, Tuple, Optional

logger = logging.getLogger("kicad_interface")


class ViaStitchingCommands:
    def __init__(self, board=None):
        self.board = board

    def add_via_stitching(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add ground via stitching across the board or within a region."""
        try:
            import pcbnew
        except ImportError:
            return {"success": False, "error": "pcbnew not available"}

        if not self.board:
            return {"success": False, "error": "No board loaded"}

        net_name = params.get("net_name", "GND")
        pitch_mm = params.get("pitch_mm", 3.0)
        via_size_mm = params.get("via_size_mm", 0.6)
        via_drill_mm = params.get("via_drill_mm", 0.3)
        clearance_mm = params.get("clearance_mm", 0.5)
        region = params.get("region")  # {x1, y1, x2, y2} in mm, or None for whole board

        nets = self.board.GetNetsByName()
        if net_name not in nets:
            available_gnd = [n for n in nets.keys() if "GND" in n.upper()]
            return {
                "success": False,
                "error": f"Net '{net_name}' not found",
                "available_ground_nets": available_gnd[:10],
            }

        net = nets[net_name]
        net_code = net.GetNetCode()

        if region:
            x1 = int(region["x1"] * 1e6)
            y1 = int(region["y1"] * 1e6)
            x2 = int(region["x2"] * 1e6)
            y2 = int(region["y2"] * 1e6)
        else:
            bbox = self.board.GetBoardEdgesBoundingBox()
            x1 = bbox.GetX()
            y1 = bbox.GetY()
            x2 = x1 + bbox.GetWidth()
            y2 = y1 + bbox.GetHeight()

        pitch = int(pitch_mm * 1e6)
        via_size = int(via_size_mm * 1e6)
        via_drill = int(via_drill_mm * 1e6)
        clearance = int(clearance_mm * 1e6)

        existing_items = []
        for fp in self.board.GetFootprints():
            bb = fp.GetBoundingBox()
            existing_items.append((
                bb.GetX() - clearance, bb.GetY() - clearance,
                bb.GetX() + bb.GetWidth() + clearance,
                bb.GetY() + bb.GetHeight() + clearance,
            ))

        for track in self.board.GetTracks():
            if hasattr(track, 'GetStart'):
                sx, sy = track.GetStart().x, track.GetStart().y
                ex, ey = track.GetEnd().x, track.GetEnd().y
                w = track.GetWidth() // 2 + clearance
                existing_items.append((
                    min(sx, ex) - w, min(sy, ey) - w,
                    max(sx, ex) + w, max(sy, ey) + w,
                ))

        def overlaps_existing(x, y):
            half = via_size // 2 + clearance
            for ix1, iy1, ix2, iy2 in existing_items:
                if x + half > ix1 and x - half < ix2 and y + half > iy1 and y - half < iy2:
                    return True
            return False

        vias_added = 0
        vias_skipped = 0

        y = y1 + pitch // 2
        while y < y2:
            x = x1 + pitch // 2
            while x < x2:
                if not overlaps_existing(x, y):
                    via = pcbnew.PCB_VIA(self.board)
                    via.SetPosition(pcbnew.VECTOR2I(x, y))
                    via.SetWidth(via_size)
                    via.SetDrill(via_drill)
                    via.SetNet(net)
                    via.SetViaType(pcbnew.VIATYPE_THROUGH)
                    self.board.Add(via)
                    vias_added += 1
                else:
                    vias_skipped += 1
                x += pitch
            y += pitch

        if hasattr(pcbnew, 'Refresh'):
            pcbnew.Refresh()

        return {
            "success": True,
            "vias_added": vias_added,
            "vias_skipped": vias_skipped,
            "net": net_name,
            "pitch_mm": pitch_mm,
            "via_size_mm": via_size_mm,
            "via_drill_mm": via_drill_mm,
        }

    def add_via_fence(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a via fence (shielding wall) along a trace or around a region."""
        try:
            import pcbnew
        except ImportError:
            return {"success": False, "error": "pcbnew not available"}

        if not self.board:
            return {"success": False, "error": "No board loaded"}

        net_name = params.get("net_name", "GND")
        points = params.get("points", [])  # [{x, y}, ...] path in mm
        pitch_mm = params.get("pitch_mm", 1.0)
        via_size_mm = params.get("via_size_mm", 0.6)
        via_drill_mm = params.get("via_drill_mm", 0.3)
        offset_mm = params.get("offset_mm", 0.0)  # Offset from path

        if not points or len(points) < 2:
            return {"success": False, "error": "Need at least 2 points for via fence path"}

        nets = self.board.GetNetsByName()
        if net_name not in nets:
            return {"success": False, "error": f"Net '{net_name}' not found"}

        net = nets[net_name]
        pitch = pitch_mm * 1e6
        via_size = int(via_size_mm * 1e6)
        via_drill = int(via_drill_mm * 1e6)

        vias_added = 0
        for i in range(len(points) - 1):
            p1 = points[i]
            p2 = points[i + 1]
            dx = p2["x"] - p1["x"]
            dy = p2["y"] - p1["y"]
            seg_len = math.sqrt(dx * dx + dy * dy)
            if seg_len < 0.01:
                continue

            num_vias = max(1, int(seg_len / pitch_mm))
            nx = -dy / seg_len * offset_mm
            ny = dx / seg_len * offset_mm

            for j in range(num_vias + 1):
                t = j / max(num_vias, 1)
                x = int((p1["x"] + dx * t + nx) * 1e6)
                y = int((p1["y"] + dy * t + ny) * 1e6)

                via = pcbnew.PCB_VIA(self.board)
                via.SetPosition(pcbnew.VECTOR2I(x, y))
                via.SetWidth(via_size)
                via.SetDrill(via_drill)
                via.SetNet(net)
                via.SetViaType(pcbnew.VIATYPE_THROUGH)
                self.board.Add(via)
                vias_added += 1

        return {
            "success": True,
            "vias_added": vias_added,
            "net": net_name,
            "segments": len(points) - 1,
        }

    def add_thermal_vias(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add thermal via array under a component's thermal pad."""
        try:
            import pcbnew
        except ImportError:
            return {"success": False, "error": "pcbnew not available"}

        if not self.board:
            return {"success": False, "error": "No board loaded"}

        reference = params.get("reference")
        pitch_mm = params.get("pitch_mm", 1.2)
        via_size_mm = params.get("via_size_mm", 0.6)
        via_drill_mm = params.get("via_drill_mm", 0.3)
        margin_mm = params.get("margin_mm", 0.3)

        if not reference:
            return {"success": False, "error": "Component reference required"}

        fp = None
        for f in self.board.GetFootprints():
            if f.GetReference() == reference:
                fp = f
                break

        if not fp:
            return {"success": False, "error": f"Component '{reference}' not found"}

        thermal_pad = None
        for pad in fp.Pads():
            pad_name = pad.GetName()
            if pad_name in ("EP", "GND", "Slug", "PAD", "0", ""):
                if thermal_pad is None or pad.GetSizeX() > thermal_pad.GetSizeX():
                    thermal_pad = pad

        if not thermal_pad:
            biggest_pad = None
            for pad in fp.Pads():
                if biggest_pad is None or (pad.GetSizeX() * pad.GetSizeY()) > (biggest_pad.GetSizeX() * biggest_pad.GetSizeY()):
                    biggest_pad = pad
            if biggest_pad and biggest_pad.GetSizeX() > 2e6:
                thermal_pad = biggest_pad

        if not thermal_pad:
            return {
                "success": False,
                "error": f"No thermal/exposed pad found on '{reference}'",
            }

        pad_pos = thermal_pad.GetPosition()
        pad_w = thermal_pad.GetSizeX()
        pad_h = thermal_pad.GetSizeY()
        net = thermal_pad.GetNet()

        margin = int(margin_mm * 1e6)
        pitch = int(pitch_mm * 1e6)
        via_size = int(via_size_mm * 1e6)
        via_drill = int(via_drill_mm * 1e6)

        area_x1 = pad_pos.x - pad_w // 2 + margin
        area_y1 = pad_pos.y - pad_h // 2 + margin
        area_x2 = pad_pos.x + pad_w // 2 - margin
        area_y2 = pad_pos.y + pad_h // 2 - margin

        vias_added = 0
        y = area_y1
        while y <= area_y2:
            x = area_x1
            while x <= area_x2:
                via = pcbnew.PCB_VIA(self.board)
                via.SetPosition(pcbnew.VECTOR2I(int(x), int(y)))
                via.SetWidth(via_size)
                via.SetDrill(via_drill)
                via.SetNet(net)
                via.SetViaType(pcbnew.VIATYPE_THROUGH)
                self.board.Add(via)
                vias_added += 1
                x += pitch
            y += pitch

        return {
            "success": True,
            "reference": reference,
            "vias_added": vias_added,
            "pad_net": net.GetNetname(),
            "pad_size_mm": f"{pad_w/1e6:.1f} x {pad_h/1e6:.1f}",
        }
