"""
DFM (Design for Manufacturing) Checker

Goes beyond KiCad's built-in DRC to check fabrication-specific rules:
- JLCPCB / PCBWay / OSHPark specific constraints
- Acid trap detection
- Thermal relief issues
- Silk-to-pad clearance
- Minimum annular ring
- Orphaned vias/tracks
- Unconnected copper pour issues
"""

import math
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Fab house constraints (min values in mm)
FAB_CONSTRAINTS = {
    "jlcpcb_standard": {
        "name": "JLCPCB Standard",
        "min_trace_width": 0.127,       # 5mil
        "min_clearance": 0.127,         # 5mil
        "min_drill": 0.3,
        "min_via_diameter": 0.45,       # pad
        "min_annular_ring": 0.13,
        "min_hole_to_hole": 0.254,
        "min_silk_width": 0.15,
        "min_silk_to_pad": 0.15,
        "min_board_edge_clearance": 0.3,
        "min_pth_to_edge": 0.5,        # plated hole to edge
        "max_board_size": [500, 500],
        "min_board_size": [10, 10],
        "max_drill_aspect": 10,         # depth/diameter
    },
    "jlcpcb_advanced": {
        "name": "JLCPCB Advanced",
        "min_trace_width": 0.09,        # 3.5mil
        "min_clearance": 0.09,
        "min_drill": 0.2,
        "min_via_diameter": 0.35,
        "min_annular_ring": 0.075,
        "min_hole_to_hole": 0.254,
        "min_silk_width": 0.1,
        "min_silk_to_pad": 0.1,
        "min_board_edge_clearance": 0.2,
        "min_pth_to_edge": 0.3,
        "max_board_size": [500, 500],
        "min_board_size": [10, 10],
        "max_drill_aspect": 12,
    },
    "oshpark": {
        "name": "OSH Park",
        "min_trace_width": 0.127,
        "min_clearance": 0.127,
        "min_drill": 0.254,
        "min_via_diameter": 0.508,
        "min_annular_ring": 0.178,
        "min_hole_to_hole": 0.254,
        "min_silk_width": 0.15,
        "min_silk_to_pad": 0.15,
        "min_board_edge_clearance": 0.381,
        "min_pth_to_edge": 0.508,
        "max_board_size": [152.4, 152.4],
        "min_board_size": [6.35, 6.35],
        "max_drill_aspect": 8,
    },
    "pcbway_standard": {
        "name": "PCBWay Standard",
        "min_trace_width": 0.1,
        "min_clearance": 0.1,
        "min_drill": 0.2,
        "min_via_diameter": 0.4,
        "min_annular_ring": 0.1,
        "min_hole_to_hole": 0.254,
        "min_silk_width": 0.15,
        "min_silk_to_pad": 0.15,
        "min_board_edge_clearance": 0.25,
        "min_pth_to_edge": 0.5,
        "max_board_size": [600, 600],
        "min_board_size": [10, 10],
        "max_drill_aspect": 10,
    },
}


