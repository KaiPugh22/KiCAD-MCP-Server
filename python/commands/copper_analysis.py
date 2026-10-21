"""
Copper Balance & Design Diff for KiCAD MCP Server.

- Copper balance analysis: checks copper distribution across layers to predict warpage
- Design diff: compares two board revisions to show what changed
- Interactive BOM generation: creates HTML BOM with component highlighting
"""

import math
import json
import os
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger("kicad_interface")


class CopperAnalysisCommands:
    def __init__(self, board=None):
        self.board = board

    def analyze_copper_balance(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze copper distribution across layers for warpage prediction."""
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        try:
            import pcbnew
        except ImportError:
            return {"success": False, "error": "pcbnew not available"}

        bbox = self.board.GetBoardEdgesBoundingBox()
        board_area = (bbox.GetWidth() / 1e6) * (bbox.GetHeight() / 1e6)

        if board_area <= 0:
            return {"success": False, "error": "Could not determine board area"}

        layer_copper = {}
        copper_layers = []

        for layer_id in range(pcbnew.PCB_LAYER_ID_COUNT):
            if self.board.IsLayerEnabled(layer_id):
                name = self.board.GetLayerName(layer_id)
                if name and ("Cu" in name):
                    copper_layers.append((layer_id, name))
                    layer_copper[name] = {"tracks_mm2": 0, "pads_mm2": 0, "zones_mm2": 0}

        for track in self.board.GetTracks():
            layer_id = track.GetLayer()
            layer_name = self.board.GetLayerName(layer_id)
            if layer_name in layer_copper:
                if hasattr(track, 'GetLength'):
                    length_mm = track.GetLength() / 1e6
                    width_mm = track.GetWidth() / 1e6
                    layer_copper[layer_name]["tracks_mm2"] += length_mm * width_mm
                elif hasattr(track, 'GetWidth'):
                    via_size = track.GetWidth() / 1e6
                    layer_copper[layer_name]["pads_mm2"] += math.pi * (via_size / 2) ** 2

        for fp in self.board.GetFootprints():
            for pad in fp.Pads():
                pad_layers = pad.GetLayerSet()
                w = pad.GetSizeX() / 1e6
                h = pad.GetSizeY() / 1e6
                area = w * h * 0.85
                for layer_id, name in copper_layers:
                    if pad_layers.Contains(layer_id):
                        layer_copper[name]["pads_mm2"] += area

        for zone in self.board.Zones():
            layer_id = zone.GetFirstLayer() if hasattr(zone, 'GetFirstLayer') else zone.GetLayer()
            name = self.board.GetLayerName(layer_id)
            if name in layer_copper:
                if hasattr(zone, 'GetFilledArea'):
                    layer_copper[name]["zones_mm2"] += zone.GetFilledArea() / 1e12
                else:
                    zbox = zone.GetBoundingBox()
                    layer_copper[name]["zones_mm2"] += (zbox.GetWidth() / 1e6) * (zbox.GetHeight() / 1e6) * 0.7

        layer_results = []
        for name, copper in layer_copper.items():
            total = copper["tracks_mm2"] + copper["pads_mm2"] + copper["zones_mm2"]
            fill_pct = (total / board_area * 100) if board_area > 0 else 0
            layer_results.append({
                "layer": name,
                "total_copper_mm2": round(total, 2),
                "fill_percentage": round(fill_pct, 1),
                "tracks_mm2": round(copper["tracks_mm2"], 2),
                "pads_mm2": round(copper["pads_mm2"], 2),
                "zones_mm2": round(copper["zones_mm2"], 2),
            })

        layer_results.sort(key=lambda l: l["layer"])

        if len(layer_results) >= 2:
            fills = [l["fill_percentage"] for l in layer_results]
            max_fill = max(fills)
            min_fill = min(fills)
            imbalance = max_fill - min_fill

            if len(layer_results) >= 4:
                top_half = sum(fills[:len(fills)//2]) / max(len(fills)//2, 1)
                bot_half = sum(fills[len(fills)//2:]) / max(len(fills) - len(fills)//2, 1)
                stackup_imbalance = abs(top_half - bot_half)
            else:
                stackup_imbalance = imbalance

            if stackup_imbalance > 30:
                risk = "high"
                recommendation = "Significant copper imbalance. Add ground pours to low-copper layers."
            elif stackup_imbalance > 15:
                risk = "medium"
                recommendation = "Moderate imbalance. Consider adding copper fills to balance."
            else:
                risk = "low"
                recommendation = "Good copper balance across layers."
        else:
            imbalance = 0
            stackup_imbalance = 0
            risk = "n/a"
            recommendation = "Only one copper layer."

        return {
            "success": True,
            "board_area_mm2": round(board_area, 1),
            "layer_count": len(layer_results),
            "layers": layer_results,
            "imbalance_pct": round(imbalance, 1),
            "stackup_imbalance_pct": round(stackup_imbalance, 1),
            "warpage_risk": risk,
            "recommendation": recommendation,
        }

    def design_diff(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Compare two board revisions and report differences."""
        board_path_a = params.get("board_a")
        board_path_b = params.get("board_b")

        if not board_path_a:
            if self.board:
                board_path_a = self.board.GetFileName()
            if not board_path_a:
                return {"success": False, "error": "board_a path required"}

        if not board_path_b:
            return {"success": False, "error": "board_b path required (the other revision)"}

        if not os.path.isfile(board_path_a):
            return {"success": False, "error": f"File not found: {board_path_a}"}
        if not os.path.isfile(board_path_b):
            return {"success": False, "error": f"File not found: {board_path_b}"}

        try:
            import pcbnew
            board_a = pcbnew.LoadBoard(board_path_a)
            board_b = pcbnew.LoadBoard(board_path_b)
        except Exception as e:
            return {"success": False, "error": f"Failed to load boards: {e}"}

        def get_components(board):
            comps = {}
            for fp in board.GetFootprints():
                ref = fp.GetReference()
                pos = fp.GetPosition()
                comps[ref] = {
                    "footprint": fp.GetFPID().GetUniStringLibItemName(),
                    "x": pos.x / 1e6,
                    "y": pos.y / 1e6,
                    "rotation": fp.GetOrientationDegrees(),
                    "side": "front" if fp.IsFlipped() is False else "back",
                    "value": fp.GetValue(),
                }
            return comps

        def get_nets(board):
            nets = set()
            for net in board.GetNetsByName().values():
                name = net.GetNetname()
                if name:
                    nets.add(name)
            return nets

        def get_track_count(board):
            return len(list(board.GetTracks()))

        comps_a = get_components(board_a)
        comps_b = get_components(board_b)
        nets_a = get_nets(board_a)
        nets_b = get_nets(board_b)

        refs_a = set(comps_a.keys())
        refs_b = set(comps_b.keys())

        added_comps = sorted(refs_b - refs_a)
        removed_comps = sorted(refs_a - refs_b)
        common_refs = refs_a & refs_b

        moved = []
        rotated = []
        value_changed = []
        footprint_changed = []
        side_changed = []

        for ref in sorted(common_refs):
            a = comps_a[ref]
            b = comps_b[ref]

            dist = math.sqrt((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2)
            if dist > 0.1:
                moved.append({
                    "ref": ref,
                    "from": {"x": round(a["x"], 2), "y": round(a["y"], 2)},
                    "to": {"x": round(b["x"], 2), "y": round(b["y"], 2)},
                    "distance_mm": round(dist, 2),
                })

            if abs(a["rotation"] - b["rotation"]) > 0.5:
                rotated.append({
                    "ref": ref,
                    "from_deg": round(a["rotation"], 1),
                    "to_deg": round(b["rotation"], 1),
                })

            if a["value"] != b["value"]:
                value_changed.append({"ref": ref, "from": a["value"], "to": b["value"]})

            if a["footprint"] != b["footprint"]:
                footprint_changed.append({"ref": ref, "from": a["footprint"], "to": b["footprint"]})

            if a["side"] != b["side"]:
                side_changed.append({"ref": ref, "from": a["side"], "to": b["side"]})

        added_nets = sorted(nets_b - nets_a)
        removed_nets = sorted(nets_a - nets_b)

        tracks_a = get_track_count(board_a)
        tracks_b = get_track_count(board_b)

        return {
            "success": True,
            "board_a": board_path_a,
            "board_b": board_path_b,
            "summary": {
                "components_added": len(added_comps),
                "components_removed": len(removed_comps),
                "components_moved": len(moved),
                "components_rotated": len(rotated),
                "values_changed": len(value_changed),
                "footprints_changed": len(footprint_changed),
                "sides_changed": len(side_changed),
                "nets_added": len(added_nets),
                "nets_removed": len(removed_nets),
                "track_count_a": tracks_a,
                "track_count_b": tracks_b,
            },
            "added_components": added_comps[:30],
            "removed_components": removed_comps[:30],
            "moved_components": moved[:30],
            "rotated_components": rotated[:20],
            "value_changes": value_changed[:20],
            "footprint_changes": footprint_changed[:20],
            "side_changes": side_changed[:10],
            "added_nets": added_nets[:20],
            "removed_nets": removed_nets[:20],
        }

    def generate_ibom(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate Interactive BOM HTML file using InteractiveHtmlBom."""
        board_path = params.get("board_path")
        if not board_path and self.board:
            board_path = self.board.GetFileName()
        if not board_path:
            return {"success": False, "error": "No board path available"}

        output_dir = params.get("output_dir")
        if not output_dir:
            output_dir = str(Path(board_path).parent / "bom")
        os.makedirs(output_dir, exist_ok=True)

        try:
            result = subprocess.run(
                ["python3", "-m", "InteractiveHtmlBom.generate_interactive_bom",
                 "--no-browser", "--dest-dir", output_dir,
                 "--include-tracks", "--include-nets",
                 board_path],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0:
                html_files = [f for f in os.listdir(output_dir) if f.endswith(".html")]
                return {
                    "success": True,
                    "method": "InteractiveHtmlBom",
                    "output_dir": output_dir,
                    "html_files": html_files,
                }
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        try:
            result = subprocess.run(
                ["generate_interactive_bom",
                 "--no-browser", "--dest-dir", output_dir,
                 board_path],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0:
                html_files = [f for f in os.listdir(output_dir) if f.endswith(".html")]
                return {
                    "success": True,
                    "method": "generate_interactive_bom",
                    "output_dir": output_dir,
                    "html_files": html_files,
                }
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        return {
            "success": False,
            "error": "InteractiveHtmlBom not found",
            "install_instructions": "pip install InteractiveHtmlBom",
            "note": "You can also install it as a KiCad plugin from the Plugin Manager.",
        }
