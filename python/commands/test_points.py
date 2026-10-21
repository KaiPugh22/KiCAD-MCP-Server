"""
Test Point Management for KiCAD MCP Server.

Auto-identifies nets that need test points, suggests placement locations,
and adds test point footprints to the board. Handles both through-hole
and SMD test point styles.
"""

import math
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("kicad_interface")

CRITICAL_NET_PATTERNS = [
    "VCC", "VDD", "3V3", "3.3V", "5V", "12V", "1V8", "1.8V", "2.5V",
    "VBAT", "VBUS", "VREF", "AVCC", "AVDD", "DVCC", "DVDD",
    "GND", "AGND", "DGND", "PGND",
    "SCL", "SDA", "MOSI", "MISO", "SCK", "CS", "SS",
    "TX", "RX", "UART", "USART",
    "SWDIO", "SWCLK", "SWO", "JTAG", "TDI", "TDO", "TMS", "TCK",
    "RESET", "RST", "NRST",
    "USB_D+", "USB_D-", "USB_DP", "USB_DN",
    "CAN_H", "CAN_L",
    "CLK", "CLOCK",
]


class TestPointCommands:
    def __init__(self, board=None):
        self.board = board

    def suggest_test_points(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Identify nets that should have test points."""
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        try:
            import pcbnew
        except ImportError:
            return {"success": False, "error": "pcbnew not available"}

        include_power = params.get("include_power", True)
        include_debug = params.get("include_debug", True)
        include_comms = params.get("include_comms", True)
        custom_nets = params.get("custom_nets", [])
        exclude_nets = params.get("exclude_nets", [])

        all_nets = {}
        for net in self.board.GetNetsByName().values():
            name = net.GetNetname()
            if name and name not in exclude_nets:
                all_nets[name] = net

        existing_tps = set()
        for fp in self.board.GetFootprints():
            ref = fp.GetReference()
            if ref.startswith("TP"):
                for pad in fp.Pads():
                    net_name = pad.GetNet().GetNetname()
                    if net_name:
                        existing_tps.add(net_name)

        suggestions = {"power": [], "debug": [], "communication": [], "custom": [], "other": []}

        for name, net in all_nets.items():
            if name in existing_tps:
                continue

            upper = name.upper()
            category = None

            if include_power:
                power_keywords = ["VCC", "VDD", "3V3", "3.3V", "5V", "12V", "1V8",
                                  "1.8V", "2.5V", "VBAT", "VBUS", "VREF", "AVCC",
                                  "AVDD", "DVCC", "DVDD"]
                gnd_keywords = ["GND", "AGND", "DGND", "PGND"]
                if any(kw in upper for kw in power_keywords):
                    category = "power"
                elif any(kw in upper for kw in gnd_keywords):
                    category = "power"

            if not category and include_debug:
                debug_keywords = ["SWDIO", "SWCLK", "SWO", "JTAG", "TDI", "TDO",
                                  "TMS", "TCK", "RESET", "RST", "NRST", "BOOT"]
                if any(kw in upper for kw in debug_keywords):
                    category = "debug"

            if not category and include_comms:
                comm_keywords = ["SCL", "SDA", "MOSI", "MISO", "SCK", "TX", "RX",
                                 "UART", "CAN_H", "CAN_L", "USB_D"]
                if any(kw in upper for kw in comm_keywords):
                    category = "communication"

            if name in custom_nets:
                category = "custom"

            if category:
                suggestions[category].append({
                    "net_name": name,
                    "priority": "high" if category in ("debug", "power") else "medium",
                })

        total = sum(len(v) for v in suggestions.values())
        return {
            "success": True,
            "total_suggestions": total,
            "already_covered": len(existing_tps),
            "existing_test_points": sorted(existing_tps)[:20],
            "suggestions": suggestions,
        }

    def add_test_points(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add test point footprints to specified nets."""
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        try:
            import pcbnew
        except ImportError:
            return {"success": False, "error": "pcbnew not available"}

        net_names = params.get("net_names", [])
        style = params.get("style", "smd")  # smd, through_hole, pad_only
        size_mm = params.get("size_mm", 1.0)
        placement = params.get("placement", "auto")  # auto, edge, or {x, y}
        side = params.get("side", "front")  # front or back

        if not net_names:
            return {"success": False, "error": "No net names specified"}

        footprint_lib = "TestPoint"
        if style == "smd":
            fp_name = f"TestPoint_Pad_D{size_mm:.1f}mm"
        elif style == "through_hole":
            fp_name = f"TestPoint_THTPad_D{size_mm:.1f}mm_Drill0.5mm"
        else:
            fp_name = f"TestPoint_Pad_D{size_mm:.1f}mm"

        nets = self.board.GetNetsByName()
        bbox = self.board.GetBoardEdgesBoundingBox()
        board_right = bbox.GetX() + bbox.GetWidth()
        board_bottom = bbox.GetY() + bbox.GetHeight()

        tp_count = 0
        existing_refs = set()
        for fp in self.board.GetFootprints():
            ref = fp.GetReference()
            if ref.startswith("TP"):
                try:
                    existing_refs.add(int(ref[2:]))
                except ValueError:
                    pass

        next_tp_num = max(existing_refs, default=0) + 1
        placed = []

        spacing = int(2.0 * 1e6)
        start_x = board_right + int(5e6)
        current_y = bbox.GetY() + int(2e6)

        for net_name in net_names:
            if net_name not in nets:
                placed.append({"net": net_name, "placed": False, "error": "net not found"})
                continue

            net = nets[net_name]

            try:
                lib_path = None
                for table_entry in pcbnew.GetBoard().GetProject().PcbFootprintLibs().GetLogicalLibs():
                    if "TestPoint" in table_entry:
                        lib_path = table_entry
                        break

                fp = pcbnew.FootprintLoad(lib_path or footprint_lib, fp_name)
            except Exception:
                fp = pcbnew.PCB_FOOTPRINT(self.board)
                pad = pcbnew.PAD(fp)
                pad_size = int(size_mm * 1e6)
                pad.SetSize(pcbnew.VECTOR2I(pad_size, pad_size))
                if style == "through_hole":
                    pad.SetDrillSize(pcbnew.VECTOR2I(int(0.5e6), int(0.5e6)))
                    pad.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
                    pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
                else:
                    pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
                    pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
                    layer = pcbnew.F_Cu if side == "front" else pcbnew.B_Cu
                    pad.SetLayerSet(pcbnew.LSET(layer))
                pad.SetName("1")
                pad.SetNet(net)
                fp.Add(pad)

            ref_str = f"TP{next_tp_num}"
            fp.SetReference(ref_str)
            fp.SetValue(net_name)

            x = start_x
            y = current_y
            fp.SetPosition(pcbnew.VECTOR2I(x, y))

            if side == "back":
                fp.Flip(fp.GetPosition(), False)

            self.board.Add(fp)
            tp_count += 1
            next_tp_num += 1
            current_y += spacing

            placed.append({
                "net": net_name,
                "placed": True,
                "reference": ref_str,
                "position_mm": {"x": x / 1e6, "y": y / 1e6},
            })

        return {
            "success": True,
            "test_points_added": tp_count,
            "style": style,
            "side": side,
            "placed": placed,
            "note": "Test points placed to the right of the board. Move them to desired locations.",
        }

    def audit_test_coverage(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Audit test point coverage — which critical nets have/lack test points."""
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        try:
            import pcbnew
        except ImportError:
            return {"success": False, "error": "pcbnew not available"}

        covered_nets = set()
        for fp in self.board.GetFootprints():
            if fp.GetReference().startswith("TP"):
                for pad in fp.Pads():
                    net_name = pad.GetNet().GetNetname()
                    if net_name:
                        covered_nets.add(net_name)

        all_nets = set()
        for net in self.board.GetNetsByName().values():
            name = net.GetNetname()
            if name:
                all_nets.add(name)

        critical_missing = []
        critical_covered = []

        for pattern in CRITICAL_NET_PATTERNS:
            for net_name in all_nets:
                if pattern.upper() in net_name.upper():
                    if net_name in covered_nets:
                        critical_covered.append(net_name)
                    else:
                        critical_missing.append(net_name)

        critical_missing = sorted(set(critical_missing))
        critical_covered = sorted(set(critical_covered))

        coverage_pct = 0
        if critical_covered or critical_missing:
            total = len(critical_covered) + len(critical_missing)
            coverage_pct = round(len(critical_covered) / total * 100, 1)

        return {
            "success": True,
            "total_test_points": len(covered_nets),
            "critical_coverage_pct": coverage_pct,
            "critical_covered": critical_covered,
            "critical_missing": critical_missing,
            "all_covered_nets": sorted(covered_nets)[:50],
        }
