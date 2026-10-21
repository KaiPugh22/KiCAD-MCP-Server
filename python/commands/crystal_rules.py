"""
Crystal/Oscillator Layout Rule Enforcer for KiCAD MCP Server.

Checks and enforces layout rules around crystals and oscillators:
- Keep-out zone verification (no signal traces under crystal)
- Guard ring presence
- Load capacitor placement distance
- Ground via placement
"""

import math
import logging
from typing import Dict, Any, List, Tuple, Optional

logger = logging.getLogger("kicad_interface")

CRYSTAL_REF_PREFIXES = ["Y", "X", "XTAL"]
LOAD_CAP_MAX_DISTANCE_MM = 5.0
KEEPOUT_MARGIN_MM = 1.0


class CrystalRulesCommands:
    def __init__(self, board=None):
        self.board = board

    def audit_crystal_layout(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Audit all crystal/oscillator layouts on the board."""
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        try:
            import pcbnew
        except ImportError:
            return {"success": False, "error": "pcbnew not available"}

        max_cap_distance_mm = params.get("max_cap_distance_mm", LOAD_CAP_MAX_DISTANCE_MM)
        keepout_margin_mm = params.get("keepout_margin_mm", KEEPOUT_MARGIN_MM)

        crystals = []
        for fp in self.board.GetFootprints():
            ref = fp.GetReference()
            prefix = ''.join(c for c in ref if c.isalpha()).upper()
            value = fp.GetValue().upper()

            is_crystal = (prefix in CRYSTAL_REF_PREFIXES or
                          any(kw in value for kw in ["CRYSTAL", "XTAL", "OSC", "OSCILLATOR",
                                                     "MHZ", "KHZ"]))
            if is_crystal:
                crystals.append(fp)

        if not crystals:
            return {
                "success": True,
                "crystal_count": 0,
                "message": "No crystals/oscillators found on the board.",
            }

        results = []
        for crystal in crystals:
            ref = crystal.GetReference()
            pos = crystal.GetPosition()
            cx = pos.x / 1e6
            cy = pos.y / 1e6
            bb = crystal.GetBoundingBox()
            cw = bb.GetWidth() / 1e6
            ch = bb.GetHeight() / 1e6

            issues = []
            info = {
                "reference": ref,
                "value": crystal.GetValue(),
                "position_mm": {"x": round(cx, 2), "y": round(cy, 2)},
                "size_mm": {"w": round(cw, 2), "h": round(ch, 2)},
            }

            crystal_nets = set()
            for pad in crystal.Pads():
                net = pad.GetNet()
                if net and net.GetNetname():
                    crystal_nets.add(net.GetNetname())

            mcu_ref = self._find_connected_mcu(crystal_nets)
            info["connected_mcu"] = mcu_ref

            if mcu_ref:
                mcu_fp = None
                for fp in self.board.GetFootprints():
                    if fp.GetReference() == mcu_ref:
                        mcu_fp = fp
                        break
                if mcu_fp:
                    mcu_pos = mcu_fp.GetPosition()
                    dist = math.sqrt((pos.x - mcu_pos.x)**2 + (pos.y - mcu_pos.y)**2) / 1e6
                    info["mcu_distance_mm"] = round(dist, 2)
                    if dist > 15:
                        issues.append({
                            "type": "too_far_from_mcu",
                            "severity": "high",
                            "detail": f"Crystal is {round(dist, 1)}mm from {mcu_ref}, should be < 15mm",
                            "fix": f"Move {ref} closer to {mcu_ref}",
                        })

            load_caps = self._find_load_caps(crystal_nets, ref, max_cap_distance_mm)
            info["load_caps"] = load_caps

            for cap in load_caps:
                if cap["distance_mm"] > max_cap_distance_mm:
                    issues.append({
                        "type": "load_cap_too_far",
                        "severity": "medium",
                        "detail": f"Load cap {cap['ref']} is {cap['distance_mm']}mm away, max {max_cap_distance_mm}mm",
                        "fix": f"Move {cap['ref']} within {max_cap_distance_mm}mm of {ref}",
                    })

            if len(load_caps) == 0:
                issues.append({
                    "type": "missing_load_caps",
                    "severity": "high",
                    "detail": "No load capacitors found on crystal nets",
                    "fix": "Add load caps (typically 12-22pF) on each crystal pin to GND",
                })

            traces_under = self._check_traces_under(crystal, keepout_margin_mm, crystal_nets)
            info["traces_under_crystal"] = len(traces_under)
            for trace_info in traces_under:
                issues.append({
                    "type": "trace_under_crystal",
                    "severity": "high",
                    "detail": f"Signal trace ({trace_info['net']}) routes under crystal on {trace_info['layer']}",
                    "fix": "Reroute trace around the crystal keep-out zone",
                })

            gnd_vias_nearby = self._count_nearby_gnd_vias(pos.x, pos.y, cw * 1e6, ch * 1e6)
            info["nearby_gnd_vias"] = gnd_vias_nearby
            if gnd_vias_nearby == 0:
                issues.append({
                    "type": "no_ground_vias",
                    "severity": "medium",
                    "detail": "No GND vias near crystal for solid return path",
                    "fix": "Add GND vias around the crystal perimeter",
                })

            guard_ring = self._check_guard_ring(pos.x, pos.y, cw * 1e6, ch * 1e6)
            info["has_guard_ring"] = guard_ring
            if not guard_ring:
                issues.append({
                    "type": "no_guard_ring",
                    "severity": "low",
                    "detail": "No guard ring/pour around crystal",
                    "fix": "Add GND guard ring or copper pour around crystal area",
                })

            info["issues"] = issues
            info["issue_count"] = len(issues)
            info["pass"] = len(issues) == 0
            results.append(info)

        total_issues = sum(r["issue_count"] for r in results)
        return {
            "success": True,
            "crystal_count": len(results),
            "total_issues": total_issues,
            "all_pass": total_issues == 0,
            "crystals": results,
        }

    def _find_connected_mcu(self, crystal_nets: set) -> Optional[str]:
        """Find the MCU connected to the crystal nets."""
        mcu_keywords = ["STM32", "ESP32", "ATMEL", "PIC", "NRF", "RP2040",
                        "SAMD", "EFM32", "GD32", "CH32", "MCU", "CPU"]
        for fp in self.board.GetFootprints():
            value = fp.GetValue().upper()
            ref = fp.GetReference()
            if not ref.startswith("U"):
                continue

            is_mcu = any(kw in value for kw in mcu_keywords) or len(list(fp.Pads())) >= 20

            if is_mcu:
                for pad in fp.Pads():
                    net = pad.GetNet()
                    if net and net.GetNetname() in crystal_nets:
                        return ref
        return None

    def _find_load_caps(self, crystal_nets: set, crystal_ref: str, max_dist: float) -> List[Dict]:
        """Find capacitors connected to crystal nets (load caps)."""
        caps = []
        crystal_fp = None
        for fp in self.board.GetFootprints():
            if fp.GetReference() == crystal_ref:
                crystal_fp = fp
                break
        if not crystal_fp:
            return caps

        crystal_pos = crystal_fp.GetPosition()

        for fp in self.board.GetFootprints():
            ref = fp.GetReference()
            if not ref.startswith("C"):
                continue
            if ref == crystal_ref:
                continue

            has_crystal_net = False
            has_gnd = False
            for pad in fp.Pads():
                net = pad.GetNet()
                if net:
                    name = net.GetNetname()
                    if name in crystal_nets:
                        has_crystal_net = True
                    if name and "GND" in name.upper():
                        has_gnd = True

            if has_crystal_net and has_gnd:
                fp_pos = fp.GetPosition()
                dist = math.sqrt((crystal_pos.x - fp_pos.x)**2 +
                                 (crystal_pos.y - fp_pos.y)**2) / 1e6
                caps.append({
                    "ref": ref,
                    "value": fp.GetValue(),
                    "distance_mm": round(dist, 2),
                })

        caps.sort(key=lambda c: c["distance_mm"])
        return caps

    def _check_traces_under(self, crystal_fp, margin_mm, crystal_nets) -> List[Dict]:
        """Check for non-crystal signal traces routing under the crystal."""
        bb = crystal_fp.GetBoundingBox()
        margin = int(margin_mm * 1e6)
        kx1 = bb.GetX() - margin
        ky1 = bb.GetY() - margin
        kx2 = bb.GetX() + bb.GetWidth() + margin
        ky2 = bb.GetY() + bb.GetHeight() + margin

        violations = []
        for track in self.board.GetTracks():
            if not hasattr(track, 'GetStart'):
                continue
            net = track.GetNet()
            if not net:
                continue
            net_name = net.GetNetname()
            if not net_name or net_name in crystal_nets:
                continue
            if "GND" in net_name.upper():
                continue

            start = track.GetStart()
            end = track.GetEnd()

            if self._segment_intersects_rect(start.x, start.y, end.x, end.y,
                                              kx1, ky1, kx2, ky2):
                layer_name = self.board.GetLayerName(track.GetLayer())
                violations.append({
                    "net": net_name,
                    "layer": layer_name,
                })

        return violations[:10]

    def _segment_intersects_rect(self, sx, sy, ex, ey, rx1, ry1, rx2, ry2) -> bool:
        """Check if a line segment intersects a rectangle."""
        if (min(sx, ex) > rx2 or max(sx, ex) < rx1 or
                min(sy, ey) > ry2 or max(sy, ey) < ry1):
            return False

        if rx1 <= sx <= rx2 and ry1 <= sy <= ry2:
            return True
        if rx1 <= ex <= rx2 and ry1 <= ey <= ry2:
            return True

        return True

    def _count_nearby_gnd_vias(self, cx, cy, cw, ch) -> int:
        """Count GND vias near the crystal."""
        search_radius = max(cw, ch) + int(2e6)
        count = 0
        for track in self.board.GetTracks():
            if hasattr(track, 'GetViaType') or track.GetClass() == "PCB_VIA":
                net = track.GetNet()
                if net and "GND" in net.GetNetname().upper():
                    pos = track.GetPosition()
                    dist = math.sqrt((pos.x - cx)**2 + (pos.y - cy)**2)
                    if dist <= search_radius:
                        count += 1
        return count

    def _check_guard_ring(self, cx, cy, cw, ch) -> bool:
        """Check if there's a GND zone/pour surrounding the crystal."""
        search_radius = max(cw, ch) + int(3e6)
        for zone in self.board.Zones():
            net = zone.GetNet()
            if not net or "GND" not in net.GetNetname().upper():
                continue
            zbb = zone.GetBoundingBox()
            zx1 = zbb.GetX()
            zy1 = zbb.GetY()
            zx2 = zx1 + zbb.GetWidth()
            zy2 = zy1 + zbb.GetHeight()

            if (zx1 <= cx - cw // 2 and zx2 >= cx + cw // 2 and
                    zy1 <= cy - ch // 2 and zy2 >= cy + ch // 2):
                return True
        return False
