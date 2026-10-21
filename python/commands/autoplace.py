"""
Connectivity-aware auto-placement integration for KiCAD MCP Server.

Wraps KiCad-Autoplace (MIT license) which provides:
- Multi-strategy seeding (force-directed, topological, floorplan)
- Simulated annealing optimization (HPWL + overlap + routing cost)
- Block detection from hierarchical sheets
- Connector edge affinity
- Decoupling capacitor proximity optimization
- Multi-seed evaluation with best-of-N selection

Called as a subprocess with KiCad's Python since it uses pcbnew SWIG for I/O.
The engine core (model, anneal, metrics) is pure Python.

Requires: KiCad-Autoplace installed (clone to ~/.kicad-mcp/KiCad-Autoplace)
"""

import os
import json
import subprocess
import shutil
import logging
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger("kicad_interface")

DEFAULT_INSTALL_DIR = os.path.join(os.path.expanduser("~"), ".kicad-mcp", "KiCad-Autoplace")


def _find_cli_script() -> Optional[str]:
    """Find the KiCad-Autoplace cli.py script."""
    candidates = [
        os.path.join(DEFAULT_INSTALL_DIR, "cli.py"),
        os.environ.get("AUTOPLACE_CLI", ""),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


def _find_kicad_python() -> Optional[str]:
    """Find KiCad's bundled Python (needed for pcbnew import)."""
    import platform
    system = platform.system()

    if system == "Darwin":
        versions = ["3.9", "3.10", "3.11", "3.12", "3.13"]
        for app in ["/Applications/KiCad/KiCad.app", "/Applications/KiCAD/KiCad.app"]:
            for v in versions:
                p = f"{app}/Contents/Frameworks/Python.framework/Versions/{v}/bin/python3"
                if os.path.isfile(p):
                    return p
    elif system == "Windows":
        for ver in ["10.0", "9.0", "8.0"]:
            p = f"C:\\Program Files\\KiCad\\{ver}\\bin\\python.exe"
            if os.path.isfile(p):
                return p
    elif system == "Linux":
        for p in ["/usr/lib/kicad/bin/python3", "/usr/bin/python3"]:
            if os.path.isfile(p):
                return p

    return shutil.which("python3")


class AutoplaceCommands:
    def __init__(self, board=None):
        self.board = board

    def _get_board_path(self, params: Dict[str, Any]) -> str:
        board_path = params.get("board_path")
        if not board_path and self.board:
            board_path = self.board.GetFileName()
        if not board_path:
            raise ValueError("No board path available")
        return board_path

    def auto_place(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Run connectivity-aware auto-placement on the board."""
        cli = _find_cli_script()
        if not cli:
            return {
                "success": False,
                "error": (
                    "KiCad-Autoplace not found. Install it:\n"
                    f"  git clone https://github.com/DTU-EKB/KiCad-Autoplace {DEFAULT_INSTALL_DIR}"
                ),
            }

        kicad_python = _find_kicad_python()
        if not kicad_python:
            return {
                "success": False,
                "error": "KiCad Python not found. KiCad-Autoplace requires pcbnew.",
            }

        try:
            board_path = self._get_board_path(params)
            output_path = params.get("output_path")
            if not output_path:
                stem = Path(board_path).stem
                output_path = str(Path(board_path).parent / f"{stem}.autoplaced.kicad_pcb")

            cmd = [kicad_python, cli, "place", board_path, output_path]

            seed = params.get("seed", 0)
            cmd.append(str(seed))

            env = os.environ.copy()

            strategy = params.get("strategy", "auto")
            env["STRATEGY"] = strategy

            if params.get("orient_pass"):
                env["ORIENT"] = "1"

            cross_weight = params.get("cross_weight")
            if cross_weight is not None:
                env["CROSS_WEIGHT"] = str(cross_weight)

            connectors = params.get("connectors", [])
            locked = params.get("locked", [])
            if connectors or locked:
                sidecar_path = str(Path(board_path).with_suffix(".autoplace.json"))
                sidecar_data = {}
                if os.path.isfile(sidecar_path):
                    with open(sidecar_path, "r") as f:
                        sidecar_data = json.load(f)
                if connectors:
                    sidecar_data["connectors"] = connectors
                if locked:
                    sidecar_data["locked"] = locked
                with open(sidecar_path, "w") as f:
                    json.dump(sidecar_data, f)

            timeout = params.get("timeout", 300)

            logger.info(f"Running autoplace (strategy={strategy}, seed={seed})...")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                cwd=os.path.dirname(cli),
            )

            if result.returncode != 0:
                return {
                    "success": False,
                    "error": f"Autoplace failed (exit {result.returncode})",
                    "stderr": result.stderr[-2000:] if result.stderr else "",
                    "stdout": result.stdout[-1000:] if result.stdout else "",
                }

            report = {}
            try:
                for line in result.stdout.strip().split("\n"):
                    if line.strip().startswith("{"):
                        report = json.loads(line)
                        break
            except (json.JSONDecodeError, ValueError):
                pass

            return {
                "success": True,
                "output_path": output_path,
                "board_path": board_path,
                "strategy": strategy,
                "seed": seed,
                "report": report,
                "hpwl_before": report.get("hpwl_before"),
                "hpwl_after": report.get("hpwl_after"),
                "improvement_pct": report.get("improvement_pct"),
                "overlaps": report.get("overlaps", 0),
            }

        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"Autoplace timed out after {timeout}s"}
        except Exception as e:
            logger.error(f"Autoplace failed: {e}")
            return {"success": False, "error": str(e)}

    def auto_place_multi_seed(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Run multi-seed auto-placement (evaluates N candidates, picks best)."""
        cli = _find_cli_script()
        if not cli:
            return {
                "success": False,
                "error": "KiCad-Autoplace not found. Install it first.",
            }

        kicad_python = _find_kicad_python()
        if not kicad_python:
            return {
                "success": False,
                "error": "KiCad Python not found.",
            }

        try:
            board_path = self._get_board_path(params)
            output_path = params.get("output_path")
            if not output_path:
                stem = Path(board_path).stem
                output_path = str(Path(board_path).parent / f"{stem}.autoplaced.kicad_pcb")

            cmd = [kicad_python, cli, "place-multi", board_path, output_path]

            env = os.environ.copy()
            num_seeds = params.get("num_seeds", 6)
            env["SEEDS"] = str(num_seeds)

            strategy = params.get("strategy", "mixed")
            env["STRATEGY"] = strategy

            if params.get("orient_pass"):
                env["ORIENT"] = "1"

            timeout = params.get("timeout", 900)

            logger.info(f"Running multi-seed autoplace ({num_seeds} seeds, strategy={strategy})...")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                cwd=os.path.dirname(cli),
            )

            if result.returncode != 0:
                return {
                    "success": False,
                    "error": f"Multi-seed autoplace failed (exit {result.returncode})",
                    "stderr": result.stderr[-2000:] if result.stderr else "",
                }

            report = {}
            try:
                for line in reversed(result.stdout.strip().split("\n")):
                    if line.strip().startswith("{"):
                        report = json.loads(line)
                        break
            except (json.JSONDecodeError, ValueError):
                pass

            return {
                "success": True,
                "output_path": output_path,
                "board_path": board_path,
                "num_seeds": num_seeds,
                "strategy": strategy,
                "report": report,
                "best_seed": report.get("best_seed"),
                "best_hpwl": report.get("best_hpwl"),
            }

        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"Multi-seed autoplace timed out after {timeout}s"}
        except Exception as e:
            logger.error(f"Multi-seed autoplace failed: {e}")
            return {"success": False, "error": str(e)}

    def placement_metrics(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate current placement quality metrics (HPWL, crossings, overlaps)."""
        cli = _find_cli_script()
        if not cli:
            return {"success": False, "error": "KiCad-Autoplace not found."}

        kicad_python = _find_kicad_python()
        if not kicad_python:
            return {"success": False, "error": "KiCad Python not found."}

        try:
            board_path = self._get_board_path(params)
            cmd = [kicad_python, cli, "metrics", board_path]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=os.path.dirname(cli),
            )

            if result.returncode != 0:
                return {
                    "success": False,
                    "error": f"Metrics failed (exit {result.returncode})",
                    "stderr": result.stderr[-1000:] if result.stderr else "",
                }

            metrics = {}
            try:
                metrics = json.loads(result.stdout)
            except json.JSONDecodeError:
                metrics = {"raw_output": result.stdout[-2000:]}

            return {
                "success": True,
                "board_path": board_path,
                "metrics": metrics,
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def check_autoplace(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Check if KiCad-Autoplace is installed and functional."""
        cli = _find_cli_script()
        kicad_python = _find_kicad_python()

        result = {
            "success": True,
            "cli_found": bool(cli),
            "cli_path": cli,
            "kicad_python_found": bool(kicad_python),
            "kicad_python_path": kicad_python,
            "install_dir": DEFAULT_INSTALL_DIR,
        }

        if not cli:
            result["success"] = False
            result["install_instructions"] = (
                f"git clone https://github.com/DTU-EKB/KiCad-Autoplace {DEFAULT_INSTALL_DIR}"
            )

        if not kicad_python:
            result["success"] = False
            result["note"] = "KiCad Python with pcbnew is required for auto-placement."

        return result

    def install_autoplace(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Download and install KiCad-Autoplace."""
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
                 "https://github.com/DTU-EKB/KiCad-Autoplace.git",
                 install_dir],
                capture_output=True, text=True, timeout=60,
            )
            if clone_result.returncode != 0:
                return {
                    "success": False,
                    "error": f"Git clone failed: {clone_result.stderr}",
                }

            return {
                "success": True,
                "install_dir": install_dir,
                "note": "KiCad-Autoplace requires KiCad's Python with pcbnew module.",
            }

        except Exception as e:
            logger.error(f"Installation failed: {e}")
            return {"success": False, "error": str(e)}
