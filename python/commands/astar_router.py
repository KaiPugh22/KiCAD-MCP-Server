"""
A* PCB Router integration for KiCAD MCP Server.

Wraps KiCadRoutingTools (MIT license) which provides a Rust-accelerated
A* grid router with Python orchestration. Called as a subprocess since
it requires the compiled Rust grid_router module.

The tool handles:
- Single-ended net routing with A* pathfinding
- Bus-aware routing with parallel track attraction
- Configurable via costs, grid step, clearances
- Rip-up-and-reroute for congested designs
- Net class-aware track widths and via sizes

Requires: KiCadRoutingTools installed (pip install kicadroutingtools or
          clone + python build_router.py)
"""

import os
import json
import subprocess
import shutil
import logging
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger("kicad_interface")

DEFAULT_INSTALL_DIR = os.path.join(os.path.expanduser("~"), ".kicad-mcp", "KiCadRoutingTools")


def _find_krt_route_script() -> Optional[str]:
    """Find the KiCadRoutingTools route.py script."""
    candidates = [
        os.path.join(DEFAULT_INSTALL_DIR, "py_router", "route.py"),
        os.environ.get("KRT_ROUTE_SCRIPT", ""),
    ]
    # Also check if installed as a package
    try:
        import importlib.util
        spec = importlib.util.find_spec("py_router.route")
        if spec and spec.origin:
            candidates.append(spec.origin)
    except (ImportError, ModuleNotFoundError):
        pass

    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


