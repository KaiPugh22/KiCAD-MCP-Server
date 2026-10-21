"""
Board Setup Automation

One-command board configuration:
- Auto-detect power nets and create appropriate net classes
- Configure design rules from fab house constraints
- Set up stackup for impedance targets
- Generate complete board setup from a spec
"""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Common stackup configurations
STACKUPS = {
    "2layer_1.6mm": {
        "layers": 2,
        "thickness_mm": 1.6,
        "dielectric_er": 4.5,  # FR4
        "copper_weight": "1oz",
        "dielectric_thickness_mm": 1.53,  # between copper layers
        "prepreg_er": 4.2,
    },
    "4layer_1.6mm": {
        "layers": 4,
        "thickness_mm": 1.6,
        "dielectric_er": 4.5,
        "copper_weight": "1oz",
        "layer_thicknesses_mm": [0.035, 0.36, 0.035, 0.76, 0.035, 0.36, 0.035],
        "dielectric_ers": [4.2, 4.5, 4.2],
    },
    "4layer_jlcpcb_jlc04161h": {
        "layers": 4,
        "thickness_mm": 1.6,
        "dielectric_er": 4.6,
        "copper_weight": "1oz",
        "layer_thicknesses_mm": [0.035, 0.1, 0.0175, 1.265, 0.0175, 0.1, 0.035],
        "dielectric_ers": [3.02, 4.6, 3.02],
        "note": "JLCPCB JLC04161H-7628 stackup",
    },
    "6layer_1.6mm": {
        "layers": 6,
        "thickness_mm": 1.6,
        "dielectric_er": 4.5,
        "copper_weight": "1oz",
    },
}

# Standard signal types and their typical impedance targets
SIGNAL_IMPEDANCES = {
    "single_ended_50": {"target_z": 50, "tolerance_pct": 10, "type": "microstrip"},
    "single_ended_75": {"target_z": 75, "tolerance_pct": 10, "type": "microstrip"},
    "differential_90": {"target_z": 90, "tolerance_pct": 10, "type": "differential"},
    "differential_100": {"target_z": 100, "tolerance_pct": 10, "type": "differential"},
    "usb2": {"target_z": 90, "tolerance_pct": 10, "type": "differential"},
    "usb3": {"target_z": 85, "tolerance_pct": 10, "type": "differential"},
    "hdmi": {"target_z": 100, "tolerance_pct": 10, "type": "differential"},
    "ethernet": {"target_z": 100, "tolerance_pct": 10, "type": "differential"},
    "pcie": {"target_z": 85, "tolerance_pct": 10, "type": "differential"},
    "ddr4": {"target_z": 40, "tolerance_pct": 10, "type": "single"},
}


