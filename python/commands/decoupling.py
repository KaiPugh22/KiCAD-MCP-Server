"""
Decoupling Capacitor Intelligence

Analyzes schematics and boards to:
- Map decoupling capacitors to the ICs they serve
- Suggest placement distances and values
- Validate decoupling cap placement quality
"""

import re
import os
import math
import logging
from typing import Dict, Any, Optional, List, Tuple, Set
from pathlib import Path

logger = logging.getLogger("kicad_interface")


# Common power pin names across IC families
POWER_PIN_PATTERNS = {
    "vcc", "vdd", "avcc", "avdd", "dvcc", "dvdd",
    "vddio", "vdda", "vddq", "vcca", "vcco",
    "v+", "vin", "vsup", "vpwr",
    "3v3", "5v", "1v8", "2v5", "1v2", "0v9",
    "+3v3", "+5v", "+3.3v", "+5v", "+12v",
    "vbus", "vbat",
}

GROUND_PIN_PATTERNS = {
    "gnd", "vss", "agnd", "dgnd", "pgnd",
    "avss", "dvss", "gndio", "gnda",
    "v-", "vee", "ground",
}

# Typical decoupling values and their frequency ranges
DECOUPLING_GUIDE = {
    "100nF": {
        "value_uF": 0.1,
        "frequency_range": "1MHz - 100MHz",
        "use_case": "General-purpose bypass, digital ICs",
        "package": "0402 or 0603",
    },
    "10nF": {
        "value_uF": 0.01,
        "frequency_range": "10MHz - 500MHz",
        "use_case": "High-frequency bypass, close to IC",
        "package": "0402",
    },
    "1uF": {
        "value_uF": 1.0,
        "frequency_range": "100kHz - 10MHz",
        "use_case": "Bulk bypass, voltage regulators",
        "package": "0402 or 0603",
    },
    "10uF": {
        "value_uF": 10.0,
        "frequency_range": "10kHz - 1MHz",
        "use_case": "Bulk decoupling, regulator output",
        "package": "0805 or 1206",
    },
    "100uF": {
        "value_uF": 100.0,
        "frequency_range": "1kHz - 100kHz",
        "use_case": "Board-level bulk, power entry",
        "package": "electrolytic or 1210",
    },
}


