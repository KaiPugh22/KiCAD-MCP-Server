"""
Bus-Aware Component Ordering for KiCAD MCP Server.

Reorders physical placement of bus-connected components (resistor packs,
ESD arrays, connectors) to match the pin order of the source IC,
eliminating net crossings before routing starts.
"""

import re
import math
import logging
from typing import Dict, Any, List, Tuple, Optional

logger = logging.getLogger("kicad_interface")


def _extract_bus_index(net_name: str) -> Optional[int]:
    """Extract numeric index from a bus net name like D0, ADDR[7], GPIO_12."""
    m = re.search(r'[\[_]?(\d+)\]?$', net_name)
    return int(m.group(1)) if m else None


def _extract_bus_prefix(net_name: str) -> str:
    """Get bus prefix: 'D0' -> 'D', 'ADDR[7]' -> 'ADDR', 'GPIO_12' -> 'GPIO_'."""
    m = re.search(r'[\[_]?\d+\]?$', net_name)
    return net_name[:m.start()] if m else net_name


class BusOrderingCommands:
    def __init__(self, board=None):
        self.board = board

    def detect_bus_groups(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Detect bus-connected component groups on the board."""
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        min_width = params.get("min_bus_width", 2)

        net_to_pads = {}
        for fp in self.board.GetFootprints():
            ref = fp.GetReference()
            for pad in fp.Pads():
                net = pad.GetNet()
                if not net:
                    continue
                name = net.GetNetname()
                if not name:
                    continue
                pos = pad.GetPosition()
                if name not in net_to_pads:
                    net_to_pads[name] = []
                net_to_pads[name].append({
                    "ref": ref,
                    "pad": pad.GetName(),
                    "x": pos.x / 1e6,
                    "y": pos.y / 1e6,
                })

        bus_candidates = {}
        for net_name in net_to_pads:
            idx = _extract_bus_index(net_name)
            if idx is None:
                continue
            prefix = _extract_bus_prefix(net_name)
            if prefix not in bus_candidates:
                bus_candidates[prefix] = []
            bus_candidates[prefix].append((idx, net_name))

        buses = []
        for prefix, members in bus_candidates.items():
            if len(members) < min_width:
                continue
            members.sort(key=lambda m: m[0])

            connected_refs = set()
            for _, net_name in members:
                for pad_info in net_to_pads.get(net_name, []):
                    connected_refs.add(pad_info["ref"])

            ref_connections = {}
            for ref in connected_refs:
                count = 0
                for _, net_name in members:
                    for pad_info in net_to_pads.get(net_name, []):
                        if pad_info["ref"] == ref:
                            count += 1
                ref_connections[ref] = count

            source_ref = max(ref_connections, key=ref_connections.get) if ref_connections else None
            dest_refs = [r for r in ref_connections if r != source_ref and ref_connections[r] >= 2]

            buses.append({
                "prefix": prefix,
                "width": len(members),
                "nets": [m[1] for m in members],
                "indices": [m[0] for m in members],
                "source": source_ref,
                "destinations": dest_refs[:10],
                "all_components": sorted(connected_refs),
            })

        buses.sort(key=lambda b: -b["width"])

        return {
            "success": True,
            "bus_count": len(buses),
            "buses": buses[:20],
        }

    def reorder_bus_components(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Reorder components along a bus to minimize crossings."""
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        try:
            import pcbnew
        except ImportError:
            return {"success": False, "error": "pcbnew not available"}

        bus_prefix = params.get("bus_prefix")
        source_ref = params.get("source_ref")
        target_refs = params.get("target_refs", [])
        axis = params.get("axis", "auto")
        dry_run = params.get("dry_run", False)

        if not bus_prefix:
            return {"success": False, "error": "bus_prefix required"}

        detection = self.detect_bus_groups({"min_bus_width": 2})
        bus = None
        for b in detection.get("buses", []):
            if b["prefix"] == bus_prefix:
                bus = b
                break
        if not bus:
            return {"success": False, "error": f"Bus '{bus_prefix}' not found"}

        if not source_ref:
            source_ref = bus.get("source")
        if not target_refs:
            target_refs = bus.get("destinations", [])
        if not target_refs:
            return {"success": False, "error": "No target components to reorder"}

        source_fp = None
        for fp in self.board.GetFootprints():
            if fp.GetReference() == source_ref:
                source_fp = fp
                break
        if not source_fp:
            return {"success": False, "error": f"Source '{source_ref}' not found"}

        source_pin_order = []
        for net_name in bus["nets"]:
            for pad in source_fp.Pads():
                if pad.GetNet() and pad.GetNet().GetNetname() == net_name:
                    pos = pad.GetPosition()
                    source_pin_order.append({
                        "net": net_name,
                        "x": pos.x / 1e6,
                        "y": pos.y / 1e6,
                    })
                    break

        if len(source_pin_order) < 2:
            return {"success": False, "error": "Source has fewer than 2 bus pins"}

        xs = [p["x"] for p in source_pin_order]
        ys = [p["y"] for p in source_pin_order]
        x_span = max(xs) - min(xs)
        y_span = max(ys) - min(ys)

        if axis == "auto":
            axis = "x" if x_span >= y_span else "y"

        source_pin_order.sort(key=lambda p: p[axis])

        moves = []
        for tgt_ref in target_refs:
            tgt_fp = None
            for fp in self.board.GetFootprints():
                if fp.GetReference() == tgt_ref:
                    tgt_fp = fp
                    break
            if not tgt_fp:
                continue

            tgt_pins = []
            for net_name in bus["nets"]:
                for pad in tgt_fp.Pads():
                    if pad.GetNet() and pad.GetNet().GetNetname() == net_name:
                        pos = pad.GetPosition()
                        tgt_pins.append({
                            "net": net_name,
                            "x": pos.x / 1e6,
                            "y": pos.y / 1e6,
                        })
                        break

            if len(tgt_pins) < 2:
                continue

            tgt_pins.sort(key=lambda p: p[axis])

            crossings_before = self._count_crossings(source_pin_order, tgt_pins, axis)

            tgt_pins_reordered = sorted(tgt_pins, key=lambda p: [
                sp[axis] for sp in source_pin_order if sp["net"] == p["net"]
            ] or [p[axis]])

            crossings_after = self._count_crossings(source_pin_order, tgt_pins_reordered, axis)

            if crossings_after < crossings_before:
                moves.append({
                    "reference": tgt_ref,
                    "crossings_before": crossings_before,
                    "crossings_after": crossings_after,
                    "reduction": crossings_before - crossings_after,
                    "note": f"Reorder {tgt_ref} pins along {axis}-axis to match {source_ref}",
                })

        return {
            "success": True,
            "bus": bus_prefix,
            "source": source_ref,
            "axis": axis,
            "bus_width": bus["width"],
            "reorder_suggestions": moves,
            "note": "Pin reordering requires schematic changes. Component physical reordering can reduce crossings.",
        }

    def _count_crossings(self, pins_a, pins_b, axis):
        """Count net crossings between two ordered pin lists."""
        crossings = 0
        matched = []
        for pa in pins_a:
            for pb in pins_b:
                if pa["net"] == pb["net"]:
                    matched.append((pa[axis], pb[axis]))
                    break

        for i in range(len(matched)):
            for j in range(i + 1, len(matched)):
                if (matched[i][0] - matched[j][0]) * (matched[i][1] - matched[j][1]) < 0:
                    crossings += 1
        return crossings

    def analyze_crossing_count(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Count net crossings for all detected buses."""
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        detection = self.detect_bus_groups(params)
        if not detection.get("success"):
            return detection

        results = []
        for bus in detection.get("buses", []):
            result = self.reorder_bus_components({
                "bus_prefix": bus["prefix"],
                "dry_run": True,
            })
            total_crossings = sum(m.get("crossings_before", 0) for m in result.get("reorder_suggestions", []))
            reducible = sum(m.get("reduction", 0) for m in result.get("reorder_suggestions", []))
            results.append({
                "bus": bus["prefix"],
                "width": bus["width"],
                "current_crossings": total_crossings,
                "reducible_crossings": reducible,
            })

        results.sort(key=lambda r: -r["reducible_crossings"])

        return {
            "success": True,
            "buses_analyzed": len(results),
            "results": results[:20],
        }
