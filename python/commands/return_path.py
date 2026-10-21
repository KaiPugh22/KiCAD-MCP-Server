"""
Return Path Analyzer for KiCAD MCP Server.

For each signal trace, checks whether its reference plane (ground/power)
is continuous underneath. Flags spots where a signal crosses a plane
split or layer boundary without a nearby stitching via.
"""

import math
import logging
from typing import Dict, Any, List, Tuple, Set, Optional

logger = logging.getLogger("kicad_interface")


class ReturnPathCommands:
    def __init__(self, board=None):
        self.board = board

    def analyze_return_paths(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze return path continuity for signal traces."""
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        try:
            import pcbnew
        except ImportError:
            return {"success": False, "error": "pcbnew not available"}

        target_nets = params.get("nets")
        via_search_radius_mm = params.get("via_search_radius_mm", 2.0)
        ref_plane_nets = params.get("ref_plane_nets", ["GND"])

        via_search_radius = int(via_search_radius_mm * 1e6)

        vias = []
        for track in self.board.GetTracks():
            if hasattr(track, 'GetViaType') or track.GetClass() == "PCB_VIA":
                pos = track.GetPosition()
                net = track.GetNet()
                vias.append({
                    "x": pos.x,
                    "y": pos.y,
                    "net": net.GetNetname() if net else "",
                })

        zone_layers = {}
        for zone in self.board.Zones():
            net = zone.GetNet()
            if not net:
                continue
            net_name = net.GetNetname()
            if net_name not in ref_plane_nets:
                continue
            layer_id = zone.GetFirstLayer() if hasattr(zone, 'GetFirstLayer') else zone.GetLayer()
            layer_name = self.board.GetLayerName(layer_id)
            if layer_name not in zone_layers:
                zone_layers[layer_name] = []
            bb = zone.GetBoundingBox()
            zone_layers[layer_name].append({
                "net": net_name,
                "x1": bb.GetX(),
                "y1": bb.GetY(),
                "x2": bb.GetX() + bb.GetWidth(),
                "y2": bb.GetY() + bb.GetHeight(),
            })

        all_nets = set()
        if target_nets:
            all_nets = set(target_nets)
        else:
            for track in self.board.GetTracks():
                net = track.GetNet()
                if net:
                    name = net.GetNetname()
                    if name and name not in ref_plane_nets:
                        upper = name.upper()
                        if not any(kw in upper for kw in ["VCC", "VDD", "GND", "VSS", "VBAT", "PGND", "AGND"]):
                            all_nets.add(name)

        issues = []
        for net_name in sorted(all_nets):
            net_tracks = []
            for track in self.board.GetTracks():
                if hasattr(track, 'GetStart') and track.GetNet():
                    if track.GetNet().GetNetname() == net_name:
                        layer_id = track.GetLayer()
                        layer_name = self.board.GetLayerName(layer_id)
                        start = track.GetStart()
                        end = track.GetEnd()
                        net_tracks.append({
                            "layer": layer_name,
                            "sx": start.x, "sy": start.y,
                            "ex": end.x, "ey": end.y,
                        })

            if len(net_tracks) < 1:
                continue

            layers_used = set(t["layer"] for t in net_tracks)
            if len(layers_used) > 1:
                layer_transitions = []
                for i, t in enumerate(net_tracks):
                    for j in range(i + 1, len(net_tracks)):
                        if net_tracks[j]["layer"] != t["layer"]:
                            mid_x = (t["ex"] + net_tracks[j]["sx"]) // 2
                            mid_y = (t["ey"] + net_tracks[j]["sy"]) // 2
                            layer_transitions.append((t["layer"], net_tracks[j]["layer"], mid_x, mid_y))

                for from_layer, to_layer, tx, ty in layer_transitions:
                    nearby_via = False
                    for via in vias:
                        if via["net"] in ref_plane_nets:
                            dist = math.sqrt((via["x"] - tx) ** 2 + (via["y"] - ty) ** 2)
                            if dist <= via_search_radius:
                                nearby_via = True
                                break

                    if not nearby_via:
                        issues.append({
                            "net": net_name,
                            "type": "layer_transition_no_via",
                            "from_layer": from_layer,
                            "to_layer": to_layer,
                            "location_mm": {"x": round(tx / 1e6, 2), "y": round(ty / 1e6, 2)},
                            "severity": "high",
                            "fix": f"Add {ref_plane_nets[0]} stitching via within {via_search_radius_mm}mm",
                        })

            for t in net_tracks:
                layer = t["layer"]
                if "Cu" not in layer:
                    continue

                adjacent_layers = self._get_adjacent_copper_layers(layer)
                has_ref_plane = False
                mid_x = (t["sx"] + t["ex"]) // 2
                mid_y = (t["sy"] + t["ey"]) // 2

                for adj_layer in adjacent_layers:
                    if adj_layer in zone_layers:
                        for zone_bb in zone_layers[adj_layer]:
                            if (zone_bb["x1"] <= mid_x <= zone_bb["x2"] and
                                    zone_bb["y1"] <= mid_y <= zone_bb["y2"]):
                                has_ref_plane = True
                                break
                    if has_ref_plane:
                        break

                if not has_ref_plane and adjacent_layers:
                    issues.append({
                        "net": net_name,
                        "type": "no_reference_plane",
                        "layer": layer,
                        "location_mm": {"x": round(mid_x / 1e6, 2), "y": round(mid_y / 1e6, 2)},
                        "severity": "medium",
                        "fix": f"Add {ref_plane_nets[0]} pour on {', '.join(adjacent_layers)} under this trace",
                    })

        issues.sort(key=lambda i: 0 if i["severity"] == "high" else 1)

        return {
            "success": True,
            "nets_analyzed": len(all_nets),
            "issue_count": len(issues),
            "high_severity": sum(1 for i in issues if i["severity"] == "high"),
            "medium_severity": sum(1 for i in issues if i["severity"] == "medium"),
            "issues": issues[:50],
            "ref_plane_nets": ref_plane_nets,
        }

    def check_signal_over_split(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Check if specific signals cross over plane splits."""
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        try:
            import pcbnew
        except ImportError:
            return {"success": False, "error": "pcbnew not available"}

        net_name = params.get("net")
        if not net_name:
            return {"success": False, "error": "net name required"}

        result = self.analyze_return_paths({"nets": [net_name]})
        return result

    def _get_adjacent_copper_layers(self, layer_name: str) -> List[str]:
        """Get copper layers adjacent in the stackup to the given layer."""
        standard_order = ["F.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu",
                          "In5.Cu", "In6.Cu", "B.Cu"]

        if layer_name not in standard_order:
            return []

        idx = standard_order.index(layer_name)
        adjacent = []

        enabled_layers = []
        if self.board:
            try:
                import pcbnew
                for l in standard_order:
                    layer_id = self.board.GetLayerID(l)
                    if layer_id >= 0 and self.board.IsLayerEnabled(layer_id):
                        enabled_layers.append(l)
            except Exception:
                enabled_layers = standard_order

        if layer_name not in enabled_layers:
            return []

        eidx = enabled_layers.index(layer_name)
        if eidx > 0:
            adjacent.append(enabled_layers[eidx - 1])
        if eidx < len(enabled_layers) - 1:
            adjacent.append(enabled_layers[eidx + 1])

        return adjacent

    def suggest_stitching_locations(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Suggest where to add stitching vias based on return path analysis."""
        result = self.analyze_return_paths(params)
        if not result.get("success"):
            return result

        suggestions = []
        for issue in result.get("issues", []):
            if issue["type"] == "layer_transition_no_via":
                suggestions.append({
                    "location_mm": issue["location_mm"],
                    "net": params.get("ref_plane_nets", ["GND"])[0],
                    "reason": f"Return path via for {issue['net']} layer transition "
                              f"{issue['from_layer']} -> {issue['to_layer']}",
                    "priority": "high",
                })

        return {
            "success": True,
            "via_suggestions": suggestions[:30],
            "total_needed": len(suggestions),
        }