def _find_krt_diff_script() -> Optional[str]:
    """Find the KiCadRoutingTools route_diff.py script."""
    candidates = [
        os.path.join(DEFAULT_INSTALL_DIR, "py_router", "route_diff.py"),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


class AStarRouterCommands:
    def __init__(self, board=None):
        self.board = board

    def _get_board_path(self, params: Dict[str, Any]) -> str:
        board_path = params.get("board_path")
        if not board_path and self.board:
            board_path = self.board.GetFileName()
        if not board_path:
            raise ValueError("No board path available")
        return board_path

    def astar_route(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Route nets using the A* grid router."""
        script = _find_krt_route_script()
        if not script:
            return {
                "success": False,
                "error": (
                    "KiCadRoutingTools not found. Install it:\n"
                    f"  git clone https://github.com/drandyhaas/KiCadRoutingTools {DEFAULT_INSTALL_DIR}\n"
                    f"  cd {DEFAULT_INSTALL_DIR} && python build_router.py"
                ),
            }

        try:
            board_path = self._get_board_path(params)
            net_names = params.get("net_names", [])
            output_path = params.get("output_path")
            if not output_path:
                stem = Path(board_path).stem
                output_path = str(Path(board_path).parent / f"{stem}.routed.kicad_pcb")

            cmd = [
                "python3", "-I", script,
                board_path,
                output_path,
            ]

            if net_names:
                for net in net_names:
                    cmd.extend(["--nets", net])

            layers = params.get("layers", [])
            if layers:
                cmd.extend(["--layers"] + layers)

            grid_step = params.get("grid_step", 0.1)
            cmd.extend(["--grid-step", str(grid_step)])

            max_iterations = params.get("max_iterations", 200000)
            cmd.extend(["--max-iterations", str(max_iterations)])

            track_width = params.get("track_width")
            if track_width:
                cmd.extend(["--track-width", str(track_width)])

            clearance = params.get("clearance")
            if clearance:
                cmd.extend(["--clearance", str(clearance)])

            via_size = params.get("via_size")
            if via_size:
                cmd.extend(["--via-size", str(via_size)])

            via_drill = params.get("via_drill")
            if via_drill:
                cmd.extend(["--via-drill", str(via_drill)])

            via_cost = params.get("via_cost")
            if via_cost is not None:
                cmd.extend(["--via-cost", str(via_cost)])

            if params.get("bus_enabled"):
                cmd.append("--bus")
                bus_radius = params.get("bus_detection_radius", 5.0)
                cmd.extend(["--bus-detection-radius", str(bus_radius)])

            if params.get("track_width_from_class"):
                cmd.append("--track-width-from-class")

            json_out = str(Path(output_path).with_suffix(".route_report.json"))
            cmd.extend(["--json-out", json_out])

            timeout = params.get("timeout", 600)

            logger.info(f"Running A* router: {' '.join(cmd[:6])}...")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=os.path.dirname(script),
            )

            report = {}
            if os.path.isfile(json_out):
                with open(json_out, "r") as f:
                    report = json.load(f)

            if result.returncode != 0:
                return {
                    "success": False,
                    "error": f"A* router failed (exit {result.returncode})",
                    "stderr": result.stderr[-2000:] if result.stderr else "",
                    "partial_report": report,
                }

            return {
                "success": True,
                "output_path": output_path,
                "board_path": board_path,
                "report": report,
                "nets_requested": len(net_names) if net_names else "all unrouted",
                "nets_routed": report.get("routed", 0),
                "nets_failed": report.get("failed", 0),
                "total_vias": report.get("total_vias", 0),
            }

        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"A* routing timed out after {timeout}s"}
        except Exception as e:
            logger.error(f"A* routing failed: {e}")
            return {"success": False, "error": str(e)}

    def astar_route_differential(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Route differential pairs using the A* router."""
        script = _find_krt_diff_script()
        if not script:
            return {
                "success": False,
                "error": "KiCadRoutingTools route_diff.py not found. Install KiCadRoutingTools first.",
            }

        try:
            board_path = self._get_board_path(params)
            output_path = params.get("output_path")
            if not output_path:
                stem = Path(board_path).stem
                output_path = str(Path(board_path).parent / f"{stem}.diffrouted.kicad_pcb")

            cmd = [
                "python3", "-I", script,
                board_path,
                output_path,
            ]

            pair_nets = params.get("pair_nets", [])
            if pair_nets:
                for pair in pair_nets:
                    if isinstance(pair, (list, tuple)) and len(pair) == 2:
                        cmd.extend(["--pair", pair[0], pair[1]])

            spacing = params.get("spacing")
            if spacing:
                cmd.extend(["--spacing", str(spacing)])

            track_width = params.get("track_width")
            if track_width:
                cmd.extend(["--track-width", str(track_width)])

            timeout = params.get("timeout", 600)

            logger.info("Running A* differential pair router...")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=os.path.dirname(script),
            )

            if result.returncode != 0:
                return {
                    "success": False,
                    "error": f"Differential routing failed (exit {result.returncode})",
                    "stderr": result.stderr[-2000:] if result.stderr else "",
                }

            return {
                "success": True,
                "output_path": output_path,
                "board_path": board_path,
                "pairs_routed": len(pair_nets) if pair_nets else "auto-detected",
            }

        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"Differential routing timed out after {timeout}s"}
        except Exception as e:
            logger.error(f"Differential routing failed: {e}")
            return {"success": False, "error": str(e)}

    def check_astar_router(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Check if KiCadRoutingTools is installed and the Rust module is built."""
        script = _find_krt_route_script()
        result = {
            "success": True,
            "route_script_found": bool(script),
            "route_script_path": script,
            "diff_script_found": bool(_find_krt_diff_script()),
            "install_dir": DEFAULT_INSTALL_DIR,
        }

        if not script:
            result["success"] = False
            result["error"] = "KiCadRoutingTools not found"
            result["install_instructions"] = (
                f"git clone https://github.com/drandyhaas/KiCadRoutingTools {DEFAULT_INSTALL_DIR}\n"
                f"cd {DEFAULT_INSTALL_DIR} && python build_router.py"
            )
            return result

        # Check if Rust module is compiled
        try:
            check_result = subprocess.run(
                ["python3", "-I", "-c", "import grid_router; print(grid_router.__version__)"],
                capture_output=True, text=True, timeout=10,
                cwd=os.path.dirname(script),
            )
            if check_result.returncode == 0:
                result["rust_module_available"] = True
                result["rust_module_version"] = check_result.stdout.strip()
            else:
                result["rust_module_available"] = False
                result["rust_module_error"] = check_result.stderr.strip()[:500]
        except Exception as e:
            result["rust_module_available"] = False
            result["rust_module_error"] = str(e)

        return result

    def install_astar_router(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Download and install KiCadRoutingTools."""
        install_dir = params.get("install_dir", DEFAULT_INSTALL_DIR)

        try:
            if os.path.isdir(install_dir):
                if not params.get("force"):
                    return {
                        "success": False,
                        "error": f"Already installed at {install_dir}. Pass force=true to reinstall.",
                    }
                shutil.rmtree(install_dir)

            os.makedirs(os.path.dirname(install_dir), exist_ok=True)

            clone_result = subprocess.run(
                ["git", "clone", "--depth", "1",
                 "https://github.com/drandyhaas/KiCadRoutingTools.git",
                 install_dir],
                capture_output=True, text=True, timeout=120,
            )
            if clone_result.returncode != 0:
                return {
                    "success": False,
                    "error": f"Git clone failed: {clone_result.stderr}",
                }

            build_script = os.path.join(install_dir, "build_router.py")
            if os.path.isfile(build_script):
                build_result = subprocess.run(
                    ["python3", "-I", build_script],
                    capture_output=True, text=True, timeout=300,
                    cwd=install_dir,
                )
                if build_result.returncode != 0:
                    return {
                        "success": True,
                        "install_dir": install_dir,
                        "cloned": True,
                        "rust_built": False,
                        "build_error": build_result.stderr[-1000:],
                        "note": "Clone succeeded but Rust build failed. You need Rust toolchain (rustup) to build the A* module.",
                    }

            return {
                "success": True,
                "install_dir": install_dir,
                "cloned": True,
                "rust_built": True,
            }

        except Exception as e:
            logger.error(f"Installation failed: {e}")
            return {"success": False, "error": str(e)}
