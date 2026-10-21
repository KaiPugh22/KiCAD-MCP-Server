"""
PCB Design Calculators

IPC-2221/IPC-2152 trace width, via current capacity, impedance,
voltage drop, and automated netclass parameter suggestion.
"""

import math
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger("kicad_interface")


class CalculatorCommands:
    """PCB design calculators for trace width, impedance, via current, etc."""

    def __init__(self, board=None):
        self.board = board

    # ------------------------------------------------------------------
    # IPC-2221 Trace Width Calculator
    # ------------------------------------------------------------------
    def calculate_trace_width(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate required trace width for a given current using IPC-2221.

        Uses the IPC-2221 formula:
            I = k * dT^b * A^c
        where:
            I = current (A)
            k, b, c = constants (different for internal vs external layers)
            dT = temperature rise (°C)
            A = cross-sectional area (mils²)

        Solving for A:  A = (I / (k * dT^b))^(1/c)
        Then width = A / thickness
        """
        try:
            current = params.get("current")  # Amps
            if current is None or current <= 0:
                return {
                    "success": False,
                    "message": "current (Amps) is required and must be > 0",
                }

            temp_rise = params.get("tempRise", 10)  # °C above ambient
            copper_weight = params.get("copperWeight", 1.0)  # oz/ft²
            layer_type = params.get("layerType", "external")  # external or internal

            # Copper thickness: 1 oz/ft² = 1.378 mils = 0.035 mm
            thickness_mils = copper_weight * 1.378
            thickness_mm = copper_weight * 0.035

            # IPC-2221 constants
            if layer_type == "internal":
                k, b, c = 0.0150, 0.5453, 0.7349
            else:
                k, b, c = 0.0647, 0.4281, 0.6732

            # Solve for cross-sectional area in mils²
            area_mils2 = (current / (k * (temp_rise ** b))) ** (1.0 / c)

            # Width in mils, then convert to mm
            width_mils = area_mils2 / thickness_mils
            width_mm = width_mils * 0.0254

            # Also calculate resistance per unit length for reference
            # Copper resistivity at 20°C: 1.724e-6 ohm·cm
            resistivity = 1.724e-6  # ohm·cm
            temp_coeff = 0.00393  # per °C
            ambient_temp = params.get("ambientTemp", 25)
            adjusted_resistivity = resistivity * (
                1 + temp_coeff * (ambient_temp + temp_rise - 20)
            )

            # Cross-section in cm²
            area_cm2 = (width_mm * 0.1) * (thickness_mm * 0.1)
            resistance_per_cm = adjusted_resistivity / area_cm2 if area_cm2 > 0 else 0
            resistance_per_mm = resistance_per_cm * 0.1

            # Voltage drop per cm at rated current
            vdrop_per_cm = current * resistance_per_cm

            return {
                "success": True,
                "message": f"Trace width for {current}A: {width_mm:.3f}mm ({width_mils:.1f}mil)",
                "calculation": {
                    "current_A": current,
                    "tempRise_C": temp_rise,
                    "copperWeight_oz": copper_weight,
                    "layerType": layer_type,
                    "requiredWidth_mm": round(width_mm, 4),
                    "requiredWidth_mils": round(width_mils, 2),
                    "crossSection_mils2": round(area_mils2, 2),
                    "copperThickness_mm": round(thickness_mm, 4),
                    "resistance_ohm_per_cm": round(resistance_per_cm, 6),
                    "voltageDrop_V_per_cm": round(vdrop_per_cm, 6),
                },
                "recommendations": self._trace_width_recommendations(width_mm, current),
            }

        except Exception as e:
            logger.error(f"Error calculating trace width: {e}")
            return {"success": False, "message": str(e)}

    def _trace_width_recommendations(
        self, width_mm: float, current: float
    ) -> List[str]:
        """Generate practical recommendations based on calculated width."""
        recs = []
        if width_mm < 0.127:
            recs.append(
                "WARNING: Required width is below most fab minimums (0.127mm). "
                "Consider using a heavier copper weight or multiple vias/planes."
            )
        elif width_mm < 0.15:
            recs.append(
                "Width is near JLCPCB minimum (0.127mm). Use 0.15mm+ for margin."
            )
        if current > 3 and width_mm < 1.0:
            recs.append(
                "For high-current traces, consider using copper pours or "
                "polygon fills instead of individual traces."
            )
        if current > 1:
            recs.append(
                "Add thermal relief vias near high-current connections."
            )
        return recs

    # ------------------------------------------------------------------
    # Via Current Capacity Calculator
    # ------------------------------------------------------------------
    def calculate_via_current(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate via current capacity.

        Uses the IPC-2221 barrel plating model:
            Cross-section of barrel = π * drill_diameter * plating_thickness
        Then applies the same IPC-2221 formula for the current.
        """
        try:
            drill_mm = params.get("drillDiameter")  # mm
            if drill_mm is None or drill_mm <= 0:
                return {
                    "success": False,
                    "message": "drillDiameter (mm) is required and must be > 0",
                }

            plating_um = params.get("platingThickness", 25)  # micrometers (1 mil = 25.4 um)
            temp_rise = params.get("tempRise", 10)  # °C
            num_vias = params.get("numVias", 1)

            # Convert to mils for IPC formula
            drill_mils = drill_mm / 0.0254
            plating_mils = plating_um / 25.4

            # Via barrel cross-section (hollow cylinder)
            area_mils2 = math.pi * drill_mils * plating_mils

            # IPC-2221 external layer constants (via barrel is exposed)
            k, b, c = 0.0647, 0.4281, 0.6732
            current_single = k * (temp_rise ** b) * (area_mils2 ** c)
            current_total = current_single * num_vias

            # Thermal resistance estimate
            thermal_resistance = 70.0 / (drill_mm * math.pi)  # rough °C/W

            return {
                "success": True,
                "message": (
                    f"Via capacity: {current_single:.2f}A per via, "
                    f"{current_total:.2f}A total ({num_vias} via{'s' if num_vias > 1 else ''})"
                ),
                "calculation": {
                    "drillDiameter_mm": drill_mm,
                    "platingThickness_um": plating_um,
                    "tempRise_C": temp_rise,
                    "numVias": num_vias,
                    "barrelArea_mils2": round(area_mils2, 2),
                    "currentPerVia_A": round(current_single, 3),
                    "totalCurrent_A": round(current_total, 3),
                    "thermalResistance_C_per_W": round(thermal_resistance, 1),
                },
                "recommendations": self._via_recommendations(
                    drill_mm, current_single, num_vias
                ),
            }

        except Exception as e:
            logger.error(f"Error calculating via current: {e}")
            return {"success": False, "message": str(e)}

    def _via_recommendations(
        self, drill_mm: float, current_per_via: float, num_vias: int
    ) -> List[str]:
        recs = []
        if drill_mm < 0.3:
            recs.append("Drill < 0.3mm may not be available at budget fabs (JLCPCB min: 0.3mm).")
        if current_per_via > 1.5:
            recs.append("Consider multiple smaller vias for better thermal distribution.")
        if num_vias > 1:
            recs.append(
                f"Space {num_vias} vias at least {max(drill_mm * 2, 0.8):.1f}mm apart "
                "for manufacturability."
            )
        return recs

    # ------------------------------------------------------------------
    # Impedance Calculator (Microstrip / Stripline)
    # ------------------------------------------------------------------
    def calculate_impedance(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate trace impedance for microstrip or stripline geometry.

        Microstrip (IPC-2141 / Wadell approximation):
            Z0 = (87 / sqrt(Er + 1.41)) * ln(5.98 * H / (0.8 * W + T))

        Stripline (centered):
            Z0 = (60 / sqrt(Er)) * ln(1.9 * B / (0.8 * W + T))
            where B = distance between ground planes
        """
        try:
            geometry = params.get("geometry", "microstrip")  # microstrip or stripline
            trace_width_mm = params.get("traceWidth")  # mm
            dielectric_height_mm = params.get("dielectricHeight")  # mm (H for microstrip, B for stripline)
            dielectric_constant = params.get("dielectricConstant", 4.5)  # Er (FR4 typical: 4.2-4.8)
            copper_thickness_mm = params.get("copperThickness", 0.035)  # mm (1oz = 0.035mm)

            if trace_width_mm is None or dielectric_height_mm is None:
                return {
                    "success": False,
                    "message": "traceWidth and dielectricHeight (mm) are required",
                }

            W = trace_width_mm
            H = dielectric_height_mm
            T = copper_thickness_mm
            Er = dielectric_constant

            if geometry == "microstrip":
                # Wadell approximation for microstrip
                arg = 5.98 * H / (0.8 * W + T)
                if arg <= 1:
                    return {
                        "success": False,
                        "message": "Trace too wide relative to dielectric height for valid microstrip calculation",
                    }
                z0 = (87.0 / math.sqrt(Er + 1.41)) * math.log(arg)

                # Effective dielectric constant
                er_eff = (Er + 1) / 2 + (Er - 1) / (2 * math.sqrt(1 + 12 * H / W))

                # Propagation delay (ps/mm)
                prop_delay = 3.336 * math.sqrt(er_eff)  # ps/mm

            elif geometry == "stripline":
                B = H  # total distance between planes
                arg = 1.9 * B / (0.8 * W + T)
                if arg <= 1:
                    return {
                        "success": False,
                        "message": "Trace too wide relative to plane spacing for valid stripline calculation",
                    }
                z0 = (60.0 / math.sqrt(Er)) * math.log(arg)
                er_eff = Er
                prop_delay = 3.336 * math.sqrt(er_eff)

            else:
                return {
                    "success": False,
                    "message": f"Unknown geometry '{geometry}'. Use 'microstrip' or 'stripline'.",
                }

            # For differential impedance estimation
            diff_z0 = None
            if "spacing" in params:
                spacing_mm = params["spacing"]
                # Rough coupled-microstrip differential impedance
                coupling_factor = 1 - 0.48 * math.exp(-0.96 * spacing_mm / H)
                diff_z0 = round(2 * z0 * coupling_factor, 2)

            result = {
                "success": True,
                "message": f"{geometry.capitalize()} impedance: {z0:.1f} ohms",
                "calculation": {
                    "geometry": geometry,
                    "traceWidth_mm": W,
                    "dielectricHeight_mm": H,
                    "copperThickness_mm": T,
                    "dielectricConstant": Er,
                    "impedance_ohms": round(z0, 2),
                    "effectiveDielectric": round(er_eff, 3),
                    "propagationDelay_ps_per_mm": round(prop_delay, 3),
                },
            }

            if diff_z0 is not None:
                result["calculation"]["differentialImpedance_ohms"] = diff_z0
                result["calculation"]["spacing_mm"] = params["spacing"]
                result["message"] += f", differential: {diff_z0} ohms"

            # Add recommendations for common targets
            result["commonTargets"] = {
                "USB2.0": {"impedance": 90, "type": "differential"},
                "USB3.0": {"impedance": 90, "type": "differential"},
                "HDMI": {"impedance": 100, "type": "differential"},
                "PCIe": {"impedance": 85, "type": "differential"},
                "DDR4": {"impedance": 40, "type": "single-ended"},
                "Ethernet_100BASE-T": {"impedance": 100, "type": "differential"},
                "LVDS": {"impedance": 100, "type": "differential"},
                "50ohm_RF": {"impedance": 50, "type": "single-ended"},
            }

            return result

        except Exception as e:
            logger.error(f"Error calculating impedance: {e}")
            return {"success": False, "message": str(e)}

    # ------------------------------------------------------------------
    # Solve Trace Width for Target Impedance
    # ------------------------------------------------------------------
    def solve_trace_width_for_impedance(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Find the trace width needed to hit a target impedance.

        Uses iterative bisection on the impedance formula.
        """
        try:
            target_z = params.get("targetImpedance")  # ohms
            geometry = params.get("geometry", "microstrip")
            dielectric_height_mm = params.get("dielectricHeight")
            dielectric_constant = params.get("dielectricConstant", 4.5)
            copper_thickness_mm = params.get("copperThickness", 0.035)

            if target_z is None or dielectric_height_mm is None:
                return {
                    "success": False,
                    "message": "targetImpedance (ohms) and dielectricHeight (mm) are required",
                }

            # Bisection search: wider trace = lower impedance
            w_low, w_high = 0.005, 10.0  # mm
            w_mid = (w_low + w_high) / 2
            z = 0.0
            for _ in range(100):
                w_mid = (w_low + w_high) / 2
                result = self.calculate_impedance({
                    "geometry": geometry,
                    "traceWidth": w_mid,
                    "dielectricHeight": dielectric_height_mm,
                    "dielectricConstant": dielectric_constant,
                    "copperThickness": copper_thickness_mm,
                })
                if not result.get("success"):
                    # Formula fails when trace is too wide relative to dielectric
                    w_high = w_mid
                    continue

                z = result["calculation"]["impedance_ohms"]
                if abs(z - target_z) < 0.01:
                    break
                if z > target_z:
                    w_low = w_mid  # wider trace = lower impedance
                else:
                    w_high = w_mid

            # Also solve for differential if requested
            diff_result = None
            if "targetDifferentialImpedance" in params and "spacing" in params:
                target_diff = params["targetDifferentialImpedance"]
                # Iterative solve for differential
                dw_low, dw_high = 0.005, 10.0
                dw_mid = (dw_low + dw_high) / 2
                dz = 0.0
                for _ in range(100):
                    dw_mid = (dw_low + dw_high) / 2
                    dr = self.calculate_impedance({
                        "geometry": geometry,
                        "traceWidth": dw_mid,
                        "dielectricHeight": dielectric_height_mm,
                        "dielectricConstant": dielectric_constant,
                        "copperThickness": copper_thickness_mm,
                        "spacing": params["spacing"],
                    })
                    if not dr.get("success"):
                        dw_high = dw_mid
                        continue
                    dz = dr["calculation"].get("differentialImpedance_ohms", 0)
                    if abs(dz - target_diff) < 0.1:
                        break
                    if dz > target_diff:
                        dw_low = dw_mid
                    else:
                        dw_high = dw_mid
                diff_result = {
                    "traceWidth_mm": round(dw_mid, 4),
                    "differentialImpedance_ohms": round(dz, 2),
                    "spacing_mm": params["spacing"],
                }

            result_data = {
                "success": True,
                "message": f"Width for {target_z}Ω {geometry}: {w_mid:.4f}mm",
                "solution": {
                    "geometry": geometry,
                    "targetImpedance_ohms": target_z,
                    "traceWidth_mm": round(w_mid, 4),
                    "achievedImpedance_ohms": round(z, 2),
                    "dielectricHeight_mm": dielectric_height_mm,
                    "dielectricConstant": dielectric_constant,
                },
            }
            if diff_result:
                result_data["differentialSolution"] = diff_result

            return result_data

        except Exception as e:
            logger.error(f"Error solving for impedance: {e}")
            return {"success": False, "message": str(e)}

    # ------------------------------------------------------------------
    # Voltage Drop Calculator
    # ------------------------------------------------------------------
    def calculate_voltage_drop(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate voltage drop across a PCB trace."""
        try:
            current = params.get("current")  # A
            trace_length_mm = params.get("traceLength")  # mm
            trace_width_mm = params.get("traceWidth")  # mm
            copper_weight = params.get("copperWeight", 1.0)  # oz/ft²
            temperature = params.get("temperature", 25)  # °C

            if not all([current, trace_length_mm, trace_width_mm]):
                return {
                    "success": False,
                    "message": "current (A), traceLength (mm), and traceWidth (mm) are required",
                }

            copper_thickness_mm = copper_weight * 0.035
            resistivity_20c = 1.724e-8  # ohm·m at 20°C
            temp_coeff = 0.00393
            resistivity = resistivity_20c * (1 + temp_coeff * (temperature - 20))

            # Cross-section in m²
            area_m2 = (trace_width_mm * 1e-3) * (copper_thickness_mm * 1e-3)
            length_m = trace_length_mm * 1e-3

            resistance = resistivity * length_m / area_m2
            voltage_drop = current * resistance
            power_loss = current * current * resistance

            return {
                "success": True,
                "message": f"Voltage drop: {voltage_drop * 1000:.2f}mV over {trace_length_mm}mm",
                "calculation": {
                    "current_A": current,
                    "traceLength_mm": trace_length_mm,
                    "traceWidth_mm": trace_width_mm,
                    "copperWeight_oz": copper_weight,
                    "temperature_C": temperature,
                    "resistance_ohms": round(resistance, 6),
                    "voltageDrop_V": round(voltage_drop, 6),
                    "voltageDrop_mV": round(voltage_drop * 1000, 3),
                    "powerLoss_mW": round(power_loss * 1000, 3),
                },
                "recommendations": self._vdrop_recommendations(voltage_drop, current),
            }

        except Exception as e:
            logger.error(f"Error calculating voltage drop: {e}")
            return {"success": False, "message": str(e)}

    def _vdrop_recommendations(self, vdrop: float, current: float) -> List[str]:
        recs = []
        if vdrop > 0.1:
            recs.append("Voltage drop > 100mV. Consider wider traces or copper pours.")
        if vdrop > 0.05 and current > 0.5:
            recs.append("For sensitive analog circuits, keep drop < 50mV on power rails.")
        if vdrop > 0.3:
            recs.append(
                "Excessive voltage drop. Use a power plane or much wider trace. "
                "Consider relocating the regulator closer to the load."
            )
        return recs

    # ------------------------------------------------------------------
    # Suggest Netclass Parameters
    # ------------------------------------------------------------------
    def suggest_netclass_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Suggest netclass parameters based on electrical requirements.

        Given current, signal type, and manufacturer, returns recommended
        trace width, via size, clearance, and differential pair parameters.
        """
        try:
            current = params.get("current", 0.1)  # A
            signal_type = params.get("signalType", "signal")  # signal, power, highspeed, differential
            manufacturer = params.get("manufacturer", "jlcpcb")
            copper_weight = params.get("copperWeight", 1.0)
            impedance_target = params.get("impedanceTarget")  # ohms, optional

            # Manufacturer minimums
            fab_limits = {
                "jlcpcb": {
                    "minTraceWidth": 0.127,
                    "minClearance": 0.127,
                    "minViaDrill": 0.3,
                    "minViaPad": 0.6,
                    "minDiffPairGap": 0.127,
                    "layers": "2-16",
                },
                "jlcpcb_4layer": {
                    "minTraceWidth": 0.09,
                    "minClearance": 0.09,
                    "minViaDrill": 0.2,
                    "minViaPad": 0.45,
                    "minDiffPairGap": 0.09,
                    "layers": "4-16",
                },
                "oshpark": {
                    "minTraceWidth": 0.152,
                    "minClearance": 0.152,
                    "minViaDrill": 0.254,
                    "minViaPad": 0.508,
                    "minDiffPairGap": 0.152,
                    "layers": "2-4",
                },
                "pcbway": {
                    "minTraceWidth": 0.1,
                    "minClearance": 0.1,
                    "minViaDrill": 0.2,
                    "minViaPad": 0.5,
                    "minDiffPairGap": 0.1,
                    "layers": "2-32",
                },
            }

            limits = fab_limits.get(manufacturer, fab_limits["jlcpcb"])

            # Calculate trace width from current
            tw_result = self.calculate_trace_width({
                "current": current,
                "copperWeight": copper_weight,
                "tempRise": 10,
                "layerType": "external",
            })

            if tw_result.get("success"):
                calc_width = tw_result["calculation"]["requiredWidth_mm"]
            else:
                calc_width = 0.2

            # Apply fab minimum
            trace_width = max(calc_width, limits["minTraceWidth"])

            # Round up to common values
            common_widths = [0.1, 0.127, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0, 1.5, 2.0]
            for cw in common_widths:
                if cw >= trace_width:
                    trace_width = cw
                    break

            # Via sizing based on current
            if current <= 0.5:
                via_drill, via_pad = 0.3, 0.6
            elif current <= 1.0:
                via_drill, via_pad = 0.4, 0.7
            elif current <= 2.0:
                via_drill, via_pad = 0.5, 0.9
            else:
                via_drill, via_pad = 0.6, 1.0

            via_drill = max(via_drill, limits["minViaDrill"])
            via_pad = max(via_pad, limits["minViaPad"])

            # Clearance
            if signal_type == "highspeed":
                clearance = max(0.2, limits["minClearance"])
            elif signal_type == "power":
                clearance = max(0.25, limits["minClearance"])
            else:
                clearance = max(0.15, limits["minClearance"])

            result = {
                "success": True,
                "message": f"Suggested netclass for {current}A {signal_type}",
                "netclassParams": {
                    "traceWidth_mm": trace_width,
                    "clearance_mm": clearance,
                    "viaDiameter_mm": via_pad,
                    "viaDrill_mm": via_drill,
                },
                "fabLimits": limits,
                "manufacturer": manufacturer,
            }

            # Add differential pair params if relevant
            if signal_type in ("differential", "highspeed") or impedance_target:
                dp_width = trace_width
                dp_gap = max(trace_width, limits["minDiffPairGap"])
                result["netclassParams"]["diffPairWidth_mm"] = dp_width
                result["netclassParams"]["diffPairGap_mm"] = dp_gap

                if impedance_target:
                    z_result = self.solve_trace_width_for_impedance({
                        "targetImpedance": impedance_target,
                        "geometry": "microstrip",
                        "dielectricHeight": 0.2,  # typical FR4 prepreg
                        "dielectricConstant": 4.5,
                    })
                    if z_result.get("success"):
                        imp_width = z_result["solution"]["traceWidth_mm"]
                        imp_width = max(imp_width, limits["minTraceWidth"])
                        result["netclassParams"]["traceWidth_mm"] = imp_width
                        result["impedanceNote"] = (
                            f"Width adjusted to {imp_width:.3f}mm for "
                            f"{impedance_target}Ω target (verify with your stackup)"
                        )

            # Power-specific recommendations
            if signal_type == "power":
                via_result = self.calculate_via_current({
                    "drillDiameter": via_drill,
                    "tempRise": 10,
                })
                if via_result.get("success"):
                    via_cap = via_result["calculation"]["currentPerVia_A"]
                    vias_needed = math.ceil(current / via_cap) if via_cap > 0 else 1
                    result["powerRecommendations"] = {
                        "viasNeededForCurrent": vias_needed,
                        "viaCurrentCapacity_A": round(via_cap, 2),
                        "useCopperPour": current > 2,
                        "thermalReliefVias": current > 1,
                    }

            return result

        except Exception as e:
            logger.error(f"Error suggesting netclass params: {e}")
            return {"success": False, "message": str(e)}

    # ------------------------------------------------------------------
    # Auto-Create Power Netclasses
    # ------------------------------------------------------------------
    def auto_create_power_netclasses(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze board nets and auto-create netclasses for power rails.

        Detects power nets (VCC, VDD, 3V3, 5V, 12V, GND, etc.) and creates
        appropriately sized netclasses based on estimated current requirements.
        """
        try:
            if not self.board:
                return {"success": False, "message": "No board is loaded"}

            import pcbnew

            manufacturer = params.get("manufacturer", "jlcpcb")
            copper_weight = params.get("copperWeight", 1.0)

            # Custom current overrides: {"VCC": 2.0, "3V3": 1.5}
            current_overrides = params.get("currentOverrides", {})

            # Default current estimates based on net name patterns
            power_patterns = {
                "GND": {"current": 3.0, "type": "ground"},
                "AGND": {"current": 0.5, "type": "ground"},
                "DGND": {"current": 2.0, "type": "ground"},
                "PGND": {"current": 5.0, "type": "ground"},
                "VCC": {"current": 1.0, "type": "power"},
                "VDD": {"current": 1.0, "type": "power"},
                "VDDA": {"current": 0.3, "type": "power"},
                "VDDIO": {"current": 0.5, "type": "power"},
                "3V3": {"current": 1.0, "type": "power"},
                "3.3V": {"current": 1.0, "type": "power"},
                "+3V3": {"current": 1.0, "type": "power"},
                "+3.3V": {"current": 1.0, "type": "power"},
                "5V": {"current": 2.0, "type": "power"},
                "+5V": {"current": 2.0, "type": "power"},
                "12V": {"current": 3.0, "type": "power"},
                "+12V": {"current": 3.0, "type": "power"},
                "1V8": {"current": 0.5, "type": "power"},
                "+1V8": {"current": 0.5, "type": "power"},
                "1.8V": {"current": 0.5, "type": "power"},
                "2V5": {"current": 0.5, "type": "power"},
                "+2V5": {"current": 0.5, "type": "power"},
                "VBUS": {"current": 3.0, "type": "power"},
                "VBAT": {"current": 2.0, "type": "power"},
                "VIN": {"current": 3.0, "type": "power"},
            }

            netinfo = self.board.GetNetInfo()
            nets_map = netinfo.NetsByName()

            created_classes = []
            matched_nets = []

            for net_name in nets_map:
                if not net_name:
                    continue
                net_upper = net_name.upper().replace(" ", "")

                # Check custom overrides first
                if net_name in current_overrides:
                    current_est = current_overrides[net_name]
                    net_type = "power"
                else:
                    # Match against patterns
                    current_est = None
                    net_type = None
                    for pattern, info in power_patterns.items():
                        if pattern.upper() in net_upper or net_upper == pattern.upper():
                            current_est = info["current"]
                            net_type = info["type"]
                            break

                if current_est is None:
                    continue

                # Get suggested params
                suggestion = self.suggest_netclass_params({
                    "current": current_est,
                    "signalType": "power",
                    "manufacturer": manufacturer,
                    "copperWeight": copper_weight,
                })

                if not suggestion.get("success"):
                    continue

                nc_params = suggestion["netclassParams"]
                class_name = f"Power_{net_name.replace('+', '').replace('.', 'V')}"

                matched_nets.append({
                    "netName": net_name,
                    "className": class_name,
                    "estimatedCurrent_A": current_est,
                    "netType": net_type,
                    "traceWidth_mm": nc_params["traceWidth_mm"],
                    "viaDiameter_mm": nc_params["viaDiameter_mm"],
                    "viaDrill_mm": nc_params["viaDrill_mm"],
                    "clearance_mm": nc_params["clearance_mm"],
                })

            # If dryRun, just return what would be created
            if params.get("dryRun", True):
                return {
                    "success": True,
                    "message": f"Found {len(matched_nets)} power nets (dry run - no changes made)",
                    "dryRun": True,
                    "powerNets": matched_nets,
                    "hint": "Set dryRun=false to actually create the netclasses and assign nets",
                }

            # Actually create netclasses and assign
            design_settings = self.board.GetDesignSettings()
            scale = 1000000  # mm to nm

            for net_info in matched_nets:
                class_name = net_info["className"]

                # Create netclass (KiCad 9/10 compatible)
                try:
                    net_classes = design_settings.GetNetClasses()
                    if hasattr(net_classes, "HasNetClass"):
                        exists = net_classes.HasNetClass(class_name)
                    else:
                        exists = class_name in net_classes
                except Exception:
                    exists = False

                if not exists:
                    nc = pcbnew.NETCLASS(class_name)
                    nc.SetTrackWidth(int(net_info["traceWidth_mm"] * scale))
                    nc.SetClearance(int(net_info["clearance_mm"] * scale))
                    nc.SetViaDiameter(int(net_info["viaDiameter_mm"] * scale))
                    nc.SetViaDrill(int(net_info["viaDrill_mm"] * scale))

                    if hasattr(net_classes, "Add"):
                        net_classes.Add(nc)
                    elif hasattr(design_settings, "SetNetClasses"):
                        net_classes[class_name] = nc
                        design_settings.SetNetClasses(net_classes)

                    created_classes.append(class_name)

                # Assign net to class
                net_obj = nets_map.get(net_info["netName"])
                if net_obj:
                    try:
                        if hasattr(net_obj, "SetNetClassName"):
                            net_obj.SetNetClassName(class_name)
                        elif hasattr(net_obj, "SetClass"):
                            net_obj.SetClass(
                                design_settings.GetNetClasses().Find(class_name)
                            )
                    except Exception as assign_err:
                        logger.warning(
                            f"Could not assign {net_info['netName']} to {class_name}: {assign_err}"
                        )

            return {
                "success": True,
                "message": (
                    f"Created {len(created_classes)} netclasses, "
                    f"configured {len(matched_nets)} power nets"
                ),
                "dryRun": False,
                "createdClasses": created_classes,
                "powerNets": matched_nets,
            }

        except Exception as e:
            logger.error(f"Error auto-creating power netclasses: {e}")
            return {"success": False, "message": str(e)}
