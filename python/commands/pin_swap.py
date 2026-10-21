"""
Pin Swap Optimization for KiCAD MCP Server.

Identifies functionally equivalent pins on ICs and suggests swaps
that would simplify routing (reduce trace crossings and layer changes).
"""

import math
import logging
from typing import Dict, Any, List, Tuple, Optional, Set

logger = logging.getLogger("kicad_interface")

# Common equivalent pin groups by IC type
KNOWN_EQUIVALENCES = {
    "STM32": {
        "gpio": ["PA", "PB", "PC", "PD", "PE"],
        "adc": ["ADC_IN"],
        "timer": ["TIM"],
    },
    "ESP32": {
        "gpio": ["GPIO"],
        "adc": ["ADC"],
    },
    "74HC": {
        "gate_inputs": True,  # All gate inputs are swappable within a gate
    },
}


class PinSwapCommands:
    def __init__(self, board=None):
        self.board = board

    def find_swappable_pins(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Find pins that could be swapped to simplify routing."""
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        try:
            import pcbnew
        except ImportError:
            return {"success": False, "error": "pcbnew not available"}

        reference = params.get("reference")
        if not reference:
            return {"success": False, "error": "Component reference required"}

        fp = None
        for f in self.board.GetFootprints():
            if f.GetReference() == reference:
                fp = f
                break

        if not fp:
            return {"success": False, "error": f"Component '{reference}' not found"}

        pads_info = []
        for pad in fp.Pads():
            pos = pad.GetPosition()
            net = pad.GetNet()
            pads_info.append({
                "name": pad.GetName(),
                "net_name": net.GetNetname() if net else "",
                "net_code": net.GetNetCode() if net else 0,
                "x": pos.x / 1e6,
                "y": pos.y / 1e6,
                "function": pad.GetPinFunction() if hasattr(pad, 'GetPinFunction') else "",
                "type": pad.GetPinType() if hasattr(pad, 'GetPinType') else "",
            })

        gpio_pins = []
        power_pins = []
        other_pins = []

        for p in pads_info:
            upper_name = p["name"].upper()
            upper_net = p["net_name"].upper()
            upper_func = p.get("function", "").upper()

            if any(kw in upper_net for kw in ["VCC", "VDD", "GND", "VSS", "VBAT"]):
                power_pins.append(p)
            elif any(kw in upper_func for kw in ["GPIO", "IO", "PORT"]):
                gpio_pins.append(p)
            elif upper_name.startswith(("PA", "PB", "PC", "PD", "PE", "PF", "PG")):
                gpio_pins.append(p)
            elif upper_name.startswith("GPIO"):
                gpio_pins.append(p)
            else:
                other_pins.append(p)

        swap_candidates = []
        if len(gpio_pins) >= 2:
            connected_gpios = [p for p in gpio_pins if p["net_name"]]
            for i in range(len(connected_gpios)):
                for j in range(i + 1, len(connected_gpios)):
                    p1 = connected_gpios[i]
                    p2 = connected_gpios[j]

                    net1_targets = self._find_net_targets(p1["net_name"], reference)
                    net2_targets = self._find_net_targets(p2["net_name"], reference)

                    if not net1_targets or not net2_targets:
                        continue

                    current_cost = self._routing_cost(
                        p1["x"], p1["y"], net1_targets
                    ) + self._routing_cost(
                        p2["x"], p2["y"], net2_targets
                    )

                    swapped_cost = self._routing_cost(
                        p1["x"], p1["y"], net2_targets
                    ) + self._routing_cost(
                        p2["x"], p2["y"], net1_targets
                    )

                    if swapped_cost < current_cost * 0.85:
                        improvement = round((1 - swapped_cost / current_cost) * 100, 1)
                        swap_candidates.append({
                            "pin1": {"name": p1["name"], "net": p1["net_name"]},
                            "pin2": {"name": p2["name"], "net": p2["net_name"]},
                            "improvement_pct": improvement,
                            "current_distance_mm": round(current_cost, 2),
                            "swapped_distance_mm": round(swapped_cost, 2),
                        })

        swap_candidates.sort(key=lambda s: -s["improvement_pct"])

        return {
            "success": True,
            "reference": reference,
            "total_pins": len(pads_info),
            "gpio_pins": len(gpio_pins),
            "swap_candidates": swap_candidates[:20],
            "note": "Pin swaps must also be applied in the schematic to maintain consistency.",
        }

    def execute_pin_swap(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a pin swap on the PCB (swap net assignments between two pads)."""
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        try:
            import pcbnew
        except ImportError:
            return {"success": False, "error": "pcbnew not available"}

        reference = params.get("reference")
        pin1 = params.get("pin1")
        pin2 = params.get("pin2")

        if not all([reference, pin1, pin2]):
            return {"success": False, "error": "reference, pin1, and pin2 are required"}

        fp = None
        for f in self.board.GetFootprints():
            if f.GetReference() == reference:
                fp = f
                break

        if not fp:
            return {"success": False, "error": f"Component '{reference}' not found"}

        pad1 = pad2 = None
        for pad in fp.Pads():
            if pad.GetName() == str(pin1):
                pad1 = pad
            elif pad.GetName() == str(pin2):
                pad2 = pad

        if not pad1 or not pad2:
            return {"success": False, "error": f"Could not find both pins ({pin1}, {pin2})"}

        net1 = pad1.GetNet()
        net2 = pad2.GetNet()

        pad1.SetNet(net2)
        pad2.SetNet(net1)

        return {
            "success": True,
            "reference": reference,
            "swap": {
                "pin1": {"name": pin1, "old_net": net1.GetNetname(), "new_net": net2.GetNetname()},
                "pin2": {"name": pin2, "old_net": net2.GetNetname(), "new_net": net1.GetNetname()},
            },
            "warning": "This swap is PCB-only. Update the schematic to match!",
        }

    def suggest_all_swaps(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Scan all ICs on the board and suggest beneficial pin swaps."""
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        try:
            import pcbnew
        except ImportError:
            return {"success": False, "error": "pcbnew not available"}

        min_pins = params.get("min_pins", 8)
        all_suggestions = []

        for fp in self.board.GetFootprints():
            pad_count = len(list(fp.Pads()))
            if pad_count < min_pins:
                continue

            ref = fp.GetReference()
            result = self.find_swappable_pins({"reference": ref})
            if result.get("success") and result.get("swap_candidates"):
                all_suggestions.append({
                    "reference": ref,
                    "pin_count": pad_count,
                    "swap_count": len(result["swap_candidates"]),
                    "best_swap": result["swap_candidates"][0],
                    "total_improvement_pct": sum(
                        s["improvement_pct"] for s in result["swap_candidates"]
                    ),
                })

        all_suggestions.sort(key=lambda s: -s["total_improvement_pct"])

        return {
            "success": True,
            "components_analyzed": len([f for f in self.board.GetFootprints() if len(list(f.Pads())) >= min_pins]),
            "components_with_swaps": len(all_suggestions),
            "suggestions": all_suggestions[:20],
        }

    def _find_net_targets(self, net_name: str, exclude_ref: str) -> List[Tuple[float, float]]:
        """Find all pad positions on a net excluding a specific component."""
        targets = []
        if not self.board:
            return targets

        for fp in self.board.GetFootprints():
            if fp.GetReference() == exclude_ref:
                continue
            for pad in fp.Pads():
                if pad.GetNet().GetNetname() == net_name:
                    pos = pad.GetPosition()
                    targets.append((pos.x / 1e6, pos.y / 1e6))
        return targets

    def _routing_cost(self, x: float, y: float, targets: List[Tuple[float, float]]) -> float:
        """Estimate routing cost as sum of Manhattan distances to targets."""
        cost = 0
        for tx, ty in targets:
            cost += abs(x - tx) + abs(y - ty)
        return cost
