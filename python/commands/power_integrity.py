"""
Power Integrity / PDN Analysis Commands

Analyzes power distribution networks on the PCB:
- DC voltage drop across power planes and traces
- Decoupling capacitor adequacy (target impedance method)
- Power plane current density estimation
- Bulk/ceramic cap staging recommendations
"""

import math
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Copper resistivity at 20°C in Ω·m
COPPER_RESISTIVITY = 1.724e-8

# Standard copper weights and their thicknesses
COPPER_WEIGHT_MM = {
    "0.5oz": 0.0175,
    "1oz": 0.035,
    "2oz": 0.070,
    "3oz": 0.105,
}

# Common decoupling cap ESR values (typ, in mΩ) by package
CAP_ESR_TYPICAL = {
    "0201": 50,
    "0402": 30,
    "0603": 15,
    "0805": 10,
    "1206": 8,
    "bulk_tantalum": 100,
    "bulk_electrolytic": 200,
    "bulk_polymer": 15,
}

# Standard capacitor values for staging
STANDARD_CAPS = [
    {"value": "100nF", "farads": 100e-9, "package": "0402", "role": "high_freq"},
    {"value": "1uF", "farads": 1e-6, "package": "0402", "role": "mid_freq"},
    {"value": "10uF", "farads": 10e-6, "package": "0805", "role": "mid_freq"},
    {"value": "47uF", "farads": 47e-6, "package": "1206", "role": "bulk"},
    {"value": "100uF", "farads": 100e-6, "package": "bulk_polymer", "role": "bulk"},
    {"value": "470uF", "farads": 470e-6, "package": "bulk_electrolytic", "role": "bulk"},
]


