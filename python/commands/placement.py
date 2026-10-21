"""
Component Placement Optimizer

Automated and semi-automated component placement:
- Group components by function (power, bypass, signal chain)
- Place bypass caps near their associated ICs
- Arrange components to minimize total ratsnest length
- Snap to grid with configurable pitch
- Fan-out BGA patterns
"""

import math
import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Standard grid pitches in mm
GRID_PITCHES = {
    "fine": 0.1,
    "standard": 0.5,
    "coarse": 1.0,
    "imperial": 1.27,  # 50mil
}


class PlacementCommands:
    def __init__(self, board=None):
        self.board = board

    def set_board(self, board):
        self.board = board

    def auto_place_bypass_caps(self, max_distance_mm: float = 3.0,
                               preferred_side: str = "same",
                               grid_pitch: float = 0.5) -> Dict[str, Any]:
        """
        Automatically place bypass/decoupling capacitors near their ICs.

        Analyzes net connectivity to find cap-IC associations, then places
        each cap within max_distance_mm of its IC's power pin.

        Args:
            max_distance_mm: Maximum placement distance from IC power pin
            preferred_side: 'same' (same layer as IC) or 'opposite'
            grid_pitch: Snap-to-grid pitch in mm
        """
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        try:
            import pcbnew
            board = self.board

            # Build net-to-component mapping
            power_net_pattern = ["VCC", "VDD", "3V3", "3.3V", "5V", "1V8", "1.8V",
                                "2V5", "VBAT", "VBUS", "AVCC", "AVDD", "DVCC", "DVDD"]
            gnd_pattern = ["GND", "VSS", "AGND", "DGND", "PGND"]

            # Find ICs (U* references with multiple pins)
            ics = {}
            for fp in board.GetFootprints():
                ref = fp.GetReference()
                if ref.startswith("U") and len(fp.Pads()) >= 4:
                    power_pins = []
                    gnd_pins = []
                    for pad in fp.Pads():
                        net = pad.GetNetname().upper()
                        if any(p in net for p in power_net_pattern):
                            power_pins.append({
                                "net": pad.GetNetname(),
                                "x": pcbnew.ToMM(pad.GetPosition().x),
                                "y": pcbnew.ToMM(pad.GetPosition().y),
                            })
                        elif any(p in net for p in gnd_pattern):
                            gnd_pins.append({
                                "net": pad.GetNetname(),
                                "x": pcbnew.ToMM(pad.GetPosition().x),
                                "y": pcbnew.ToMM(pad.GetPosition().y),
                            })
                    if power_pins:
                        ics[ref] = {
                            "footprint": fp,
                            "power_pins": power_pins,
                            "gnd_pins": gnd_pins,
                        }

            # Find capacitors
            caps = {}
            for fp in board.GetFootprints():
                ref = fp.GetReference()
                if ref.startswith("C") and ref[1:].isdigit():
                    pads = list(fp.Pads())
                    if len(pads) == 2:
                        nets = [pad.GetNetname() for pad in pads]
                        has_power = any(
                            any(p in n.upper() for p in power_net_pattern)
                            for n in nets
                        )
                        has_gnd = any(
                            any(p in n.upper() for p in gnd_pattern)
                            for n in nets
                        )
                        if has_power and has_gnd:
                            power_net = next(
                                n for n in nets
                                if any(p in n.upper() for p in power_net_pattern)
                            )
                            caps[ref] = {
                                "footprint": fp,
                                "power_net": power_net,
                                "current_x": pcbnew.ToMM(fp.GetPosition().x),
                                "current_y": pcbnew.ToMM(fp.GetPosition().y),
                            }

            # Match caps to ICs by shared power net
            placements = []
            for cap_ref, cap_info in caps.items():
                best_ic = None
                best_pin = None
                best_dist = float('inf')

                for ic_ref, ic_info in ics.items():
                    for pin in ic_info["power_pins"]:
                        if pin["net"] == cap_info["power_net"]:
                            dist = math.sqrt(
                                (cap_info["current_x"] - pin["x"]) ** 2 +
                                (cap_info["current_y"] - pin["y"]) ** 2
                            )
                            if dist < best_dist:
                                best_dist = dist
                                best_ic = ic_ref
                                best_pin = pin

                if best_ic and best_pin:
                    # Calculate target position near the IC's power pin
                    target_x, target_y = self._find_placement_near_pin(
                        best_pin["x"], best_pin["y"],
                        max_distance_mm, grid_pitch, board
                    )

                    needs_move = best_dist > max_distance_mm

                    placement = {
                        "cap": cap_ref,
                        "ic": best_ic,
                        "net": cap_info["power_net"],
                        "current_distance_mm": round(best_dist, 2),
                        "needs_move": needs_move,
                    }

                    if needs_move:
                        fp = cap_info["footprint"]
                        fp.SetPosition(pcbnew.VECTOR2I(
                            int(pcbnew.FromMM(target_x)),
                            int(pcbnew.FromMM(target_y))
                        ))
                        placement["new_x"] = target_x
                        placement["new_y"] = target_y
                        placement["new_distance_mm"] = round(math.sqrt(
                            (target_x - best_pin["x"]) ** 2 +
                            (target_y - best_pin["y"]) ** 2
                        ), 2)

                    placements.append(placement)

            if placements:
                pcbnew.Refresh()

            moved = sum(1 for p in placements if p["needs_move"])
            return {
                "success": True,
                "message": f"Analyzed {len(placements)} bypass caps, moved {moved}",
                "placements": placements,
                "summary": {
                    "total_caps": len(placements),
                    "moved": moved,
                    "already_ok": len(placements) - moved,
                },
            }

        except Exception as e:
            logger.error(f"Auto-place bypass caps failed: {e}")
            return {"success": False, "error": str(e)}

    def _find_placement_near_pin(self, pin_x: float, pin_y: float,
                                  max_dist: float, grid: float,
                                  board) -> Tuple[float, float]:
        """Find the nearest grid-aligned position near a pin that isn't occupied."""
        import pcbnew

        # Try positions in a spiral outward from the pin
        for r in [i * grid for i in range(1, int(max_dist / grid) + 2)]:
            for angle_deg in range(0, 360, 45):
                angle = math.radians(angle_deg)
                x = pin_x + r * math.cos(angle)
                y = pin_y + r * math.sin(angle)

                # Snap to grid
                x = round(x / grid) * grid
                y = round(y / grid) * grid

                # Check if position is occupied
                occupied = False
                test_pt = pcbnew.VECTOR2I(int(pcbnew.FromMM(x)), int(pcbnew.FromMM(y)))
                for fp in board.GetFootprints():
                    fp_pos = fp.GetPosition()
                    dist = math.sqrt(
                        (pcbnew.ToMM(fp_pos.x) - x) ** 2 +
                        (pcbnew.ToMM(fp_pos.y) - y) ** 2
                    )
                    if dist < 1.0:  # 1mm minimum clearance
                        occupied = True
                        break

                if not occupied:
                    return (x, y)

        # Fallback: just place near the pin
        return (round(pin_x / grid) * grid + grid,
                round(pin_y / grid) * grid + grid)

    def group_by_function(self) -> Dict[str, Any]:
        """
        Analyze the board and group components by function.

        Groups: power (regulators, inductors, big caps), bypass (small caps near ICs),
        connectors, ICs, passives (resistors/small caps in signal path), crystals.
        """
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        try:
            import pcbnew
            board = self.board

            groups = {
                "ics": [],
                "power": [],
                "bypass_caps": [],
                "signal_passives": [],
                "connectors": [],
                "crystals": [],
                "other": [],
            }

            for fp in board.GetFootprints():
                ref = fp.GetReference()
                value = fp.GetValue().upper()
                pad_count = len(fp.Pads())
                pos = fp.GetPosition()

                info = {
                    "reference": ref,
                    "value": fp.GetValue(),
                    "x": pcbnew.ToMM(pos.x),
                    "y": pcbnew.ToMM(pos.y),
                    "pad_count": pad_count,
                }

                # Classify
                if ref.startswith("U"):
                    groups["ics"].append(info)
                elif ref.startswith("J") or ref.startswith("P"):
                    groups["connectors"].append(info)
                elif ref.startswith("Y") or ref.startswith("X"):
                    groups["crystals"].append(info)
                elif ref.startswith("L") or (ref.startswith("D") and "SCHOTTKY" in value):
                    groups["power"].append(info)
                elif ref.startswith("C"):
                    # Big caps are power, small caps are bypass
                    if any(u in value for u in ["100U", "47U", "22U", "10U", "470U"]):
                        groups["power"].append(info)
                    else:
                        groups["bypass_caps"].append(info)
                elif ref.startswith("R") or ref.startswith("FB"):
                    groups["signal_passives"].append(info)
                else:
                    groups["other"].append(info)

            return {
                "success": True,
                "groups": groups,
                "summary": {k: len(v) for k, v in groups.items()},
            }

        except Exception as e:
            logger.error(f"Group by function failed: {e}")
            return {"success": False, "error": str(e)}

    def optimize_placement(self, references: Optional[List[str]] = None,
                           iterations: int = 100,
                           grid_pitch: float = 0.5,
                           dry_run: bool = True) -> Dict[str, Any]:
        """
        Optimize component placement to minimize total ratsnest (unrouted) length.

        Uses simulated annealing: swaps and shifts components, keeping moves that
        reduce total wire length.

        Args:
            references: Components to optimize (None = all non-fixed)
            iterations: SA iterations (more = better but slower)
            grid_pitch: Grid snap pitch in mm
            dry_run: If True, only report improvements without moving components
        """
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        try:
            import pcbnew
            import random
            board = self.board

            # Get movable footprints
            footprints = {}
            for fp in board.GetFootprints():
                ref = fp.GetReference()
                if references and ref not in references:
                    continue
                if fp.IsLocked():
                    continue
                pos = fp.GetPosition()
                footprints[ref] = {
                    "fp": fp,
                    "x": pcbnew.ToMM(pos.x),
                    "y": pcbnew.ToMM(pos.y),
                    "best_x": pcbnew.ToMM(pos.x),
                    "best_y": pcbnew.ToMM(pos.y),
                }

            if not footprints:
                return {"success": False, "error": "No movable components found"}

            # Build connectivity: for each component, list its connected components
            connectivity = {}
            for ref, info in footprints.items():
                fp = info["fp"]
                connected = set()
                for pad in fp.Pads():
                    net = pad.GetNetname()
                    if not net:
                        continue
                    for other_fp in board.GetFootprints():
                        other_ref = other_fp.GetReference()
                        if other_ref == ref:
                            continue
                        for other_pad in other_fp.Pads():
                            if other_pad.GetNetname() == net:
                                connected.add(other_ref)
                                break
                connectivity[ref] = list(connected)

            # Calculate initial total wire length
            def calc_total_length():
                total = 0
                for ref, conns in connectivity.items():
                    if ref not in footprints:
                        continue
                    x1, y1 = footprints[ref]["x"], footprints[ref]["y"]
                    for other in conns:
                        if other in footprints:
                            x2, y2 = footprints[other]["x"], footprints[other]["y"]
                        else:
                            # Fixed component position
                            for fp in board.GetFootprints():
                                if fp.GetReference() == other:
                                    pos = fp.GetPosition()
                                    x2, y2 = pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)
                                    break
                            else:
                                continue
                        total += math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
                return total

            initial_length = calc_total_length()
            best_length = initial_length
            refs = list(footprints.keys())

            # Simulated annealing
            temperature = 10.0
            cooling = 0.95

            for i in range(iterations):
                # Pick a random component and try moving it
                ref = random.choice(refs)
                old_x, old_y = footprints[ref]["x"], footprints[ref]["y"]

                # Random shift
                dx = random.gauss(0, temperature) * grid_pitch
                dy = random.gauss(0, temperature) * grid_pitch

                new_x = round((old_x + dx) / grid_pitch) * grid_pitch
                new_y = round((old_y + dy) / grid_pitch) * grid_pitch

                footprints[ref]["x"] = new_x
                footprints[ref]["y"] = new_y

                new_length = calc_total_length()

                # Accept or reject
                delta = new_length - best_length
                if delta < 0 or random.random() < math.exp(-delta / max(temperature, 0.01)):
                    if new_length < best_length:
                        best_length = new_length
                        for r in refs:
                            footprints[r]["best_x"] = footprints[r]["x"]
                            footprints[r]["best_y"] = footprints[r]["y"]
                else:
                    footprints[ref]["x"] = old_x
                    footprints[ref]["y"] = old_y

                temperature *= cooling

            improvement_pct = ((initial_length - best_length) / initial_length * 100
                              if initial_length > 0 else 0)

            moves = []
            for ref in refs:
                info = footprints[ref]
                orig_pos = info["fp"].GetPosition()
                orig_x = pcbnew.ToMM(orig_pos.x)
                orig_y = pcbnew.ToMM(orig_pos.y)

                if abs(info["best_x"] - orig_x) > 0.01 or abs(info["best_y"] - orig_y) > 0.01:
                    moves.append({
                        "reference": ref,
                        "from": {"x": round(orig_x, 2), "y": round(orig_y, 2)},
                        "to": {"x": round(info["best_x"], 2), "y": round(info["best_y"], 2)},
                    })

                    if not dry_run:
                        info["fp"].SetPosition(pcbnew.VECTOR2I(
                            int(pcbnew.FromMM(info["best_x"])),
                            int(pcbnew.FromMM(info["best_y"]))
                        ))

            if not dry_run and moves:
                pcbnew.Refresh()

            return {
                "success": True,
                "dry_run": dry_run,
                "initial_ratsnest_length_mm": round(initial_length, 1),
                "optimized_ratsnest_length_mm": round(best_length, 1),
                "improvement_pct": round(improvement_pct, 1),
                "components_to_move": len(moves),
                "total_components": len(refs),
                "iterations": iterations,
                "moves": moves[:20],
                "message": (
                    f"Placement optimization would reduce ratsnest by {improvement_pct:.1f}% "
                    f"({len(moves)} moves). " +
                    ("Run with dry_run=false to apply." if dry_run else "Applied.")
                ),
            }

        except Exception as e:
            logger.error(f"Optimize placement failed: {e}")
            return {"success": False, "error": str(e)}

    def arrange_in_line(self, references: List[str], start_x: float, start_y: float,
                        direction: str = "horizontal", spacing_mm: float = 2.0,
                        grid_pitch: float = 0.5) -> Dict[str, Any]:
        """
        Arrange components in a line (useful for resistor arrays, LED strips, etc.).

        Args:
            references: List of component references to arrange
            start_x: Starting X position in mm
            start_y: Starting Y position in mm
            direction: 'horizontal' or 'vertical'
            spacing_mm: Center-to-center spacing in mm
            grid_pitch: Grid snap in mm
        """
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        try:
            import pcbnew
            board = self.board

            placed = []
            for i, ref in enumerate(references):
                fp = None
                for f in board.GetFootprints():
                    if f.GetReference() == ref:
                        fp = f
                        break

                if not fp:
                    placed.append({"reference": ref, "error": "not found"})
                    continue

                if direction == "horizontal":
                    x = start_x + i * spacing_mm
                    y = start_y
                else:
                    x = start_x
                    y = start_y + i * spacing_mm

                x = round(x / grid_pitch) * grid_pitch
                y = round(y / grid_pitch) * grid_pitch

                fp.SetPosition(pcbnew.VECTOR2I(
                    int(pcbnew.FromMM(x)),
                    int(pcbnew.FromMM(y))
                ))
                placed.append({"reference": ref, "x": x, "y": y})

            pcbnew.Refresh()

            return {
                "success": True,
                "message": f"Arranged {len(placed)} components in a {direction} line",
                "placed": placed,
            }

        except Exception as e:
            logger.error(f"Arrange in line failed: {e}")
            return {"success": False, "error": str(e)}

    def spread_components(self, spacing_mm: float = 5.0,
                          center_x: float = 100.0,
                          center_y: float = 100.0) -> Dict[str, Any]:
        """
        Spread all overlapping components apart on a grid. Useful as a first
        step before optimizing placement.

        Args:
            spacing_mm: Minimum spacing between component centers
            center_x: Center X of the spread area
            center_y: Center Y of the spread area
        """
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        try:
            import pcbnew
            board = self.board

            footprints = [fp for fp in board.GetFootprints() if not fp.IsLocked()]
            n = len(footprints)
            if n == 0:
                return {"success": False, "error": "No unlocked components"}

            # Arrange in a grid
            cols = max(1, int(math.ceil(math.sqrt(n))))
            rows = max(1, int(math.ceil(n / cols)))

            start_x = center_x - (cols * spacing_mm) / 2
            start_y = center_y - (rows * spacing_mm) / 2

            moved = []
            for i, fp in enumerate(footprints):
                col = i % cols
                row = i // cols
                x = start_x + col * spacing_mm
                y = start_y + row * spacing_mm

                fp.SetPosition(pcbnew.VECTOR2I(
                    int(pcbnew.FromMM(x)),
                    int(pcbnew.FromMM(y))
                ))
                moved.append({
                    "reference": fp.GetReference(),
                    "x": x, "y": y,
                })

            pcbnew.Refresh()

            return {
                "success": True,
                "message": f"Spread {n} components on a {cols}x{rows} grid",
                "grid": {"cols": cols, "rows": rows, "spacing_mm": spacing_mm},
                "moved": moved[:30],
            }

        except Exception as e:
            logger.error(f"Spread components failed: {e}")
            return {"success": False, "error": str(e)}
