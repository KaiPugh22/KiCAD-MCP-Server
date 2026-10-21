"""
Floorplanner for KiCAD MCP Server.

Generates spatial floorplans from hierarchical schematics:
- Groups components by schematic sheet / functional block
- Sizes each block by component area
- Places power/analog/digital in separate zones
- Pins connectors to board edges
"""

import math
import logging
from typing import Dict, Any, List, Tuple, Optional

logger = logging.getLogger("kicad_interface")

FUNCTIONAL_ZONES = {
    "power": {
        "prefixes": ["U"],
        "value_keywords": ["regulator", "ldo", "buck", "boost", "converter", "pmic"],
        "net_keywords": ["VCC", "VDD", "VIN", "VOUT", "VBUS"],
    },
    "analog": {
        "prefixes": ["U"],
        "value_keywords": ["opamp", "adc", "dac", "amplifier", "sensor", "codec"],
        "net_keywords": ["AIN", "AOUT", "ANALOG", "ADC", "DAC"],
    },
    "rf": {
        "prefixes": ["U", "L", "C"],
        "value_keywords": ["antenna", "balun", "filter", "rf", "lna", "pa", "mixer"],
        "net_keywords": ["RF", "ANT"],
    },
    "digital": {
        "prefixes": ["U"],
        "value_keywords": ["mcu", "cpu", "fpga", "flash", "ram", "eeprom", "stm32", "esp32"],
        "net_keywords": [],
    },
    "connector": {
        "prefixes": ["J", "P", "CN"],
        "value_keywords": ["connector", "header", "usb", "jack", "socket"],
        "net_keywords": [],
    },
    "passive": {
        "prefixes": ["R", "C", "L", "D", "F", "FB"],
        "value_keywords": [],
        "net_keywords": [],
    },
}


