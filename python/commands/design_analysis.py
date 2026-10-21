"""
Design Analysis integration for KiCAD MCP Server.

Wraps kicad-happy (MIT license) analyzers as subprocesses. Provides:
- PCB layout analysis (trace widths, via counts, connectivity, DFM scoring)
- Schematic analysis (60+ detectors: power regulators, filters, buses, ESD)
- EMC pre-compliance (44 rule checks: ground plane, decoupling, routing)
- Thermal analysis (junction temps, thermal vias, hotspot proximity)
- Cross-domain analysis (schematic-to-PCB consistency)

Requires: kicad-happy installed (clone to ~/.kicad-mcp/kicad-happy)
Dependencies: Python 3.10+ stdlib only (zero pip deps)
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

DEFAULT_INSTALL_DIR = os.path.join(os.path.expanduser("~"), ".kicad-mcp", "kicad-happy")


def _find_script(name: str) -> Optional[str]:
    """Find a kicad-happy analyzer script."""
    script_dirs = [
        os.path.join(DEFAULT_INSTALL_DIR, "skills", "kicad", "scripts"),
        os.path.join(DEFAULT_INSTALL_DIR, "skills", "emc", "scripts"),
        os.path.join(DEFAULT_INSTALL_DIR, "skills", "spice", "scripts"),
    ]
    override = os.environ.get("KICAD_HAPPY_DIR")
    if override:
        script_dirs.insert(0, os.path.join(override, "skills", "kicad", "scripts"))
        script_dirs.insert(1, os.path.join(override, "skills", "emc", "scripts"))

    for d in script_dirs:
        path = os.path.join(d, name)
        if os.path.isfile(path):
            return path
    return None


def _run_analyzer(script_name: str, input_path: str, extra_args: List[str] = None,
                  timeout: int = 120) -> Dict[str, Any]:
    """Run a kicad-happy analyzer script and capture JSON output."""
    script = _find_script(script_name)
    if not script:
        return {
            "success": False,
            "error": f"Analyzer script {script_name} not found. Install kicad-happy first.",
            "install_instructions": (
                f"git clone https://github.com/aklofas/kicad-happy {DEFAULT_INSTALL_DIR}"
            ),
        }

    cmd = ["python3", "-I", script, input_path]
    if extra_args:
        cmd.extend(extra_args)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode != 0:
            return {
                "success": False,
                "error": f"Analyzer failed (exit {result.returncode})",
                "stderr": result.stderr[-2000:] if result.stderr else "",
            }

        try:
            analysis = json.loads(result.stdout)
            return {"success": True, "analysis": analysis}
        except json.JSONDecodeError:
            return {
                "success": True,
                "raw_output": result.stdout[-5000:] if result.stdout else "",
                "note": "Output was not JSON (use --text mode?)",
            }

    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Analysis timed out after {timeout}s"}
    except Exception as e:
        return {"success": False, "error": str(e)}


class DesignAnalysisCommands:
    def __init__(self, board=None):
        self.board = board

    def _get_board_path(self, params: Dict[str, Any]) -> str:
        board_path = params.get("board_path") or params.get("pcb_path")
        if not board_path and self.board:
            board_path = self.board.GetFileName()
        if not board_path:
            raise ValueError("No board path available")
        return board_path

    def analyze_pcb(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Run comprehensive PCB layout analysis."""
        try:
            board_path = self._get_board_path(params)
        except ValueError as e:
            return {"success": False, "error": str(e)}

        extra_args = []
        if params.get("full"):
            extra_args.append("--full")
        if params.get("proximity"):
            extra_args.append("--proximity")
        if params.get("stage"):
            extra_args.extend(["--stage", params["stage"]])

        result = _run_analyzer("analyze_pcb.py", board_path, extra_args,
                               timeout=params.get("timeout", 120))

        if result.get("success") and result.get("analysis"):
            analysis = result["analysis"]
            summary = {
                "success": True,
                "board_path": board_path,
                "analysis_type": "pcb_layout",
            }

            if "board" in analysis:
                summary["board_info"] = {
                    "width_mm": analysis["board"].get("width_mm"),
                    "height_mm": analysis["board"].get("height_mm"),
                    "layer_count": analysis["board"].get("layer_count"),
                    "area_mm2": analysis["board"].get("area_mm2"),
                }

            if "statistics" in analysis:
                summary["statistics"] = analysis["statistics"]

            if "findings" in analysis:
                findings = analysis["findings"]
                summary["finding_count"] = len(findings)
                by_severity = {}
                for f in findings:
                    sev = f.get("severity", "info")
                    by_severity[sev] = by_severity.get(sev, 0) + 1
                summary["findings_by_severity"] = by_severity
                summary["findings"] = findings[:30]

            if "connectivity" in analysis:
                conn = analysis["connectivity"]
                summary["connectivity"] = {
                    "unrouted_nets": conn.get("unrouted_count", 0),
                    "total_nets": conn.get("total_nets", 0),
                }

            return summary
        return result

    def analyze_schematic(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Run comprehensive schematic analysis (60+ circuit detectors)."""
        sch_path = params.get("schematic_path")
        if not sch_path:
            board_path = None
            try:
                board_path = self._get_board_path(params)
            except ValueError:
                pass
            if board_path:
                sch_path = str(Path(board_path).with_suffix(".kicad_sch"))
                if not os.path.isfile(sch_path):
                    pro_path = str(Path(board_path).with_suffix(".kicad_pro"))
                    if os.path.isfile(pro_path):
                        sch_path = pro_path

        if not sch_path or not os.path.isfile(sch_path):
            return {
                "success": False,
                "error": "No schematic file found. Pass schematic_path parameter."
            }

        extra_args = []
        if params.get("stage"):
            extra_args.extend(["--stage", params["stage"]])

        result = _run_analyzer("analyze_schematic.py", sch_path, extra_args,
                               timeout=params.get("timeout", 180))

        if result.get("success") and result.get("analysis"):
            analysis = result["analysis"]
            summary = {
                "success": True,
                "schematic_path": sch_path,
                "analysis_type": "schematic",
            }

            if "components" in analysis:
                summary["component_count"] = len(analysis["components"])

            if "signal_analysis" in analysis:
                sig = analysis["signal_analysis"]
                summary["detected_circuits"] = {}
                for key in ["power_regulators", "voltage_dividers", "filters",
                            "opamp_circuits", "transistor_circuits", "crystal_oscillators"]:
                    if key in sig and sig[key]:
                        summary["detected_circuits"][key] = len(sig[key])

            if "bus_topology" in analysis:
                buses = analysis["bus_topology"]
                summary["detected_buses"] = {}
                for bus_type in ["i2c", "spi", "uart", "can", "usb", "ethernet"]:
                    if bus_type in buses and buses[bus_type]:
                        summary["detected_buses"][bus_type] = len(buses[bus_type])

            if "findings" in analysis:
                findings = analysis["findings"]
                summary["finding_count"] = len(findings)
                by_severity = {}
                for f in findings:
                    sev = f.get("severity", "info")
                    by_severity[sev] = by_severity.get(sev, 0) + 1
                summary["findings_by_severity"] = by_severity
                summary["findings"] = findings[:30]

            if "pdn" in analysis:
                summary["pdn_analysis"] = analysis["pdn"]

            return summary
        return result

    def analyze_emc(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Run EMC pre-compliance analysis (44 rule checks)."""
        try:
            board_path = self._get_board_path(params)
        except ValueError as e:
            return {"success": False, "error": str(e)}

        extra_args = []
        standard = params.get("standard")
        if standard:
            extra_args.extend(["--standard", standard])

        schematic_json = params.get("schematic_json")
        if schematic_json:
            extra_args.extend(["--schematic", schematic_json])

        result = _run_analyzer("analyze_emc.py", board_path, extra_args,
                               timeout=params.get("timeout", 120))

        if result.get("success") and result.get("analysis"):
            analysis = result["analysis"]
            summary = {
                "success": True,
                "board_path": board_path,
                "analysis_type": "emc_precompliance",
            }

            if "findings" in analysis:
                findings = analysis["findings"]
                summary["finding_count"] = len(findings)

                by_category = {}
                by_severity = {}
                for f in findings:
                    cat = f.get("rule_id", "unknown").split("-")[0] if f.get("rule_id") else "unknown"
                    by_category[cat] = by_category.get(cat, 0) + 1
                    sev = f.get("severity", "info")
                    by_severity[sev] = by_severity.get(sev, 0) + 1

                summary["findings_by_category"] = by_category
                summary["findings_by_severity"] = by_severity
                summary["findings"] = findings[:30]

                category_names = {
                    "GP": "Ground Plane",
                    "DC": "Decoupling",
                    "SW": "Switching/Harmonics",
                    "CK": "Clock Routing",
                    "DP": "Differential Pairs",
                    "IO": "I/O Filtering",
                    "RP": "Return Path",
                    "XT": "Crosstalk",
                    "ES": "ESD Protection",
                    "BE": "Board Edge",
                    "SH": "Shielding",
                    "PD": "PDN Impedance",
                    "TS": "Thermal/Spacing",
                }
                summary["category_names"] = category_names

            return summary
        return result

    def analyze_thermal(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Run thermal analysis (junction temps, thermal vias, hotspots)."""
        try:
            board_path = self._get_board_path(params)
        except ValueError as e:
            return {"success": False, "error": str(e)}

        extra_args = []
        ambient_temp = params.get("ambient_temp")
        if ambient_temp:
            extra_args.extend(["--ambient", str(ambient_temp)])

        result = _run_analyzer("analyze_thermal.py", board_path, extra_args,
                               timeout=params.get("timeout", 120))

        if result.get("success") and result.get("analysis"):
            analysis = result["analysis"]
            summary = {
                "success": True,
                "board_path": board_path,
                "analysis_type": "thermal",
            }

            if "findings" in analysis:
                findings = analysis["findings"]
                summary["finding_count"] = len(findings)
                by_severity = {}
                for f in findings:
                    sev = f.get("severity", "info")
                    by_severity[sev] = by_severity.get(sev, 0) + 1
                summary["findings_by_severity"] = by_severity
                summary["findings"] = findings[:20]

            if "thermal_summary" in analysis:
                summary["thermal_summary"] = analysis["thermal_summary"]

            return summary
        return result

    def analyze_cross_domain(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Run cross-domain analysis (schematic vs PCB consistency)."""
        try:
            board_path = self._get_board_path(params)
        except ValueError as e:
            return {"success": False, "error": str(e)}

        sch_path = params.get("schematic_path")
        if not sch_path:
            sch_path = str(Path(board_path).with_suffix(".kicad_sch"))

        if not os.path.isfile(sch_path):
            return {
                "success": False,
                "error": f"Schematic not found at {sch_path}. Pass schematic_path parameter."
            }

        extra_args = []
        if sch_path:
            extra_args.extend(["--schematic", sch_path])

        result = _run_analyzer("cross_analysis.py", board_path, extra_args,
                               timeout=params.get("timeout", 180))

        if result.get("success") and result.get("analysis"):
            analysis = result["analysis"]
            return {
                "success": True,
                "board_path": board_path,
                "schematic_path": sch_path,
                "analysis_type": "cross_domain",
                "findings": analysis.get("findings", [])[:30],
                "finding_count": len(analysis.get("findings", [])),
            }
        return result

    def check_analyzers(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Check which kicad-happy analyzers are available."""
        analyzers = {
            "analyze_pcb.py": "PCB layout analysis",
            "analyze_schematic.py": "Schematic analysis (60+ detectors)",
            "analyze_emc.py": "EMC pre-compliance (44 rules)",
            "analyze_thermal.py": "Thermal analysis",
            "cross_analysis.py": "Cross-domain analysis",
            "analyze_gerbers.py": "Gerber file analysis",
        }

        available = {}
        for script, desc in analyzers.items():
            path = _find_script(script)
            available[script] = {
                "description": desc,
                "found": bool(path),
                "path": path,
            }

        any_found = any(v["found"] for v in available.values())

        result = {
            "success": True,
            "install_dir": DEFAULT_INSTALL_DIR,
            "installed": any_found,
            "analyzers": available,
        }

        if not any_found:
            result["install_instructions"] = (
                f"git clone https://github.com/aklofas/kicad-happy {DEFAULT_INSTALL_DIR}"
            )

        return result

    def install_analyzers(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Download and install kicad-happy analyzers."""
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
                 "https://github.com/aklofas/kicad-happy.git",
                 install_dir],
                capture_output=True, text=True, timeout=60,
            )
            if clone_result.returncode != 0:
                return {
                    "success": False,
                    "error": f"Git clone failed: {clone_result.stderr}",
                }

            # Verify scripts exist
            found_count = 0
            for script in ["analyze_pcb.py", "analyze_schematic.py", "analyze_emc.py"]:
                path = os.path.join(install_dir, "skills", "kicad", "scripts", script)
                if os.path.isfile(path):
                    found_count += 1

            return {
                "success": True,
                "install_dir": install_dir,
                "scripts_found": found_count,
                "note": "kicad-happy requires Python 3.10+ (stdlib only, no pip deps needed)",
            }

        except Exception as e:
            logger.error(f"Installation failed: {e}")
            return {"success": False, "error": str(e)}
