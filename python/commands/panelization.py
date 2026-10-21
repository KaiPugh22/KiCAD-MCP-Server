"""
Panelization tools for KiCAD MCP Server.

Generates panel layouts for PCB fabrication, supporting:
- Grid panelization with configurable rows/columns
- V-score and mouse bite (tab) separation
- Fiducial and tooling hole placement
- Panel frame (rails) for assembly
- JLCPCB panel size constraints
"""

import math
import logging
import os
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger("kicad_interface")

JLCPCB_PANEL_CONSTRAINTS = {
    "min_width_mm": 70,
    "min_height_mm": 70,
    "max_width_mm": 400,
    "max_height_mm": 400,
    "preferred_width_mm": 100,
    "preferred_height_mm": 100,
    "rail_width_mm": 5.0,
    "v_score_clearance_mm": 0.4,
    "mouse_bite_diameter_mm": 0.5,
    "mouse_bite_spacing_mm": 0.8,
    "fiducial_diameter_mm": 1.0,
    "fiducial_clearance_mm": 2.0,
    "tooling_hole_diameter_mm": 1.152,
}


class PanelizationCommands:
    def __init__(self, board=None):
        self.board = board

    def _get_board_size(self) -> Optional[Dict[str, float]]:
        """Get current board dimensions in mm."""
        if not self.board:
            return None
        bbox = self.board.GetBoardEdgesBoundingBox()
        return {
            "width_mm": bbox.GetWidth() / 1e6,
            "height_mm": bbox.GetHeight() / 1e6,
        }

    def calculate_panel_layout(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate optimal panel layout for fabrication."""
        board_width = params.get("board_width_mm")
        board_height = params.get("board_height_mm")

        if not board_width or not board_height:
            size = self._get_board_size()
            if size:
                board_width = board_width or size["width_mm"]
                board_height = board_height or size["height_mm"]
            else:
                return {"success": False, "error": "Board dimensions required"}

        separation = params.get("separation_mm", "v_score")
        fab_house = params.get("fab_house", "jlcpcb")
        max_panel_width = params.get("max_panel_width_mm")
        max_panel_height = params.get("max_panel_height_mm")
        add_rails = params.get("add_rails", True)
        rail_width_mm = params.get("rail_width_mm", 5.0)
        target_quantity = params.get("target_quantity")

        constraints = JLCPCB_PANEL_CONSTRAINTS.copy()
        if max_panel_width:
            constraints["max_width_mm"] = max_panel_width
        if max_panel_height:
            constraints["max_height_mm"] = max_panel_height

        if separation == "v_score":
            gap = constraints["v_score_clearance_mm"]
        elif separation == "mouse_bite":
            gap = 2.0
        else:
            gap = float(separation) if isinstance(separation, (int, float)) else 2.0

        usable_w = constraints["max_width_mm"]
        usable_h = constraints["max_height_mm"]
        if add_rails:
            usable_h -= 2 * rail_width_mm

        max_cols = max(1, int((usable_w + gap) / (board_width + gap)))
        max_rows = max(1, int((usable_h + gap) / (board_height + gap)))

        best_layout = None
        best_count = 0

        for cols in range(1, max_cols + 1):
            for rows in range(1, max_rows + 1):
                panel_w = cols * board_width + (cols - 1) * gap
                panel_h = rows * board_height + (rows - 1) * gap
                if add_rails:
                    panel_h += 2 * rail_width_mm

                if panel_w > constraints["max_width_mm"]:
                    continue
                if panel_h > constraints["max_height_mm"]:
                    continue

                count = rows * cols
                if count > best_count:
                    best_count = count
                    best_layout = {
                        "rows": rows,
                        "cols": cols,
                        "boards_per_panel": count,
                        "panel_width_mm": round(panel_w, 2),
                        "panel_height_mm": round(panel_h, 2),
                    }

        also_rotated = None
        max_cols_r = max(1, int((usable_w + gap) / (board_height + gap)))
        max_rows_r = max(1, int((usable_h + gap) / (board_width + gap)))
        best_count_r = 0
        for cols in range(1, max_cols_r + 1):
            for rows in range(1, max_rows_r + 1):
                panel_w = cols * board_height + (cols - 1) * gap
                panel_h = rows * board_width + (rows - 1) * gap
                if add_rails:
                    panel_h += 2 * rail_width_mm
                if panel_w > constraints["max_width_mm"] or panel_h > constraints["max_height_mm"]:
                    continue
                count = rows * cols
                if count > best_count_r:
                    best_count_r = count
                    also_rotated = {
                        "rows": rows,
                        "cols": cols,
                        "boards_per_panel": count,
                        "panel_width_mm": round(panel_w, 2),
                        "panel_height_mm": round(panel_h, 2),
                        "board_rotated": True,
                    }

        if not best_layout:
            return {
                "success": False,
                "error": f"Board ({board_width}x{board_height}mm) too large for panelization",
            }

        result = {
            "success": True,
            "board_size_mm": {"width": board_width, "height": board_height},
            "separation_type": separation,
            "gap_mm": gap,
            "recommended_layout": best_layout,
            "add_rails": add_rails,
            "rail_width_mm": rail_width_mm if add_rails else 0,
        }

        if also_rotated and also_rotated["boards_per_panel"] > best_layout["boards_per_panel"]:
            result["better_rotated_layout"] = also_rotated
            result["note"] = "Rotating boards 90 degrees fits more per panel"

        if target_quantity:
            panels_needed = math.ceil(target_quantity / best_layout["boards_per_panel"])
            result["production_estimate"] = {
                "target_quantity": target_quantity,
                "panels_needed": panels_needed,
                "boards_produced": panels_needed * best_layout["boards_per_panel"],
                "waste_boards": panels_needed * best_layout["boards_per_panel"] - target_quantity,
            }

        return result

    def generate_panel(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a panel KiCad file with the board arrayed."""
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        board_path = self.board.GetFileName()
        if not board_path:
            return {"success": False, "error": "Board has no file path. Save it first."}

        rows = params.get("rows", 2)
        cols = params.get("cols", 2)
        gap_mm = params.get("gap_mm", 2.0)
        add_rails = params.get("add_rails", True)
        rail_width_mm = params.get("rail_width_mm", 5.0)
        add_fiducials = params.get("add_fiducials", True)
        add_tooling_holes = params.get("add_tooling_holes", True)
        output_path = params.get("output_path")

        if not output_path:
            stem = Path(board_path).stem
            output_path = str(Path(board_path).parent / f"{stem}_panel_{rows}x{cols}.kicad_pcb")

        import subprocess
        kikit_available = False
        try:
            result = subprocess.run(
                ["kikit", "--version"],
                capture_output=True, text=True, timeout=10,
            )
            kikit_available = result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        if kikit_available:
            cmd = [
                "kikit", "panelize",
                "--layout", f"grid; rows: {rows}; cols: {cols}; space: {gap_mm}mm",
                "--tabs", "fixed; width: 3mm; vcount: 2",
                "--cuts", "mousebites; drill: 0.5mm; spacing: 0.8mm; offset: 0.25mm",
            ]
            if add_rails:
                cmd.extend(["--framing", f"railstb; width: {rail_width_mm}mm"])
            if add_fiducials:
                cmd.extend(["--fiducials", "type: 3fid; hoffset: 2.5mm; voffset: 2.5mm"])
            if add_tooling_holes:
                cmd.extend(["--tooling", "type: 3hole; hoffset: 2.5mm; voffset: 2.5mm; size: 1.152mm"])
            cmd.extend(["--post", "millradius: 1mm"])
            cmd.extend([board_path, output_path])

            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                if result.returncode == 0:
                    return {
                        "success": True,
                        "method": "kikit",
                        "output_path": output_path,
                        "layout": f"{rows}x{cols}",
                        "boards_per_panel": rows * cols,
                    }
                else:
                    return {
                        "success": False,
                        "error": f"KiKit panelize failed: {result.stderr[:500]}",
                    }
            except subprocess.TimeoutExpired:
                return {"success": False, "error": "Panelization timed out"}

        return {
            "success": False,
            "error": "KiKit not installed. Install it: pip install kikit",
            "manual_instructions": {
                "layout": f"{rows}x{cols}",
                "gap_mm": gap_mm,
                "rails": add_rails,
                "note": "Without KiKit, use KiCad's built-in panelizer or kikit CLI",
            },
            "calculated_panel": self.calculate_panel_layout({
                "board_width_mm": self._get_board_size()["width_mm"] if self._get_board_size() else 0,
                "board_height_mm": self._get_board_size()["height_mm"] if self._get_board_size() else 0,
                "separation_mm": gap_mm,
                "add_rails": add_rails,
                "rail_width_mm": rail_width_mm,
            }),
        }

    def add_fiducials(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add assembly fiducial markers to the board."""
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        try:
            import pcbnew
        except ImportError:
            return {"success": False, "error": "pcbnew not available"}

        count = params.get("count", 3)
        diameter_mm = params.get("diameter_mm", 1.0)
        clearance_mm = params.get("clearance_mm", 2.0)
        placement = params.get("placement", "corners")  # corners, custom
        side = params.get("side", "both")  # front, back, both
        positions = params.get("positions")  # [{x, y}, ...] for custom

        bbox = self.board.GetBoardEdgesBoundingBox()
        bx = bbox.GetX()
        by = bbox.GetY()
        bw = bbox.GetWidth()
        bh = bbox.GetHeight()
        margin = int(3e6)

        if positions:
            fid_positions = [(int(p["x"] * 1e6), int(p["y"] * 1e6)) for p in positions]
        elif placement == "corners":
            fid_positions = [
                (bx + margin, by + margin),
                (bx + bw - margin, by + margin),
                (bx + margin, by + bh - margin),
            ]
            if count >= 4:
                fid_positions.append((bx + bw - margin, by + bh - margin))
        else:
            fid_positions = [
                (bx + margin, by + margin),
                (bx + bw - margin, by + margin),
                (bx + bw // 2, by + bh - margin),
            ]

        fid_positions = fid_positions[:count]

        existing_fids = sum(1 for f in self.board.GetFootprints() if f.GetReference().startswith("FID"))
        next_num = existing_fids + 1
        added = 0

        layers = []
        if side in ("front", "both"):
            layers.append(pcbnew.F_Cu)
        if side in ("back", "both"):
            layers.append(pcbnew.B_Cu)

        for layer in layers:
            for x, y in fid_positions:
                fp = pcbnew.PCB_FOOTPRINT(self.board)
                fp.SetReference(f"FID{next_num}")
                fp.SetValue("Fiducial")

                pad = pcbnew.PAD(fp)
                size = int(diameter_mm * 1e6)
                pad.SetSize(pcbnew.VECTOR2I(size, size))
                pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
                pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
                pad.SetLayerSet(pcbnew.LSET(layer))
                pad.SetName("1")

                mask_size = int((diameter_mm + clearance_mm * 2) * 1e6)
                pad.SetLocalSolderMaskMargin(int(clearance_mm * 1e6))

                fp.Add(pad)
                fp.SetPosition(pcbnew.VECTOR2I(x, y))
                if layer == pcbnew.B_Cu:
                    fp.Flip(fp.GetPosition(), False)

                self.board.Add(fp)
                added += 1
                next_num += 1

        return {
            "success": True,
            "fiducials_added": added,
            "diameter_mm": diameter_mm,
            "clearance_mm": clearance_mm,
            "side": side,
        }
