"""
Pin Swap Optimization & GPIO Allocation for KiCAD MCP Server.

Identifies functionally equivalent pins on ICs and suggests swaps
that would simplify routing. Supports:
- Auto-detection of swappable GPIO pins
- User-defined swap groups
- Optimal assignment solver (greedy or exhaustive for small groups)
- Bulk swap execution
"""

import math
import logging
import itertools
from typing import Dict, Any, List, Tuple, Optional, Set

logger = logging.getLogger("kicad_interface")

KNOWN_EQUIVALENCES = {
    "STM32": {
        "gpio": ["PA", "PB", "PC", "PD", "PE"],
        "adc": ["ADC_IN"],
        "timer": ["TIM"],
        "spi_miso": ["SPI1_MISO", "SPI2_MISO", "SPI3_MISO"],
        "i2c_sda": ["I2C1_SDA", "I2C2_SDA", "I2C3_SDA"],
        "uart_tx": ["USART1_TX", "USART2_TX", "USART3_TX", "UART4_TX"],
    },
    "ESP32": {
        "gpio": ["GPIO"],
        "adc": ["ADC"],
        "touch": ["TOUCH"],
    },
    "74HC": {
        "gate_inputs": True,
    },
    "RP2040": {
        "gpio": ["GPIO"],
        "adc": ["ADC"],
        "pio": ["PIO"],
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

    def define_swap_group(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Define a group of pins that are functionally interchangeable."""
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        reference = params.get("reference")
        group_name = params.get("group_name", "custom")
        pin_names = params.get("pin_names", [])

        if not reference:
            return {"success": False, "error": "Component reference required"}
        if len(pin_names) < 2:
            return {"success": False, "error": "Need at least 2 pins in a swap group"}

        fp = None
        for f in self.board.GetFootprints():
            if f.GetReference() == reference:
                fp = f
                break
        if not fp:
            return {"success": False, "error": f"Component '{reference}' not found"}

        valid_pins = []
        invalid_pins = []
        for pin in pin_names:
            found = False
            for pad in fp.Pads():
                if pad.GetName() == str(pin):
                    net = pad.GetNet()
                    pos = pad.GetPosition()
                    valid_pins.append({
                        "name": str(pin),
                        "net": net.GetNetname() if net else "",
                        "x": pos.x / 1e6,
                        "y": pos.y / 1e6,
                    })
                    found = True
                    break
            if not found:
                invalid_pins.append(str(pin))

        if invalid_pins:
            return {"success": False, "error": f"Pins not found: {invalid_pins}"}

        return {
            "success": True,
            "reference": reference,
            "group_name": group_name,
            "pin_count": len(valid_pins),
            "pins": valid_pins,
            "note": "Use optimize_pin_assignment with these pins for optimal routing.",
        }

    def optimize_pin_assignment(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Find the optimal pin-to-net assignment for a swap group.
        Uses exhaustive search for <= 8 pins, greedy for larger groups."""
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        try:
            import pcbnew
        except ImportError:
            return {"success": False, "error": "pcbnew not available"}

        reference = params.get("reference")
        pin_names = params.get("pin_names")

        if not reference:
            return {"success": False, "error": "Component reference required"}

        fp = None
        for f in self.board.GetFootprints():
            if f.GetReference() == reference:
                fp = f
                break
        if not fp:
            return {"success": False, "error": f"Component '{reference}' not found"}

        if not pin_names:
            pin_names = []
            for pad in fp.Pads():
                name = pad.GetName()
                upper = name.upper()
                net = pad.GetNet()
                net_name = net.GetNetname() if net else ""
                if any(kw in net_name.upper() for kw in ["VCC", "VDD", "GND", "VSS", "VBAT"]):
                    continue
                if (upper.startswith(("PA", "PB", "PC", "PD", "PE", "PF", "PG")) or
                        upper.startswith("GPIO")):
                    if net_name:
                        pin_names.append(name)

        if len(pin_names) < 2:
            return {"success": False, "error": "Need at least 2 swappable pins with nets"}

        pins = []
        nets = []
        for pin_name in pin_names:
            for pad in fp.Pads():
                if pad.GetName() == str(pin_name):
                    net = pad.GetNet()
                    pos = pad.GetPosition()
                    pins.append({
                        "name": str(pin_name),
                        "x": pos.x / 1e6,
                        "y": pos.y / 1e6,
                    })
                    net_name = net.GetNetname() if net else ""
                    if net_name:
                        targets = self._find_net_targets(net_name, reference)
                        nets.append({
                            "net": net_name,
                            "targets": targets,
                        })
                    break

        if len(pins) != len(nets):
            return {"success": False, "error": "All pins must have net assignments"}

        n = len(pins)
        current_cost = sum(
            self._routing_cost(pins[i]["x"], pins[i]["y"], nets[i]["targets"])
            for i in range(n)
        )

        if n <= 8:
            best_perm = list(range(n))
            best_cost = current_cost
            for perm in itertools.permutations(range(n)):
                cost = sum(
                    self._routing_cost(pins[i]["x"], pins[i]["y"], nets[perm[i]]["targets"])
                    for i in range(n)
                )
                if cost < best_cost:
                    best_cost = cost
                    best_perm = list(perm)
            method = "exhaustive"
        else:
            best_perm = list(range(n))
            best_cost = current_cost
            improved = True
            while improved:
                improved = False
                for i in range(n):
                    for j in range(i + 1, n):
                        new_perm = best_perm[:]
                        new_perm[i], new_perm[j] = new_perm[j], new_perm[i]
                        cost = sum(
                            self._routing_cost(pins[k]["x"], pins[k]["y"],
                                               nets[new_perm[k]]["targets"])
                            for k in range(n)
                        )
                        if cost < best_cost:
                            best_cost = cost
                            best_perm = new_perm
                            improved = True
            method = "greedy_pairwise"

        swaps = []
        for i in range(n):
            if best_perm[i] != i:
                swaps.append({
                    "pin": pins[i]["name"],
                    "current_net": nets[i]["net"],
                    "optimal_net": nets[best_perm[i]]["net"],
                })

        improvement = round((1 - best_cost / current_cost) * 100, 1) if current_cost > 0 else 0

        return {
            "success": True,
            "reference": reference,
            "method": method,
            "pins_analyzed": n,
            "current_total_distance_mm": round(current_cost, 2),
            "optimal_total_distance_mm": round(best_cost, 2),
            "improvement_pct": improvement,
            "swaps_needed": len(swaps),
            "swaps": swaps,
            "note": "Use bulk_pin_swap to apply these swaps.",
        }

    def bulk_pin_swap(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Apply multiple pin swaps at once from an optimization result."""
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        try:
            import pcbnew
        except ImportError:
            return {"success": False, "error": "pcbnew not available"}

        reference = params.get("reference")
        swaps = params.get("swaps", [])

        if not reference:
            return {"success": False, "error": "Component reference required"}
        if not swaps:
            return {"success": False, "error": "No swaps to apply"}

        fp = None
        for f in self.board.GetFootprints():
            if f.GetReference() == reference:
                fp = f
                break
        if not fp:
            return {"success": False, "error": f"Component '{reference}' not found"}

        nets = self.board.GetNetsByName()
        applied = []
        errors = []

        pad_map = {}
        for pad in fp.Pads():
            pad_map[pad.GetName()] = pad

        for swap in swaps:
            pin = swap.get("pin")
            target_net = swap.get("optimal_net") or swap.get("new_net")

            if not pin or not target_net:
                errors.append({"pin": pin, "error": "Missing pin or target_net"})
                continue

            if pin not in pad_map:
                errors.append({"pin": pin, "error": f"Pin '{pin}' not found"})
                continue

            if target_net not in nets:
                errors.append({"pin": pin, "error": f"Net '{target_net}' not found"})
                continue

            pad = pad_map[pin]
            old_net = pad.GetNet().GetNetname() if pad.GetNet() else ""
            pad.SetNet(nets[target_net])

            applied.append({
                "pin": pin,
                "old_net": old_net,
                "new_net": target_net,
            })

        return {
            "success": True,
            "reference": reference,
            "swaps_applied": len(applied),
            "applied": applied,
            "errors": errors,
            "warning": "PCB-only changes. Update schematic to match!",
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