class DecouplingCommands:
    """Decoupling capacitor analysis and intelligence."""

    def __init__(self, board=None):
        self.board = board

    # ------------------------------------------------------------------
    # Analyze Decoupling Map from Schematic
    # ------------------------------------------------------------------
    def analyze_decoupling(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze schematic to map decoupling capacitors to their ICs.

        Parses the .kicad_sch file to find capacitors connected to the same
        power nets as IC power pins, then infers which cap decouples which IC.
        """
        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {
                    "success": False,
                    "message": "schematicPath is required",
                }

            if not os.path.exists(schematic_path):
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            with open(schematic_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Parse components and their connections
            components = self._parse_schematic_components(content)
            nets = self._parse_schematic_nets(content)

            # Classify components
            ics = []
            capacitors = []
            for comp in components:
                ref = comp.get("reference", "")
                if ref.startswith("U") or ref.startswith("IC"):
                    ics.append(comp)
                elif ref.startswith("C"):
                    # Check if it looks like a decoupling cap
                    value = comp.get("value", "").lower()
                    if self._is_likely_decoupling_cap(value):
                        capacitors.append(comp)

            # Build net-to-component mapping
            net_components: Dict[str, List[Dict]] = {}
            for net_name, connected_pins in nets.items():
                net_upper = net_name.upper().replace(" ", "")
                is_power = any(
                    p in net_upper
                    for p in [s.upper() for s in POWER_PIN_PATTERNS]
                )
                is_ground = any(
                    p in net_upper
                    for p in [s.upper() for s in GROUND_PIN_PATTERNS]
                )
                if is_power or is_ground:
                    net_components[net_name] = {
                        "type": "power" if is_power else "ground",
                        "pins": connected_pins,
                    }

            # Map caps to ICs via shared power nets
            decoupling_map = []
            unmatched_caps = []

            for cap in capacitors:
                cap_ref = cap["reference"]
                cap_nets = self._get_component_nets(cap_ref, nets)

                # Find which power nets this cap connects to
                cap_power_nets = [
                    n for n in cap_nets if n in net_components
                ]

                if not cap_power_nets:
                    unmatched_caps.append({
                        "reference": cap_ref,
                        "value": cap.get("value", ""),
                        "reason": "Not connected to any identified power net",
                    })
                    continue

                # Find ICs sharing these power nets
                matched_ics = []
                for power_net in cap_power_nets:
                    for ic in ics:
                        ic_ref = ic["reference"]
                        ic_nets = self._get_component_nets(ic_ref, nets)
                        if power_net in ic_nets:
                            if ic_ref not in [m["reference"] for m in matched_ics]:
                                matched_ics.append({
                                    "reference": ic_ref,
                                    "value": ic.get("value", ""),
                                    "sharedNet": power_net,
                                })

                if matched_ics:
                    decoupling_map.append({
                        "capacitor": {
                            "reference": cap_ref,
                            "value": cap.get("value", ""),
                            "position": cap.get("position"),
                        },
                        "decouples": matched_ics,
                        "powerNets": cap_power_nets,
                    })
                else:
                    unmatched_caps.append({
                        "reference": cap_ref,
                        "value": cap.get("value", ""),
                        "reason": "Connected to power net but no IC shares it",
                        "nets": cap_power_nets,
                    })

            # Check which ICs lack decoupling
            decoupled_ics = set()
            for entry in decoupling_map:
                for ic in entry["decouples"]:
                    decoupled_ics.add(ic["reference"])

            undecoupled_ics = []
            for ic in ics:
                if ic["reference"] not in decoupled_ics:
                    ic_nets = self._get_component_nets(ic["reference"], nets)
                    ic_power_nets = [n for n in ic_nets if n in net_components]
                    if ic_power_nets:
                        undecoupled_ics.append({
                            "reference": ic["reference"],
                            "value": ic.get("value", ""),
                            "powerNets": ic_power_nets,
                            "recommendation": "Add 100nF ceramic cap on each VCC/VDD pin",
                        })

            return {
                "success": True,
                "message": (
                    f"Found {len(decoupling_map)} decoupling associations, "
                    f"{len(undecoupled_ics)} ICs without decoupling"
                ),
                "decouplingMap": decoupling_map,
                "unmatchedCaps": unmatched_caps,
                "undecoupledICs": undecoupled_ics,
                "summary": {
                    "totalICs": len(ics),
                    "totalDecouplingCaps": len(capacitors),
                    "matchedAssociations": len(decoupling_map),
                    "icsWithDecoupling": len(decoupled_ics),
                    "icsWithoutDecoupling": len(undecoupled_ics),
                },
            }

        except Exception as e:
            logger.error(f"Error analyzing decoupling: {e}")
            return {"success": False, "message": str(e)}

    # ------------------------------------------------------------------
    # Board-Level Decoupling Placement Analysis
    # ------------------------------------------------------------------
    def analyze_decoupling_placement(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze PCB placement quality of decoupling capacitors.

        Checks distance from each decoupling cap to its associated IC on the board.
        """
        try:
            if not self.board:
                return {"success": False, "message": "No board is loaded"}

            import pcbnew

            max_good_distance_mm = params.get("maxGoodDistance", 5.0)
            max_ok_distance_mm = params.get("maxOkDistance", 10.0)

            # Get all footprints
            footprints = list(self.board.GetFootprints())

            # Classify
            ics = {}
            caps = {}
            for fp in footprints:
                ref = fp.GetReference()
                if ref.startswith("U") or ref.startswith("IC"):
                    pos = fp.GetPosition()
                    ics[ref] = {
                        "x": pos.x / 1e6,
                        "y": pos.y / 1e6,
                        "footprint": fp,
                    }
                elif ref.startswith("C"):
                    value = fp.GetValue().lower()
                    if self._is_likely_decoupling_cap(value):
                        pos = fp.GetPosition()
                        caps[ref] = {
                            "x": pos.x / 1e6,
                            "y": pos.y / 1e6,
                            "value": fp.GetValue(),
                            "footprint": fp,
                        }

            # Find cap-to-IC associations via shared nets
            associations = []
            for cap_ref, cap_info in caps.items():
                cap_fp = cap_info["footprint"]
                cap_nets = set()
                for pad in cap_fp.Pads():
                    net = pad.GetNet()
                    if net:
                        cap_nets.add(net.GetNetname())

                # Find power nets
                cap_power_nets = set()
                for net_name in cap_nets:
                    nu = net_name.upper().replace(" ", "")
                    if any(p.upper() in nu for p in POWER_PIN_PATTERNS) or \
                       any(p.upper() in nu for p in GROUND_PIN_PATTERNS):
                        cap_power_nets.add(net_name)

                if not cap_power_nets:
                    continue

                # Find closest IC sharing a power net
                best_ic = None
                best_dist = float("inf")
                shared_net = None

                for ic_ref, ic_info in ics.items():
                    ic_fp = ic_info["footprint"]
                    ic_nets = set()
                    for pad in ic_fp.Pads():
                        net = pad.GetNet()
                        if net:
                            ic_nets.add(net.GetNetname())

                    common_power = cap_power_nets & ic_nets
                    if common_power:
                        dist = math.sqrt(
                            (cap_info["x"] - ic_info["x"]) ** 2
                            + (cap_info["y"] - ic_info["y"]) ** 2
                        )
                        if dist < best_dist:
                            best_dist = dist
                            best_ic = ic_ref
                            shared_net = list(common_power)[0]

                if best_ic:
                    if best_dist <= max_good_distance_mm:
                        quality = "good"
                    elif best_dist <= max_ok_distance_mm:
                        quality = "acceptable"
                    else:
                        quality = "too_far"

                    associations.append({
                        "capacitor": cap_ref,
                        "capValue": cap_info["value"],
                        "ic": best_ic,
                        "sharedNet": shared_net,
                        "distance_mm": round(best_dist, 2),
                        "quality": quality,
                        "capPosition": {"x": round(cap_info["x"], 2), "y": round(cap_info["y"], 2)},
                        "icPosition": {"x": round(ics[best_ic]["x"], 2), "y": round(ics[best_ic]["y"], 2)},
                    })

            # Summary
            good = sum(1 for a in associations if a["quality"] == "good")
            ok = sum(1 for a in associations if a["quality"] == "acceptable")
            bad = sum(1 for a in associations if a["quality"] == "too_far")

            return {
                "success": True,
                "message": (
                    f"Analyzed {len(associations)} cap-IC pairs: "
                    f"{good} good, {ok} acceptable, {bad} too far"
                ),
                "associations": associations,
                "summary": {
                    "total": len(associations),
                    "good": good,
                    "acceptable": ok,
                    "tooFar": bad,
                    "maxGoodDistance_mm": max_good_distance_mm,
                    "maxOkDistance_mm": max_ok_distance_mm,
                },
                "recommendations": self._placement_recommendations(associations),
            }

        except Exception as e:
            logger.error(f"Error analyzing decoupling placement: {e}")
            return {"success": False, "message": str(e)}

    # ------------------------------------------------------------------
    # Suggest Decoupling Strategy
    # ------------------------------------------------------------------
    def suggest_decoupling(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Suggest decoupling capacitor values and placement for a component.

        Given an IC reference or type, recommends the decoupling strategy.
        """
        try:
            ic_type = params.get("icType", "").lower()
            num_power_pins = params.get("numPowerPins", 1)
            max_frequency_mhz = params.get("maxFrequency", 100)  # MHz
            supply_voltage = params.get("supplyVoltage", 3.3)

            suggestions = []

            # Base recommendation: 100nF per power pin
            suggestions.append({
                "value": "100nF",
                "quantity": num_power_pins,
                "package": "0402" if num_power_pins > 4 else "0603",
                "placement": f"Within 2mm of each VCC/VDD pin",
                "purpose": "General high-frequency bypass",
                "priority": "required",
            })

            # Bulk cap
            if num_power_pins >= 2:
                suggestions.append({
                    "value": "1uF" if supply_voltage <= 3.3 else "4.7uF",
                    "quantity": max(1, num_power_pins // 4),
                    "package": "0603",
                    "placement": "Within 5mm of IC, shared among power pins",
                    "purpose": "Mid-frequency bulk bypass",
                    "priority": "recommended",
                })

            # High-frequency cap for fast digital
            if max_frequency_mhz > 100:
                suggestions.append({
                    "value": "10nF",
                    "quantity": num_power_pins,
                    "package": "0402",
                    "placement": "As close as physically possible to VCC pin",
                    "purpose": "High-frequency noise suppression",
                    "priority": "recommended",
                })

            if max_frequency_mhz > 500:
                suggestions.append({
                    "value": "1nF" if max_frequency_mhz > 1000 else "2.2nF",
                    "quantity": num_power_pins,
                    "package": "0402",
                    "placement": "Directly adjacent to power pin, same layer",
                    "purpose": "Very-high-frequency bypass (GHz range)",
                    "priority": "recommended",
                })

            # IC-specific suggestions
            ic_specific = self._ic_specific_decoupling(ic_type, supply_voltage)
            if ic_specific:
                suggestions.extend(ic_specific)

            # Board-level bulk (always recommended)
            suggestions.append({
                "value": "10uF",
                "quantity": 1,
                "package": "0805",
                "placement": "Near power entry point of the supply rail",
                "purpose": "Board-level bulk energy storage",
                "priority": "recommended",
            })

            return {
                "success": True,
                "message": f"Decoupling strategy for {ic_type or 'generic IC'} ({num_power_pins} power pins)",
                "suggestions": suggestions,
                "placementRules": {
                    "maxDistance_100nF_mm": 2.0,
                    "maxDistance_bulk_mm": 5.0,
                    "preferSameLayer": True,
                    "viaToGroundPlane": "Use via-in-pad or via within 0.5mm for ground connection",
                    "routingOrder": "Route decoupling caps BEFORE signal traces",
                },
                "frequencyGuide": DECOUPLING_GUIDE,
            }

        except Exception as e:
            logger.error(f"Error suggesting decoupling: {e}")
            return {"success": False, "message": str(e)}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _is_likely_decoupling_cap(self, value: str) -> bool:
        """Check if a capacitor value suggests it's a decoupling/bypass cap."""
        v = value.lower().strip()
        # Match common bypass cap values
        bypass_values = [
            "100n", "0.1u", "100nf", "0.1uf",
            "10n", "10nf", "0.01u", "0.01uf",
            "1u", "1uf",
            "4.7u", "4.7uf", "4u7",
            "10u", "10uf",
            "22n", "22nf", "0.022u",
            "47n", "47nf", "0.047u",
            "2.2n", "2.2nf", "2n2",
            "1n", "1nf",
            "220n", "220nf", "0.22u",
            "470n", "470nf", "0.47u",
        ]
        for bv in bypass_values:
            if bv in v:
                return True
        # Also match if it's just a number followed by nF/uF/pF
        if re.match(r"^\d+\.?\d*\s*(n|u|p)f?$", v):
            return True
        return False

    def _parse_schematic_components(self, content: str) -> List[Dict]:
        """Parse component references and values from schematic S-expression."""
        components = []

        # Match (symbol (lib_id ...) ... (property "Reference" "U1" ...) (property "Value" "STM32" ...))
        # This is a simplified parser for the common patterns
        symbol_blocks = re.finditer(
            r'\(symbol\s+\(lib_id\s+"([^"]+)"\)',
            content,
        )

        for match in symbol_blocks:
            start = match.start()
            # Find the matching closing paren
            depth = 0
            block_end = start
            for i in range(start, min(start + 5000, len(content))):
                if content[i] == "(":
                    depth += 1
                elif content[i] == ")":
                    depth -= 1
                    if depth == 0:
                        block_end = i + 1
                        break

            block = content[start:block_end]

            ref_match = re.search(
                r'\(property\s+"Reference"\s+"([^"]+)"', block
            )
            val_match = re.search(
                r'\(property\s+"Value"\s+"([^"]+)"', block
            )
            pos_match = re.search(
                r'\(at\s+([\d.-]+)\s+([\d.-]+)', block
            )

            if ref_match:
                comp = {
                    "reference": ref_match.group(1),
                    "lib_id": match.group(1),
                    "value": val_match.group(1) if val_match else "",
                }
                if pos_match:
                    comp["position"] = {
                        "x": float(pos_match.group(1)),
                        "y": float(pos_match.group(2)),
                    }
                components.append(comp)

        return components

    def _parse_schematic_nets(self, content: str) -> Dict[str, List[Dict]]:
        """Parse net connections from schematic.

        Returns dict of net_name -> list of {reference, pin} connected to it.
        """
        nets: Dict[str, List[Dict]] = {}

        # Find net labels
        label_pattern = re.compile(
            r'\((?:net_)?label\s+"([^"]+)".*?\(at\s+([\d.-]+)\s+([\d.-]+)',
            re.DOTALL,
        )
        for m in label_pattern.finditer(content):
            net_name = m.group(1)
            if net_name not in nets:
                nets[net_name] = []

        # Find power symbols (they define net names)
        power_pattern = re.compile(
            r'\(symbol\s+\(lib_id\s+"power:([^"]+)"\)',
        )
        for m in power_pattern.finditer(content):
            net_name = m.group(1)
            if net_name not in nets:
                nets[net_name] = []

        # Find global labels
        glabel_pattern = re.compile(
            r'\(global_label\s+"([^"]+)"',
        )
        for m in glabel_pattern.finditer(content):
            net_name = m.group(1)
            if net_name not in nets:
                nets[net_name] = []

        # Find hierarchical labels
        hlabel_pattern = re.compile(
            r'\(hierarchical_label\s+"([^"]+)"',
        )
        for m in hlabel_pattern.finditer(content):
            net_name = m.group(1)
            if net_name not in nets:
                nets[net_name] = []

        return nets

    def _get_component_nets(
        self, reference: str, nets: Dict[str, List[Dict]]
    ) -> List[str]:
        """Get all nets connected to a component (simplified)."""
        connected = []
        for net_name, pins in nets.items():
            for pin in pins:
                if isinstance(pin, dict) and pin.get("reference") == reference:
                    connected.append(net_name)
                    break
        return connected

    def _ic_specific_decoupling(
        self, ic_type: str, supply_voltage: float
    ) -> List[Dict]:
        """Return IC-family-specific decoupling recommendations."""
        suggestions = []

        if not ic_type:
            return suggestions

        ic = ic_type.lower()

        if "stm32" in ic or "stm" in ic:
            suggestions.append({
                "value": "4.7uF",
                "quantity": 1,
                "package": "0603",
                "placement": "Near VCAP pin (if present)",
                "purpose": "STM32 internal regulator output capacitor (check datasheet)",
                "priority": "required",
            })
            suggestions.append({
                "value": "1uF",
                "quantity": 1,
                "package": "0603",
                "placement": "Near VDDA pin",
                "purpose": "Analog supply filtering",
                "priority": "required",
            })

        elif "esp32" in ic or "esp" in ic:
            suggestions.append({
                "value": "10uF",
                "quantity": 2,
                "package": "0805",
                "placement": "Near 3V3 power input",
                "purpose": "ESP32 high transient current during WiFi TX",
                "priority": "required",
            })

        elif "fpga" in ic or "spartan" in ic or "artix" in ic or "zynq" in ic:
            suggestions.append({
                "value": "100nF",
                "quantity": 0,  # placeholder
                "package": "0402",
                "placement": "One per VCC ball/pin, as close as possible",
                "purpose": "FPGA core decoupling (check power design guide)",
                "priority": "required",
                "note": "Follow FPGA vendor power integrity guide for exact quantities",
            })

        elif any(x in ic for x in ["adc", "dac", "codec"]):
            suggestions.append({
                "value": "10uF",
                "quantity": 1,
                "package": "0805",
                "placement": "Near analog supply pin",
                "purpose": "Analog converter power filtering",
                "priority": "required",
            })
            suggestions.append({
                "value": "100nF + 10nF",
                "quantity": 1,
                "package": "0402",
                "placement": "Parallel pair at each AVDD pin",
                "purpose": "Wideband analog noise filtering",
                "priority": "required",
            })

        elif any(x in ic for x in ["ldo", "regulator", "vreg"]):
            suggestions.append({
                "value": "See datasheet",
                "quantity": 1,
                "package": "per datasheet",
                "placement": "At input and output pins per datasheet",
                "purpose": "Regulator stability (ESR and value are critical)",
                "priority": "required",
                "note": "Wrong capacitor value/ESR can cause regulator oscillation",
            })

        return suggestions