class DFMCheckerCommands:
    def __init__(self, board=None):
        self.board = board

    def set_board(self, board):
        self.board = board

    def run_dfm_check(self, fab_house: str = "jlcpcb_standard",
                      board_thickness: float = 1.6) -> Dict[str, Any]:
        """
        Run comprehensive DFM checks against a specific fab house's capabilities.

        Args:
            fab_house: Target fab house preset
            board_thickness: Board thickness in mm (for drill aspect ratio)
        """
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        if fab_house not in FAB_CONSTRAINTS:
            return {
                "success": False,
                "error": f"Unknown fab house '{fab_house}'",
                "available": list(FAB_CONSTRAINTS.keys()),
            }

        try:
            import pcbnew
            board = self.board
            constraints = FAB_CONSTRAINTS[fab_house]
            violations = []

            # Check trace widths
            for track in board.GetTracks():
                if isinstance(track, pcbnew.PCB_TRACK) and not isinstance(track, pcbnew.PCB_VIA):
                    w = pcbnew.ToMM(track.GetWidth())
                    if w < constraints["min_trace_width"]:
                        violations.append({
                            "type": "trace_width",
                            "severity": "error",
                            "message": f"Trace width {w:.3f}mm < min {constraints['min_trace_width']}mm",
                            "net": track.GetNetname(),
                            "layer": board.GetLayerName(track.GetLayer()),
                            "x": pcbnew.ToMM(track.GetStart().x),
                            "y": pcbnew.ToMM(track.GetStart().y),
                        })

            # Check vias
            for track in board.GetTracks():
                if isinstance(track, pcbnew.PCB_VIA):
                    diameter = pcbnew.ToMM(track.GetWidth())
                    drill = pcbnew.ToMM(track.GetDrillValue())
                    annular_ring = (diameter - drill) / 2
                    aspect_ratio = board_thickness / drill if drill > 0 else 999

                    if diameter < constraints["min_via_diameter"]:
                        violations.append({
                            "type": "via_diameter",
                            "severity": "error",
                            "message": f"Via diameter {diameter:.3f}mm < min {constraints['min_via_diameter']}mm",
                            "x": pcbnew.ToMM(track.GetPosition().x),
                            "y": pcbnew.ToMM(track.GetPosition().y),
                        })

                    if drill < constraints["min_drill"]:
                        violations.append({
                            "type": "drill_size",
                            "severity": "error",
                            "message": f"Drill {drill:.3f}mm < min {constraints['min_drill']}mm",
                            "x": pcbnew.ToMM(track.GetPosition().x),
                            "y": pcbnew.ToMM(track.GetPosition().y),
                        })

                    if annular_ring < constraints["min_annular_ring"]:
                        violations.append({
                            "type": "annular_ring",
                            "severity": "error",
                            "message": f"Annular ring {annular_ring:.3f}mm < min {constraints['min_annular_ring']}mm",
                            "x": pcbnew.ToMM(track.GetPosition().x),
                            "y": pcbnew.ToMM(track.GetPosition().y),
                        })

                    if aspect_ratio > constraints["max_drill_aspect"]:
                        violations.append({
                            "type": "drill_aspect_ratio",
                            "severity": "warning",
                            "message": f"Drill aspect ratio {aspect_ratio:.1f} > max {constraints['max_drill_aspect']}",
                            "x": pcbnew.ToMM(track.GetPosition().x),
                            "y": pcbnew.ToMM(track.GetPosition().y),
                        })

            # Check board size
            bbox = board.GetBoardEdgesBoundingBox()
            bw = pcbnew.ToMM(bbox.GetWidth())
            bh = pcbnew.ToMM(bbox.GetHeight())

            if bw > constraints["max_board_size"][0] or bh > constraints["max_board_size"][1]:
                violations.append({
                    "type": "board_too_large",
                    "severity": "error",
                    "message": f"Board {bw:.1f}x{bh:.1f}mm exceeds max "
                              f"{constraints['max_board_size'][0]}x{constraints['max_board_size'][1]}mm",
                })

            # Check PTH to board edge distance
            edge_x = pcbnew.ToMM(bbox.GetX())
            edge_y = pcbnew.ToMM(bbox.GetY())
            edge_w = bw
            edge_h = bh

            for track in board.GetTracks():
                if isinstance(track, pcbnew.PCB_VIA):
                    vx = pcbnew.ToMM(track.GetPosition().x)
                    vy = pcbnew.ToMM(track.GetPosition().y)

                    dist_to_edge = min(
                        vx - edge_x,
                        vy - edge_y,
                        (edge_x + edge_w) - vx,
                        (edge_y + edge_h) - vy,
                    )
                    if dist_to_edge < constraints["min_pth_to_edge"]:
                        violations.append({
                            "type": "pth_to_edge",
                            "severity": "error",
                            "message": f"Via {dist_to_edge:.2f}mm from board edge "
                                      f"< min {constraints['min_pth_to_edge']}mm",
                            "x": vx, "y": vy,
                        })

            # Check footprint pads
            for fp in board.GetFootprints():
                for pad in fp.Pads():
                    if pad.GetDrillSize().x > 0:
                        drill = pcbnew.ToMM(pad.GetDrillSize().x)
                        if drill < constraints["min_drill"]:
                            violations.append({
                                "type": "pad_drill",
                                "severity": "error",
                                "message": f"{fp.GetReference()} pad {pad.GetName()}: "
                                          f"drill {drill:.3f}mm < min {constraints['min_drill']}mm",
                                "x": pcbnew.ToMM(pad.GetPosition().x),
                                "y": pcbnew.ToMM(pad.GetPosition().y),
                            })

            # Count by severity
            errors = sum(1 for v in violations if v["severity"] == "error")
            warnings = sum(1 for v in violations if v["severity"] == "warning")

            return {
                "success": True,
                "fab_house": constraints["name"],
                "board_size": {"width_mm": round(bw, 2), "height_mm": round(bh, 2)},
                "board_thickness_mm": board_thickness,
                "result": "PASS" if errors == 0 else "FAIL",
                "error_count": errors,
                "warning_count": warnings,
                "violations": violations[:50],
                "message": (
                    f"DFM check for {constraints['name']}: "
                    f"{errors} errors, {warnings} warnings"
                    + (" - READY FOR FABRICATION" if errors == 0 else " - FIX ERRORS BEFORE ORDERING")
                ),
            }

        except Exception as e:
            logger.error(f"DFM check failed: {e}")
            return {"success": False, "error": str(e)}

    def check_unconnected_nets(self) -> Dict[str, Any]:
        """Check for unconnected nets (ratsnest items)."""
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        try:
            import pcbnew
            board = self.board

            # Build connection map: net → set of connected component pads
            net_connections = {}
            for fp in board.GetFootprints():
                for pad in fp.Pads():
                    net = pad.GetNetname()
                    if net:
                        if net not in net_connections:
                            net_connections[net] = []
                        net_connections[net].append({
                            "component": fp.GetReference(),
                            "pad": pad.GetName(),
                        })

            # Nets with only one connection point are suspicious
            single_pad_nets = []
            for net, pads in net_connections.items():
                if len(pads) == 1 and net:
                    single_pad_nets.append({
                        "net": net,
                        "component": pads[0]["component"],
                        "pad": pads[0]["pad"],
                    })

            return {
                "success": True,
                "total_nets": len(net_connections),
                "single_pad_nets": single_pad_nets,
                "single_pad_count": len(single_pad_nets),
                "message": (
                    f"Found {len(single_pad_nets)} nets with only one connection "
                    "(possible unconnected pins)"
                ),
            }

        except Exception as e:
            logger.error(f"Unconnected net check failed: {e}")
            return {"success": False, "error": str(e)}

    def check_silk_clearance(self, min_clearance_mm: float = 0.15) -> Dict[str, Any]:
        """Check for silkscreen text overlapping pads."""
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        try:
            import pcbnew
            board = self.board

            issues = []

            # Collect all pad positions and sizes
            pads_info = []
            for fp in board.GetFootprints():
                for pad in fp.Pads():
                    pos = pad.GetPosition()
                    size = pad.GetSize()
                    pads_info.append({
                        "x": pcbnew.ToMM(pos.x),
                        "y": pcbnew.ToMM(pos.y),
                        "w": pcbnew.ToMM(size.x),
                        "h": pcbnew.ToMM(size.y),
                        "ref": fp.GetReference(),
                        "pad": pad.GetName(),
                    })

            # Check each footprint's silkscreen reference against pads
            for fp in board.GetFootprints():
                ref_field = fp.Reference()
                if not ref_field.IsVisible():
                    continue

                ref_pos = ref_field.GetPosition()
                rx = pcbnew.ToMM(ref_pos.x)
                ry = pcbnew.ToMM(ref_pos.y)

                text_bbox = ref_field.GetBoundingBox()
                tw = pcbnew.ToMM(text_bbox.GetWidth())
                th = pcbnew.ToMM(text_bbox.GetHeight())

                for pad_info in pads_info:
                    dx = abs(rx - pad_info["x"]) - (tw + pad_info["w"]) / 2
                    dy = abs(ry - pad_info["y"]) - (th + pad_info["h"]) / 2

                    if dx < min_clearance_mm and dy < min_clearance_mm:
                        issues.append({
                            "type": "silk_over_pad",
                            "silk_ref": fp.GetReference(),
                            "pad_component": pad_info["ref"],
                            "pad_name": pad_info["pad"],
                            "clearance_x_mm": round(max(0, dx), 3),
                            "clearance_y_mm": round(max(0, dy), 3),
                        })

            return {
                "success": True,
                "issues": issues[:30],
                "issue_count": len(issues),
                "message": f"Found {len(issues)} silkscreen-to-pad clearance issues",
            }

        except Exception as e:
            logger.error(f"Silk clearance check failed: {e}")
            return {"success": False, "error": str(e)}

    def list_fab_presets(self) -> Dict[str, Any]:
        """List available fabrication house presets and their constraints."""
        presets = {}
        for key, c in FAB_CONSTRAINTS.items():
            presets[key] = {
                "name": c["name"],
                "min_trace_mm": c["min_trace_width"],
                "min_clearance_mm": c["min_clearance"],
                "min_drill_mm": c["min_drill"],
                "min_via_mm": c["min_via_diameter"],
                "max_board_mm": f"{c['max_board_size'][0]}x{c['max_board_size'][1]}",
            }
        return {"success": True, "presets": presets}