class BoardSetupCommands:
    def __init__(self, board=None):
        self.board = board

    def set_board(self, board):
        self.board = board

    def auto_setup_board(self, fab_house: str = "jlcpcb_standard",
                         stackup: str = "2layer_1.6mm",
                         signal_types: Optional[List[str]] = None,
                         max_power_current: float = 1.0,
                         dry_run: bool = True) -> Dict[str, Any]:
        """
        One-command board setup: configure design rules, net classes, and stackup.

        Args:
            fab_house: Fabrication house preset for design rules
            stackup: PCB stackup configuration
            signal_types: List of signal types requiring impedance control
                         (e.g. ['usb2', 'ethernet', 'single_ended_50'])
            max_power_current: Maximum current on power nets in amps
            dry_run: If True, just report what would be configured
        """
        from commands.dfm_checker import FAB_CONSTRAINTS
        from commands.calculators import CalculatorCommands

        if fab_house not in FAB_CONSTRAINTS:
            return {"success": False, "error": f"Unknown fab: {fab_house}",
                    "available": list(FAB_CONSTRAINTS.keys())}

        if stackup not in STACKUPS:
            return {"success": False, "error": f"Unknown stackup: {stackup}",
                    "available": list(STACKUPS.keys())}

        constraints = FAB_CONSTRAINTS[fab_house]
        stack = STACKUPS[stackup]
        calc = CalculatorCommands(self.board)

        config = {
            "fab_house": constraints["name"],
            "stackup": stackup,
            "design_rules": {},
            "net_classes": [],
            "impedance_controlled": [],
        }

        # Design rules from fab constraints
        config["design_rules"] = {
            "min_track_width_mm": constraints["min_trace_width"],
            "min_clearance_mm": constraints["min_clearance"],
            "min_via_diameter_mm": constraints["min_via_diameter"],
            "min_via_drill_mm": constraints["min_drill"],
            "min_annular_ring_mm": constraints["min_annular_ring"],
            "copper_layers": stack["layers"],
        }

        # Default net class
        config["net_classes"].append({
            "name": "Default",
            "track_width_mm": max(0.2, constraints["min_trace_width"]),
            "clearance_mm": max(0.15, constraints["min_clearance"]),
            "via_diameter_mm": max(0.6, constraints["min_via_diameter"]),
            "via_drill_mm": max(0.3, constraints["min_drill"]),
        })

        # Power net class based on current
        power_result = calc.suggest_netclass_params(
            current=max_power_current,
            signal_type="power",
            manufacturer=fab_house.split("_")[0],
        )
        if power_result.get("success"):
            config["net_classes"].append({
                "name": "Power",
                "track_width_mm": power_result.get("recommended_track_width_mm", 0.5),
                "clearance_mm": power_result.get("recommended_clearance_mm", 0.2),
                "via_diameter_mm": power_result.get("recommended_via_diameter_mm", 0.8),
                "via_drill_mm": power_result.get("recommended_via_drill_mm", 0.4),
                "assigned_nets_pattern": ["VCC*", "VDD*", "+*V*", "VBUS", "VBAT"],
                "current_capacity_a": max_power_current,
            })

        # Impedance-controlled net classes
        if signal_types:
            for sig_type in signal_types:
                if sig_type not in SIGNAL_IMPEDANCES:
                    continue

                spec = SIGNAL_IMPEDANCES[sig_type]
                dielectric_h = stack.get("dielectric_thickness_mm",
                                         stack.get("layer_thicknesses_mm", [0, 0.36])[1])
                er = stack.get("dielectric_er", 4.5)

                # Calculate trace width for target impedance
                imp_result = calc.solve_trace_width_for_impedance(
                    target_impedance=spec["target_z"],
                    dielectric_height=dielectric_h,
                    dielectric_constant=er,
                    copper_thickness=0.035,
                    mode=spec["type"],
                    spacing=0.15 if "differential" in spec["type"] else None,
                )

                nc = {
                    "name": sig_type.upper().replace("_", " "),
                    "signal_type": sig_type,
                    "target_impedance_ohms": spec["target_z"],
                    "tolerance_pct": spec["tolerance_pct"],
                }

                if imp_result.get("success"):
                    tw = imp_result.get("trace_width_mm", 0.15)
                    tw = max(tw, constraints["min_trace_width"])
                    nc["track_width_mm"] = round(tw, 3)
                    nc["clearance_mm"] = round(max(tw * 2, constraints["min_clearance"]), 3)

                    if "differential" in spec["type"]:
                        nc["diff_pair_gap_mm"] = imp_result.get("spacing_mm", 0.15)
                        nc["diff_pair_width_mm"] = round(tw, 3)
                else:
                    nc["error"] = imp_result.get("message", "Could not solve impedance")

                nc["via_diameter_mm"] = max(0.45, constraints["min_via_diameter"])
                nc["via_drill_mm"] = max(0.25, constraints["min_drill"])

                config["net_classes"].append(nc)
                config["impedance_controlled"].append(sig_type)

        # Auto-detect and assign power nets
        power_nets_assigned = []
        if self.board and not dry_run:
            try:
                import pcbnew
                board = self.board
                ds = board.GetDesignSettings()

                # Apply design rules
                ds.m_TrackMinWidth = int(pcbnew.FromMM(config["design_rules"]["min_track_width_mm"]))
                ds.m_MinClearance = int(pcbnew.FromMM(config["design_rules"]["min_clearance_mm"]))
                ds.m_ViasMinSize = int(pcbnew.FromMM(config["design_rules"]["min_via_diameter_mm"]))

                # Create net classes
                nc_settings = ds.GetNetClasses()
                for nc in config["net_classes"]:
                    name = nc["name"]
                    if name == "Default":
                        target = nc_settings.GetDefault()
                    else:
                        if not nc_settings.HasNetClass(name):
                            new_nc = pcbnew.NETCLASS(name)
                            nc_settings.Add(new_nc)
                        target = nc_settings.Find(name)

                    if target:
                        target.SetTrackWidth(int(pcbnew.FromMM(nc["track_width_mm"])))
                        target.SetClearance(int(pcbnew.FromMM(nc["clearance_mm"])))
                        target.SetViaDiameter(int(pcbnew.FromMM(nc["via_diameter_mm"])))
                        target.SetViaDrill(int(pcbnew.FromMM(nc["via_drill_mm"])))

                # Assign power nets to Power class
                netinfo = board.GetNetInfo()
                for i in range(board.GetNetCount()):
                    net = netinfo.GetNetItem(i)
                    if not net:
                        continue
                    name_upper = net.GetNetname().upper()
                    is_power = any(p in name_upper for p in [
                        "VCC", "VDD", "3V3", "3.3V", "5V", "12V", "1V8",
                        "VBAT", "VIN", "VOUT", "VBUS", "+",
                    ])
                    if is_power and net.GetNetname():
                        try:
                            net.SetNetClass(nc_settings.Find("Power"))
                            power_nets_assigned.append(net.GetNetname())
                        except Exception:
                            pass

                pcbnew.Refresh()

            except Exception as e:
                logger.error(f"Failed to apply board setup: {e}")
                config["apply_error"] = str(e)

        config["power_nets_assigned"] = power_nets_assigned

        return {
            "success": True,
            "dry_run": dry_run,
            "config": config,
            "message": (
                f"Board setup for {constraints['name']} with {stack['layers']}-layer "
                f"{stack['thickness_mm']}mm stackup: {len(config['net_classes'])} net classes"
                + (f", {len(power_nets_assigned)} power nets assigned" if power_nets_assigned else "")
                + (". Run with dry_run=false to apply." if dry_run else ". Applied.")
            ),
        }

    def list_stackups(self) -> Dict[str, Any]:
        """List available PCB stackup configurations."""
        return {
            "success": True,
            "stackups": {
                k: {key: val for key, val in v.items() if key != "layer_thicknesses_mm"}
                for k, v in STACKUPS.items()
            },
        }

    def list_signal_types(self) -> Dict[str, Any]:
        """List available impedance-controlled signal types."""
        return {
            "success": True,
            "signal_types": SIGNAL_IMPEDANCES,
        }