class FloorplannerCommands:
    def __init__(self, board=None):
        self.board = board

    def analyze_functional_blocks(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Identify functional blocks from component properties and nets."""
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        blocks = {}
        unclassified = []

        for fp in self.board.GetFootprints():
            ref = fp.GetReference()
            value = fp.GetValue().lower()
            bb = fp.GetBoundingBox()
            area = (bb.GetWidth() / 1e6) * (bb.GetHeight() / 1e6)

            pad_nets = set()
            for pad in fp.Pads():
                net = pad.GetNet()
                if net and net.GetNetname():
                    pad_nets.add(net.GetNetname().upper())

            zone = self._classify_component(ref, value, pad_nets)

            if zone not in blocks:
                blocks[zone] = {
                    "components": [],
                    "total_area_mm2": 0,
                    "component_count": 0,
                }

            blocks[zone]["components"].append(ref)
            blocks[zone]["total_area_mm2"] += area
            blocks[zone]["component_count"] += 1

        for zone in blocks:
            blocks[zone]["total_area_mm2"] = round(blocks[zone]["total_area_mm2"], 1)
            blocks[zone]["components"] = blocks[zone]["components"][:20]

        return {
            "success": True,
            "block_count": len(blocks),
            "blocks": blocks,
        }

    def generate_floorplan(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a spatial floorplan with zone assignments."""
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        try:
            import pcbnew
        except ImportError:
            return {"success": False, "error": "pcbnew not available"}

        board_margin_mm = params.get("board_margin_mm", 2.0)
        connector_edge = params.get("connector_edge", "left")
        power_position = params.get("power_position", "top_right")
        analog_position = params.get("analog_position", "bottom_left")
        dry_run = params.get("dry_run", True)

        bbox = self.board.GetBoardEdgesBoundingBox()
        bw = bbox.GetWidth() / 1e6
        bh = bbox.GetHeight() / 1e6
        bx = bbox.GetX() / 1e6
        by = bbox.GetY() / 1e6

        if bw <= 0 or bh <= 0:
            return {"success": False, "error": "Board has no defined outline"}

        analysis = self.analyze_functional_blocks({})
        if not analysis.get("success"):
            return analysis

        blocks = analysis["blocks"]
        margin = board_margin_mm

        zone_positions = {
            "top_left": (bx + margin, by + margin),
            "top_right": (bx + bw * 0.6, by + margin),
            "bottom_left": (bx + margin, by + bh * 0.6),
            "bottom_right": (bx + bw * 0.6, by + bh * 0.6),
            "center": (bx + bw * 0.25, by + bh * 0.25),
        }

        edge_positions = {
            "left": (bx + margin, by + bh * 0.3),
            "right": (bx + bw - margin - 10, by + bh * 0.3),
            "top": (bx + bw * 0.3, by + margin),
            "bottom": (bx + bw * 0.3, by + bh - margin - 10),
        }

        zone_assignments = {}

        if "connector" in blocks:
            pos = edge_positions.get(connector_edge, edge_positions["left"])
            zone_assignments["connector"] = {
                "zone": "connector",
                "position_mm": {"x": round(pos[0], 1), "y": round(pos[1], 1)},
                "components": blocks["connector"]["components"],
                "strategy": f"Pin to {connector_edge} edge",
            }

        if "power" in blocks:
            pos = zone_positions.get(power_position, zone_positions["top_right"])
            zone_assignments["power"] = {
                "zone": "power",
                "position_mm": {"x": round(pos[0], 1), "y": round(pos[1], 1)},
                "components": blocks["power"]["components"],
                "strategy": f"Isolate in {power_position}",
            }

        if "analog" in blocks:
            pos = zone_positions.get(analog_position, zone_positions["bottom_left"])
            zone_assignments["analog"] = {
                "zone": "analog",
                "position_mm": {"x": round(pos[0], 1), "y": round(pos[1], 1)},
                "components": blocks["analog"]["components"],
                "strategy": f"Isolate in {analog_position}, away from digital",
            }

        if "rf" in blocks:
            zone_assignments["rf"] = {
                "zone": "rf",
                "position_mm": {"x": round(bx + margin, 1), "y": round(by + margin, 1)},
                "components": blocks["rf"]["components"],
                "strategy": "Corner placement, minimize trace lengths",
            }

        if "digital" in blocks:
            pos = zone_positions.get("center", zone_positions["center"])
            zone_assignments["digital"] = {
                "zone": "digital",
                "position_mm": {"x": round(pos[0], 1), "y": round(pos[1], 1)},
                "components": blocks["digital"]["components"],
                "strategy": "Central placement for connectivity",
            }

        moves = []
        if not dry_run:
            for zone_name, assignment in zone_assignments.items():
                target_x = assignment["position_mm"]["x"]
                target_y = assignment["position_mm"]["y"]
                spacing = 3.0
                col = 0
                row = 0
                max_cols = max(1, int(math.sqrt(len(assignment["components"]))))

                for ref in assignment["components"]:
                    for fp in self.board.GetFootprints():
                        if fp.GetReference() == ref and not fp.IsLocked():
                            x = int((target_x + col * spacing) * 1e6)
                            y = int((target_y + row * spacing) * 1e6)
                            fp.SetPosition(pcbnew.VECTOR2I(x, y))
                            moves.append({"ref": ref, "zone": zone_name,
                                          "x_mm": round(x / 1e6, 1), "y_mm": round(y / 1e6, 1)})
                            col += 1
                            if col >= max_cols:
                                col = 0
                                row += 1
                            break

        return {
            "success": True,
            "dry_run": dry_run,
            "board_size_mm": {"width": round(bw, 1), "height": round(bh, 1)},
            "zone_assignments": zone_assignments,
            "components_moved": len(moves),
            "moves": moves[:30] if moves else [],
            "guidelines": [
                "Keep analog and digital grounds separate, join at a single point",
                "Place decoupling caps adjacent to their ICs",
                "Route power traces wide, away from signal traces",
                "Keep crystal and its load caps within 5mm of MCU",
            ],
        }

    def _classify_component(self, ref: str, value: str, nets: set) -> str:
        """Classify a component into a functional zone."""
        ref_prefix = ''.join(c for c in ref if c.isalpha())

        for zone_name, rules in FUNCTIONAL_ZONES.items():
            if zone_name == "passive":
                continue

            if any(kw in value for kw in rules.get("value_keywords", [])):
                return zone_name

            if ref_prefix in rules.get("prefixes", []) and zone_name == "connector":
                return zone_name

            for net in nets:
                if any(kw in net for kw in rules.get("net_keywords", [])):
                    if zone_name != "digital":
                        return zone_name

        if ref_prefix in ["R", "C", "L", "D", "F", "FB"]:
            return "passive"

        if ref_prefix in ["U"]:
            return "digital"

        return "other"

    def estimate_board_size(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Estimate minimum board size from component areas and count."""
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        total_area = 0
        component_count = 0
        max_dim = 0

        for fp in self.board.GetFootprints():
            bb = fp.GetBoundingBox()
            w = bb.GetWidth() / 1e6
            h = bb.GetHeight() / 1e6
            total_area += w * h
            max_dim = max(max_dim, w, h)
            component_count += 1

        packing_factor = params.get("packing_factor", 0.4)
        board_area = total_area / packing_factor

        side = math.sqrt(board_area)
        side = max(side, max_dim + 4)

        aspect = params.get("aspect_ratio", 1.0)
        width = side * math.sqrt(aspect)
        height = side / math.sqrt(aspect)

        return {
            "success": True,
            "component_count": component_count,
            "total_component_area_mm2": round(total_area, 1),
            "packing_factor": packing_factor,
            "estimated_board_area_mm2": round(board_area, 1),
            "suggested_size_mm": {
                "width": round(max(width, 20), 1),
                "height": round(max(height, 20), 1),
            },
        }