class PowerIntegrityCommands:
    def __init__(self, board=None):
        self.board = board

    def set_board(self, board):
        self.board = board

    def analyze_pdn(self, voltage: float, max_current: float,
                    max_ripple_pct: float = 3.0,
                    frequency_range: Optional[List[float]] = None,
                    copper_weight: str = "1oz",
                    num_caps_installed: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
        """
        Full PDN analysis: target impedance, cap staging, and recommendations.

        Args:
            voltage: Rail voltage (e.g. 3.3, 1.8, 5.0)
            max_current: Maximum transient current draw in amps
            max_ripple_pct: Maximum allowed voltage ripple as percentage
            frequency_range: [min_Hz, max_Hz] of interest (default [10kHz, 1GHz])
            copper_weight: Copper weight for plane impedance
            num_caps_installed: Current cap inventory, e.g. {"100nF": 10, "10uF": 4}

        Returns:
            Complete PDN analysis with target impedance, cap staging, and grades.
        """
        if frequency_range is None:
            frequency_range = [10e3, 1e9]

        max_ripple_v = voltage * (max_ripple_pct / 100.0)
        target_z = max_ripple_v / max_current

        f_low, f_high = frequency_range

        # Analyze required capacitor staging
        staging = self._calculate_cap_staging(target_z, f_low, f_high, max_current)

        # Check existing caps against requirements
        adequacy = None
        if num_caps_installed:
            adequacy = self._check_cap_adequacy(
                num_caps_installed, staging, target_z, f_low, f_high
            )

        # Plane impedance estimate
        thickness = COPPER_WEIGHT_MM.get(copper_weight, 0.035) / 1000  # to meters
        plane_z = self._estimate_plane_impedance(thickness, f_high)

        grade = "PASS"
        issues = []

        if plane_z > target_z * 0.5:
            issues.append(f"Plane impedance ({plane_z*1000:.1f} mΩ) is high relative "
                         f"to target ({target_z*1000:.1f} mΩ). Consider heavier copper or wider planes.")

        if adequacy and not adequacy["meets_target"]:
            grade = "FAIL"
            issues.extend(adequacy.get("issues", []))
        elif issues:
            grade = "WARNING"

        return {
            "success": True,
            "voltage": voltage,
            "max_current": max_current,
            "max_ripple_v": round(max_ripple_v, 4),
            "target_impedance_ohms": round(target_z, 6),
            "target_impedance_mohms": round(target_z * 1000, 2),
            "frequency_range_hz": frequency_range,
            "plane_impedance_mohms": round(plane_z * 1000, 2),
            "cap_staging": staging,
            "existing_cap_adequacy": adequacy,
            "grade": grade,
            "issues": issues,
        }

    def _calculate_cap_staging(self, target_z: float, f_low: float, f_high: float,
                               max_current: float) -> List[Dict[str, Any]]:
        """Determine the optimal capacitor staging to meet target impedance."""
        stages = []

        # Bulk caps: cover low frequencies (10kHz-100kHz)
        bulk_z = target_z
        bulk_cap_f = 100e3
        c_bulk = 1 / (2 * math.pi * bulk_cap_f * bulk_z)
        if c_bulk > 10e-6:
            best_bulk = None
            for cap in reversed(STANDARD_CAPS):
                if cap["role"] == "bulk" and cap["farads"] >= c_bulk * 0.8:
                    best_bulk = cap
                    break
            if best_bulk is None:
                best_bulk = STANDARD_CAPS[-1]

            n_bulk = max(1, math.ceil(c_bulk / best_bulk["farads"]))
            stages.append({
                "role": "bulk",
                "frequency_band": "10kHz - 100kHz",
                "cap_value": best_bulk["value"],
                "count": n_bulk,
                "package": best_bulk["package"],
                "total_capacitance_uF": round(n_bulk * best_bulk["farads"] * 1e6, 1),
            })

        # Mid-frequency caps (100kHz - 10MHz)
        mid_z = target_z
        mid_cap_f = 5e6
        c_mid = 1 / (2 * math.pi * mid_cap_f * mid_z)
        mid_caps = [c for c in STANDARD_CAPS if c["role"] == "mid_freq"]
        for cap in mid_caps:
            n = max(1, math.ceil(c_mid / cap["farads"]))
            if n <= 20:
                stages.append({
                    "role": "mid_frequency",
                    "frequency_band": "100kHz - 10MHz",
                    "cap_value": cap["value"],
                    "count": n,
                    "package": cap["package"],
                    "total_capacitance_uF": round(n * cap["farads"] * 1e6, 1),
                })
                break

        # High-frequency caps (10MHz - 1GHz)
        hf_z = target_z
        hf_cap_f = 100e6
        c_hf = 1 / (2 * math.pi * hf_cap_f * hf_z)
        n_hf = max(1, math.ceil(c_hf / 100e-9))
        stages.append({
            "role": "high_frequency",
            "frequency_band": "10MHz - 1GHz",
            "cap_value": "100nF",
            "count": n_hf,
            "package": "0402",
            "total_capacitance_uF": round(n_hf * 0.1, 1),
            "note": "Place as close to IC power pins as possible",
        })

        return stages

    def _check_cap_adequacy(self, installed: Dict[str, int],
                            staging: List[Dict], target_z: float,
                            f_low: float, f_high: float) -> Dict[str, Any]:
        """Check if installed caps meet the target impedance."""
        issues = []
        meets_target = True

        for stage in staging:
            key = stage["cap_value"]
            needed = stage["count"]
            have = installed.get(key, 0)

            if have < needed:
                meets_target = False
                issues.append(
                    f"{stage['role']}: need {needed}x {key} but only have {have}. "
                    f"Add {needed - have} more ({stage['package']})"
                )

        return {
            "meets_target": meets_target,
            "issues": issues,
            "installed": installed,
        }

    def _estimate_plane_impedance(self, thickness_m: float, frequency: float) -> float:
        """Estimate copper plane impedance at a given frequency using skin effect."""
        skin_depth = math.sqrt(COPPER_RESISTIVITY / (math.pi * frequency * 4e-7 * math.pi))
        effective_thickness = min(thickness_m, skin_depth)
        # Per-square impedance assuming 100mm x 100mm plane
        r_sheet = COPPER_RESISTIVITY / effective_thickness
        return r_sheet

    def calculate_voltage_drop_plane(self, current: float, length_mm: float,
                                     width_mm: float, copper_weight: str = "1oz",
                                     temperature: float = 25.0) -> Dict[str, Any]:
        """
        Calculate DC voltage drop across a copper plane segment.

        Args:
            current: Current in amps
            length_mm: Current path length in mm
            width_mm: Effective current path width in mm
            copper_weight: Copper thickness
            temperature: Operating temperature in °C
        """
        thickness_mm = COPPER_WEIGHT_MM.get(copper_weight, 0.035)

        # Temperature-adjusted resistivity
        alpha = 0.00393  # copper temperature coefficient
        rho = COPPER_RESISTIVITY * (1 + alpha * (temperature - 20))

        # Convert to meters
        length_m = length_mm / 1000
        width_m = width_mm / 1000
        thickness_m = thickness_mm / 1000

        area = width_m * thickness_m
        resistance = rho * length_m / area
        v_drop = current * resistance
        power_loss = current * current * resistance

        return {
            "success": True,
            "voltage_drop_mv": round(v_drop * 1000, 3),
            "resistance_mohms": round(resistance * 1000, 4),
            "power_loss_mw": round(power_loss * 1000, 3),
            "current_density_a_per_mm2": round(current / (width_mm * thickness_mm), 2),
            "parameters": {
                "current_a": current,
                "length_mm": length_mm,
                "width_mm": width_mm,
                "copper_weight": copper_weight,
                "temperature_c": temperature,
            }
        }

    def suggest_bypass_strategy(self, ic_type: str, power_pins: int = 1,
                                max_current: float = 0.5,
                                voltage: float = 3.3) -> Dict[str, Any]:
        """
        Suggest a bypass/decoupling strategy for a specific IC type.

        Args:
            ic_type: IC category (mcu, fpga, adc, dac, rf, ldo, ddr, pll)
            power_pins: Number of VCC pins on the IC
            max_current: Maximum current draw in amps
            voltage: Supply voltage
        """
        strategies = {
            "mcu": {
                "per_pin": [
                    {"value": "100nF", "package": "0402", "count": 1},
                ],
                "per_ic": [
                    {"value": "10uF", "package": "0805", "count": 1},
                    {"value": "1uF", "package": "0402", "count": 1},
                ],
                "placement": "Within 2mm of power pin, on same layer or adjacent via",
                "notes": "Route power trace to cap first, then to pin (series path)",
            },
            "fpga": {
                "per_pin": [
                    {"value": "100nF", "package": "0402", "count": 1},
                    {"value": "10nF", "package": "0201", "count": 1},
                ],
                "per_ic": [
                    {"value": "10uF", "package": "0805", "count": 2},
                    {"value": "100uF", "package": "bulk_polymer", "count": 1},
                ],
                "placement": "100nF within 1mm of pin, 10nF within 0.5mm if space allows",
                "notes": "Multiple cap values needed to cover wide frequency range. "
                        "Use ground vias immediately adjacent to cap GND pad.",
            },
            "adc": {
                "per_pin": [
                    {"value": "100nF", "package": "0402", "count": 1},
                ],
                "per_ic": [
                    {"value": "10uF", "package": "0805", "count": 1},
                ],
                "placement": "Star-ground topology. Keep analog and digital decoupling separate.",
                "notes": "Use ferrite bead between digital and analog supply if shared rail. "
                        "Consider LC filter for AVDD.",
            },
            "dac": {
                "per_pin": [
                    {"value": "100nF", "package": "0402", "count": 1},
                ],
                "per_ic": [
                    {"value": "10uF", "package": "0805", "count": 1},
                ],
                "placement": "Separate analog and digital ground planes under IC",
                "notes": "Output reference decoupling is critical. Check datasheet for VREF caps.",
            },
            "rf": {
                "per_pin": [
                    {"value": "100nF", "package": "0402", "count": 1},
                    {"value": "10pF", "package": "0201", "count": 1},
                ],
                "per_ic": [
                    {"value": "1uF", "package": "0402", "count": 1},
                ],
                "placement": "As close as physically possible. Minimize via inductance.",
                "notes": "RF supply filtering often needs specific LC networks per datasheet.",
            },
            "ldo": {
                "per_pin": [],
                "per_ic": [
                    {"value": "10uF", "package": "0805", "count": 1},  # input
                    {"value": "10uF", "package": "0805", "count": 1},  # output
                ],
                "placement": "Input cap close to VIN, output cap close to VOUT",
                "notes": "Check datasheet for ESR requirements — some LDOs oscillate with "
                        "low-ESR ceramics. Output cap value affects transient response.",
            },
            "ddr": {
                "per_pin": [
                    {"value": "100nF", "package": "0402", "count": 1},
                ],
                "per_ic": [
                    {"value": "10uF", "package": "0805", "count": 2},
                    {"value": "47uF", "package": "1206", "count": 1},
                ],
                "placement": "VTT termination caps near memory ICs. VDDQ caps near both "
                            "controller and memory.",
                "notes": "DDR requires low-impedance PDN for clean signal integrity. "
                        "Route VTT reference through ferrite bead.",
            },
            "pll": {
                "per_pin": [
                    {"value": "100nF", "package": "0402", "count": 1},
                    {"value": "10nF", "package": "0201", "count": 1},
                ],
                "per_ic": [
                    {"value": "1uF", "package": "0402", "count": 1},
                ],
                "placement": "Isolate PLL supply with ferrite bead + cap filter",
                "notes": "PLL jitter is directly affected by supply noise. Use separate "
                        "filtered supply from main digital rail.",
            },
        }

        ic_lower = ic_type.lower()
        if ic_lower not in strategies:
            return {
                "success": False,
                "error": f"Unknown IC type '{ic_type}'. Supported: {list(strategies.keys())}",
            }

        strategy = strategies[ic_lower]

        # Calculate total caps needed
        total_caps = []
        for cap in strategy["per_pin"]:
            total_caps.append({
                **cap,
                "count": cap["count"] * power_pins,
                "reason": f"{cap['count']} per power pin x {power_pins} pins",
            })
        for cap in strategy["per_ic"]:
            total_caps.append({
                **cap,
                "reason": "Per IC",
            })

        # Estimate if PDN is adequate
        target_z = (voltage * 0.03) / max_current  # 3% ripple budget
        total_cap_farads = sum(
            self._value_to_farads(c["value"]) * c["count"]
            for c in total_caps
        )

        return {
            "success": True,
            "ic_type": ic_type,
            "power_pins": power_pins,
            "strategy": {
                "per_pin_caps": strategy["per_pin"],
                "per_ic_caps": strategy["per_ic"],
                "total_caps": total_caps,
                "placement_guide": strategy["placement"],
                "notes": strategy["notes"],
            },
            "pdn_estimate": {
                "target_impedance_mohms": round(target_z * 1000, 2),
                "total_capacitance_uF": round(total_cap_farads * 1e6, 2),
            },
        }

    def _value_to_farads(self, value_str: str) -> float:
        """Convert a cap value string like '100nF' or '10uF' to farads."""
        val = value_str.lower().strip()
        if val.endswith("pf"):
            return float(val[:-2]) * 1e-12
        elif val.endswith("nf"):
            return float(val[:-2]) * 1e-9
        elif val.endswith("uf"):
            return float(val[:-2]) * 1e-6
        elif val.endswith("mf"):
            return float(val[:-2]) * 1e-3
        return float(val)

    def analyze_power_tree(self) -> Dict[str, Any]:
        """
        Analyze the power distribution tree from the board's netlist.
        Identifies power rails, regulators, and load relationships.
        """
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        try:
            import pcbnew
            board = self.board

            power_nets = {}
            regulators = []
            loads = []

            # Scan nets for power-related names
            netinfo = board.GetNetInfo()
            for i in range(board.GetNetCount()):
                net = netinfo.GetNetItem(i)
                if not net:
                    continue
                name = net.GetNetname().upper()
                is_power = any(p in name for p in [
                    "VCC", "VDD", "3V3", "3.3V", "5V", "12V", "1V8", "1.8V",
                    "2V5", "2.5V", "VBAT", "VIN", "VOUT", "VBUS", "VSYS",
                    "+3V3", "+5V", "+12V", "+3.3V",
                ])
                is_gnd = any(p in name for p in ["GND", "VSS", "AGND", "DGND", "PGND"])

                if is_power or is_gnd:
                    # Count connected pads
                    pad_count = 0
                    for fp in board.GetFootprints():
                        for pad in fp.Pads():
                            if pad.GetNetname() == net.GetNetname():
                                pad_count += 1
                    power_nets[net.GetNetname()] = {
                        "code": net.GetNetCode(),
                        "type": "ground" if is_gnd else "power",
                        "connected_pads": pad_count,
                    }

            # Identify regulators (components with both VIN and VOUT connections)
            for fp in board.GetFootprints():
                ref = fp.GetReference()
                value = fp.GetValue().upper()
                pad_nets = set()
                for pad in fp.Pads():
                    pad_nets.add(pad.GetNetname())

                has_power_in = any(
                    n.upper() in ["VIN", "VBUS", "VSYS"] or
                    any(p in n.upper() for p in ["5V", "12V", "VBAT", "VIN"])
                    for n in pad_nets
                )
                has_power_out = any(
                    any(p in n.upper() for p in ["VOUT", "3V3", "1V8", "2V5"])
                    for n in pad_nets
                )

                is_reg = (
                    ref.startswith("U") and
                    (has_power_in and has_power_out) or
                    any(kw in value for kw in ["LDO", "REG", "7805", "1117", "AMS"])
                )

                if is_reg:
                    regulators.append({
                        "reference": ref,
                        "value": fp.GetValue(),
                        "input_nets": [n for n in pad_nets if any(
                            p in n.upper() for p in ["VIN", "VBUS", "5V", "12V"]
                        )],
                        "output_nets": [n for n in pad_nets if any(
                            p in n.upper() for p in ["VOUT", "3V3", "1V8", "2V5"]
                        )],
                    })

            return {
                "success": True,
                "power_nets": power_nets,
                "regulators": regulators,
                "summary": {
                    "power_rail_count": sum(1 for v in power_nets.values() if v["type"] == "power"),
                    "ground_net_count": sum(1 for v in power_nets.values() if v["type"] == "ground"),
                    "regulator_count": len(regulators),
                },
            }

        except Exception as e:
            logger.error(f"Power tree analysis failed: {e}")
            return {"success": False, "error": str(e)}
