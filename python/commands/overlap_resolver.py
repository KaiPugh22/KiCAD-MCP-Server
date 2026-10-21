"""
Overlap Resolver for KiCAD MCP Server.

Detects courtyard/placement overlaps and computes minimum legal moves
to resolve them using force-directed repulsion.
"""

import math
import logging
from typing import Dict, Any, List, Tuple, Optional

logger = logging.getLogger("kicad_interface")


class OverlapResolverCommands:
    def __init__(self, board=None):
        self.board = board

    def detect_overlaps(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Detect all courtyard and placement overlaps on the board."""
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        try:
            import pcbnew
        except ImportError:
            return {"success": False, "error": "pcbnew not available"}

        margin_mm = params.get("margin_mm", 0.0)
        margin = int(margin_mm * 1e6)

        footprints = list(self.board.GetFootprints())
        overlaps = []

        for i in range(len(footprints)):
            fp1 = footprints[i]
            ref1 = fp1.GetReference()
            bb1 = fp1.GetBoundingBox()
            r1 = (bb1.GetX() - margin, bb1.GetY() - margin,
                   bb1.GetX() + bb1.GetWidth() + margin,
                   bb1.GetY() + bb1.GetHeight() + margin)

            for j in range(i + 1, len(footprints)):
                fp2 = footprints[j]
                ref2 = fp2.GetReference()
                bb2 = fp2.GetBoundingBox()
                r2 = (bb2.GetX() - margin, bb2.GetY() - margin,
                       bb2.GetX() + bb2.GetWidth() + margin,
                       bb2.GetY() + bb2.GetHeight() + margin)

                ox = max(0, min(r1[2], r2[2]) - max(r1[0], r2[0]))
                oy = max(0, min(r1[3], r2[3]) - max(r1[1], r2[1]))

                if ox > 0 and oy > 0:
                    overlaps.append({
                        "comp_a": ref1,
                        "comp_b": ref2,
                        "overlap_x_mm": round(ox / 1e6, 3),
                        "overlap_y_mm": round(oy / 1e6, 3),
                        "overlap_area_mm2": round((ox / 1e6) * (oy / 1e6), 3),
                    })

        return {
            "success": True,
            "total_overlaps": len(overlaps),
            "overlaps": overlaps[:50],
        }

    def resolve_overlaps(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Compute and apply minimum moves to resolve all overlaps."""
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        try:
            import pcbnew
        except ImportError:
            return {"success": False, "error": "pcbnew not available"}

        margin_mm = params.get("margin_mm", 0.25)
        max_iterations = params.get("max_iterations", 50)
        locked_refs = set(params.get("locked", []))
        dry_run = params.get("dry_run", False)

        margin = int(margin_mm * 1e6)
        footprints = []
        for fp in self.board.GetFootprints():
            ref = fp.GetReference()
            bb = fp.GetBoundingBox()
            pos = fp.GetPosition()
            footprints.append({
                "fp": fp,
                "ref": ref,
                "x": pos.x,
                "y": pos.y,
                "w": bb.GetWidth(),
                "h": bb.GetHeight(),
                "locked": ref in locked_refs or fp.IsLocked(),
                "dx": 0,
                "dy": 0,
            })

        moves = []
        for iteration in range(max_iterations):
            has_overlap = False
            for i in range(len(footprints)):
                if footprints[i]["locked"]:
                    continue
                fi = footprints[i]
                ax1 = fi["x"] - fi["w"] // 2 - margin
                ay1 = fi["y"] - fi["h"] // 2 - margin
                ax2 = fi["x"] + fi["w"] // 2 + margin
                ay2 = fi["y"] + fi["h"] // 2 + margin

                for j in range(len(footprints)):
                    if i == j:
                        continue
                    fj = footprints[j]
                    bx1 = fj["x"] - fj["w"] // 2
                    by1 = fj["y"] - fj["h"] // 2
                    bx2 = fj["x"] + fj["w"] // 2
                    by2 = fj["y"] + fj["h"] // 2

                    ox = max(0, min(ax2, bx2) - max(ax1, bx1))
                    oy = max(0, min(ay2, by2) - max(ay1, by1))

                    if ox > 0 and oy > 0:
                        has_overlap = True
                        cx_i = fi["x"]
                        cy_i = fi["y"]
                        cx_j = fj["x"]
                        cy_j = fj["y"]

                        dx = cx_i - cx_j
                        dy = cy_i - cy_j

                        if abs(dx) < 100 and abs(dy) < 100:
                            dx = 1e6
                            dy = 0

                        if ox < oy:
                            push = ox + int(0.1e6)
                            if dx >= 0:
                                fi["x"] += push // 2
                                if not fj["locked"]:
                                    fj["x"] -= push // 2
                            else:
                                fi["x"] -= push // 2
                                if not fj["locked"]:
                                    fj["x"] += push // 2
                        else:
                            push = oy + int(0.1e6)
                            if dy >= 0:
                                fi["y"] += push // 2
                                if not fj["locked"]:
                                    fj["y"] -= push // 2
                            else:
                                fi["y"] -= push // 2
                                if not fj["locked"]:
                                    fj["y"] += push // 2

            if not has_overlap:
                break

        for fi in footprints:
            orig_pos = fi["fp"].GetPosition()
            dx = fi["x"] - orig_pos.x
            dy = fi["y"] - orig_pos.y
            if abs(dx) > 1000 or abs(dy) > 1000:
                moves.append({
                    "reference": fi["ref"],
                    "dx_mm": round(dx / 1e6, 3),
                    "dy_mm": round(dy / 1e6, 3),
                    "distance_mm": round(math.sqrt(dx**2 + dy**2) / 1e6, 3),
                })
                if not dry_run:
                    fi["fp"].SetPosition(pcbnew.VECTOR2I(fi["x"], fi["y"]))

        if not dry_run and moves:
            if hasattr(pcbnew, 'Refresh'):
                pcbnew.Refresh()

        remaining = self.detect_overlaps({"margin_mm": margin_mm})
        remaining_count = remaining.get("total_overlaps", 0)

        return {
            "success": True,
            "dry_run": dry_run,
            "components_moved": len(moves),
            "moves": moves[:30],
            "iterations_used": iteration + 1 if 'iteration' in dir() else 0,
            "remaining_overlaps": remaining_count,
        }

    def suggest_overlap_fixes(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Suggest fixes without applying them (dry run with explanations)."""
        params["dry_run"] = True
        result = self.resolve_overlaps(params)
        if result.get("success"):
            result["note"] = "These moves have NOT been applied. Use resolve_overlaps to apply."
        return result
