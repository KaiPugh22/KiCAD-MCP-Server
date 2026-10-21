"""
Trace Length Matching

For high-speed interfaces (DDR, USB, HDMI, PCIe) where traces in a bus must
be within a tight length tolerance of each other:
- Measure and report lengths of grouped nets
- Identify which traces need serpentine/meander tuning
- Auto-add serpentine meanders to short traces
- Support grouping by bus (DDR data, address, clock, etc.)
"""

import math
import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Common bus definitions with length matching requirements
BUS_DEFINITIONS = {
    "usb2": {
        "signal_nets": ["D+", "D-", "DP", "DM", "USB_D+", "USB_D-"],
        "tolerance_mm": 2.0,
        "description": "USB 2.0 differential pair",
    },
    "usb3_tx": {
        "signal_nets": ["SSTX+", "SSTX-", "USB3_TX+", "USB3_TX-"],
        "tolerance_mm": 1.0,
        "description": "USB 3.0 TX pair",
    },
    "usb3_rx": {
        "signal_nets": ["SSRX+", "SSRX-", "USB3_RX+", "USB3_RX-"],
        "tolerance_mm": 1.0,
        "description": "USB 3.0 RX pair",
    },
    "ddr_data": {
        "signal_nets": ["DQ0", "DQ1", "DQ2", "DQ3", "DQ4", "DQ5", "DQ6", "DQ7",
                        "DQ8", "DQ9", "DQ10", "DQ11", "DQ12", "DQ13", "DQ14", "DQ15"],
        "tolerance_mm": 2.5,
        "description": "DDR data bus (per byte lane)",
    },
    "ddr_addr": {
        "signal_nets": ["A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7",
                        "A8", "A9", "A10", "A11", "A12", "A13", "A14", "A15",
                        "BA0", "BA1", "BA2"],
        "tolerance_mm": 5.0,
        "description": "DDR address/command bus",
    },
    "hdmi_tmds": {
        "signal_nets": ["TMDS0+", "TMDS0-", "TMDS1+", "TMDS1-",
                        "TMDS2+", "TMDS2-", "TMDS_CLK+", "TMDS_CLK-"],
        "tolerance_mm": 2.0,
        "description": "HDMI TMDS lanes",
    },
    "ethernet_tx": {
        "signal_nets": ["TX+", "TX-", "ETH_TX+", "ETH_TX-", "TD+", "TD-"],
        "tolerance_mm": 2.5,
        "description": "Ethernet TX pair",
    },
    "ethernet_rx": {
        "signal_nets": ["RX+", "RX-", "ETH_RX+", "ETH_RX-", "RD+", "RD-"],
        "tolerance_mm": 2.5,
        "description": "Ethernet RX pair",
    },
}


class LengthMatchingCommands:
    def __init__(self, board=None):
        self.board = board

    def set_board(self, board):
        self.board = board

    def measure_net_lengths(self, net_names: List[str]) -> Dict[str, Any]:
        """
        Measure the total routed trace length for a group of nets.

        Args:
            net_names: List of net names to measure
        """
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        try:
            import pcbnew
            board = self.board

            results = []
            for net_name in net_names:
                total_length = 0.0
                segment_count = 0
                via_count = 0
                layers_used = set()

                for t in board.GetTracks():
                    if t.GetNetname() != net_name:
                        continue

                    if isinstance(t, pcbnew.PCB_VIA):
                        via_count += 1
                        continue

                    if isinstance(t, pcbnew.PCB_TRACK):
                        sx = pcbnew.ToMM(t.GetStart().x)
                        sy = pcbnew.ToMM(t.GetStart().y)
                        ex = pcbnew.ToMM(t.GetEnd().x)
                        ey = pcbnew.ToMM(t.GetEnd().y)
                        seg_len = math.sqrt((ex - sx) ** 2 + (ey - sy) ** 2)
                        total_length += seg_len
                        segment_count += 1
                        layers_used.add(board.GetLayerName(t.GetLayer()))

                results.append({
                    "net": net_name,
                    "length_mm": round(total_length, 3),
                    "segments": segment_count,
                    "vias": via_count,
                    "layers": list(layers_used),
                    "routed": segment_count > 0,
                })

            # Calculate statistics
            routed = [r for r in results if r["routed"]]
            if routed:
                lengths = [r["length_mm"] for r in routed]
                max_len = max(lengths)
                min_len = min(lengths)
                avg_len = sum(lengths) / len(lengths)
                spread = max_len - min_len
            else:
                max_len = min_len = avg_len = spread = 0

            return {
                "success": True,
                "nets": results,
                "statistics": {
                    "max_length_mm": round(max_len, 3),
                    "min_length_mm": round(min_len, 3),
                    "average_length_mm": round(avg_len, 3),
                    "spread_mm": round(spread, 3),
                    "routed_count": len(routed),
                    "total_count": len(results),
                },
            }

        except Exception as e:
            logger.error(f"Measure net lengths failed: {e}")
            return {"success": False, "error": str(e)}

    def check_length_matching(self, net_names: List[str],
                              tolerance_mm: float = 2.0,
                              reference_net: Optional[str] = None) -> Dict[str, Any]:
        """
        Check if a group of nets are length-matched within tolerance.

        Args:
            net_names: Nets that should be length-matched
            tolerance_mm: Maximum allowed length difference
            reference_net: Net to match against (default: longest net)
        """
        measurement = self.measure_net_lengths(net_names)
        if not measurement.get("success"):
            return measurement

        nets = measurement["nets"]
        routed = [n for n in nets if n["routed"]]

        if not routed:
            return {"success": False, "error": "None of the specified nets are routed"}

        # Determine reference length
        if reference_net:
            ref = next((n for n in routed if n["net"] == reference_net), None)
            if not ref:
                return {"success": False, "error": f"Reference net '{reference_net}' not found or not routed"}
            ref_length = ref["length_mm"]
        else:
            ref_length = max(n["length_mm"] for n in routed)

        # Check each net against reference
        results = []
        all_pass = True
        for net_info in routed:
            delta = net_info["length_mm"] - ref_length
            passes = abs(delta) <= tolerance_mm
            if not passes:
                all_pass = False

            needed_meander = max(0, -delta)

            results.append({
                "net": net_info["net"],
                "length_mm": net_info["length_mm"],
                "delta_mm": round(delta, 3),
                "abs_delta_mm": round(abs(delta), 3),
                "passes": passes,
                "meander_needed_mm": round(needed_meander, 3),
            })

        # Sort by delta (shortest first — needs most meander)
        results.sort(key=lambda x: x["delta_mm"])

        return {
            "success": True,
            "reference_length_mm": round(ref_length, 3),
            "tolerance_mm": tolerance_mm,
            "all_pass": all_pass,
            "nets": results,
            "summary": {
                "passing": sum(1 for r in results if r["passes"]),
                "failing": sum(1 for r in results if not r["passes"]),
                "max_delta_mm": round(max(abs(r["delta_mm"]) for r in results), 3),
            },
        }

    def auto_detect_bus_groups(self) -> Dict[str, Any]:
        """
        Auto-detect bus groups on the board by matching net names against
        known bus patterns (DDR, USB, HDMI, Ethernet, etc.).
        """
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        try:
            import pcbnew
            board = self.board

            # Collect all net names
            all_nets = set()
            netinfo = board.GetNetInfo()
            for i in range(board.GetNetCount()):
                net = netinfo.GetNetItem(i)
                if net and net.GetNetname():
                    all_nets.add(net.GetNetname())

            detected_groups = []
            for bus_key, bus_def in BUS_DEFINITIONS.items():
                matching_nets = []
                for pattern in bus_def["signal_nets"]:
                    # Check exact match and common prefixed variants
                    for net in all_nets:
                        net_upper = net.upper().replace("-", "").replace("_", "")
                        pattern_upper = pattern.upper().replace("-", "").replace("_", "")
                        if pattern_upper in net_upper or net_upper.endswith(pattern_upper):
                            matching_nets.append(net)

                if len(matching_nets) >= 2:
                    detected_groups.append({
                        "bus": bus_key,
                        "description": bus_def["description"],
                        "nets": sorted(set(matching_nets)),
                        "net_count": len(set(matching_nets)),
                        "tolerance_mm": bus_def["tolerance_mm"],
                    })

            return {
                "success": True,
                "detected_groups": detected_groups,
                "total_groups": len(detected_groups),
                "total_board_nets": len(all_nets),
                "message": f"Detected {len(detected_groups)} bus groups requiring length matching"
                          if detected_groups else "No known bus patterns detected in net names",
            }

        except Exception as e:
            logger.error(f"Auto-detect bus groups failed: {e}")
            return {"success": False, "error": str(e)}

    def add_serpentine(self, net_name: str, target_length_mm: float,
                      amplitude_mm: float = 0.5,
                      segment_length_mm: float = 1.0,
                      layer: str = "F.Cu") -> Dict[str, Any]:
        """
        Add serpentine/meander tuning to a trace to increase its length.

        Finds the longest straight segment on the net and adds a serpentine
        pattern to extend it to the target length.

        Args:
            net_name: Net to add serpentine to
            target_length_mm: Desired total net length after tuning
            amplitude_mm: Serpentine peak-to-peak amplitude in mm
            segment_length_mm: Length of each serpentine segment
            layer: Layer to add serpentine on
        """
        if not self.board:
            return {"success": False, "error": "No board loaded"}

        try:
            import pcbnew
            board = self.board

            # Measure current length
            current_length = 0
            longest_seg = None
            longest_seg_len = 0
            track_width = 0.2  # default

            for t in board.GetTracks():
                if t.GetNetname() != net_name:
                    continue
                if isinstance(t, pcbnew.PCB_VIA):
                    continue
                if not isinstance(t, pcbnew.PCB_TRACK):
                    continue

                sx = pcbnew.ToMM(t.GetStart().x)
                sy = pcbnew.ToMM(t.GetStart().y)
                ex = pcbnew.ToMM(t.GetEnd().x)
                ey = pcbnew.ToMM(t.GetEnd().y)
                seg_len = math.sqrt((ex - sx) ** 2 + (ey - sy) ** 2)
                current_length += seg_len
                track_width = pcbnew.ToMM(t.GetWidth())

                if seg_len > longest_seg_len and board.GetLayerName(t.GetLayer()) == layer:
                    longest_seg_len = seg_len
                    longest_seg = t

            if not longest_seg:
                return {"success": False, "error": f"No tracks found for net '{net_name}' on {layer}"}

            needed = target_length_mm - current_length
            if needed <= 0:
                return {
                    "success": True,
                    "message": f"Net already at {current_length:.2f}mm (target {target_length_mm}mm), no tuning needed",
                    "current_length_mm": round(current_length, 3),
                }

            # Calculate serpentine parameters
            # Each meander adds approximately 2 * amplitude of extra length
            meander_extra = 2 * amplitude_mm  # per period
            num_meanders = max(1, int(math.ceil(needed / meander_extra)))

            # Generate serpentine along the longest segment
            sx = pcbnew.ToMM(longest_seg.GetStart().x)
            sy = pcbnew.ToMM(longest_seg.GetStart().y)
            ex = pcbnew.ToMM(longest_seg.GetEnd().x)
            ey = pcbnew.ToMM(longest_seg.GetEnd().y)

            # Direction vector along the trace
            dx = ex - sx
            dy = ey - sy
            seg_len = math.sqrt(dx * dx + dy * dy)
            if seg_len == 0:
                return {"success": False, "error": "Longest segment has zero length"}

            ux = dx / seg_len  # unit vector along trace
            uy = dy / seg_len
            nx = -uy  # perpendicular (normal)
            ny = ux

            # Place serpentine in the middle of the segment
            total_serpentine_length = num_meanders * segment_length_mm
            if total_serpentine_length > seg_len * 0.8:
                total_serpentine_length = seg_len * 0.8
                num_meanders = max(1, int(total_serpentine_length / segment_length_mm))

            start_offset = (seg_len - total_serpentine_length) / 2

            # Remove the original long segment
            board.Remove(longest_seg)

            layer_id = board.GetLayerID(layer)
            net_item = board.GetNetInfo().GetNetItem(net_name)
            created_tracks = []

            # Lead-in segment
            lead_in_end_x = sx + ux * start_offset
            lead_in_end_y = sy + uy * start_offset
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(pcbnew.VECTOR2I(int(pcbnew.FromMM(sx)), int(pcbnew.FromMM(sy))))
            t.SetEnd(pcbnew.VECTOR2I(int(pcbnew.FromMM(lead_in_end_x)), int(pcbnew.FromMM(lead_in_end_y))))
            t.SetWidth(int(pcbnew.FromMM(track_width)))
            t.SetLayer(layer_id)
            if net_item:
                t.SetNet(net_item)
            board.Add(t)
            created_tracks.append(t)

            # Serpentine meanders
            cur_x = lead_in_end_x
            cur_y = lead_in_end_y

            for i in range(num_meanders):
                direction = 1 if i % 2 == 0 else -1
                half_seg = segment_length_mm / 2

                # Go perpendicular
                mid_x = cur_x + nx * amplitude_mm * direction
                mid_y = cur_y + ny * amplitude_mm * direction

                t1 = pcbnew.PCB_TRACK(board)
                t1.SetStart(pcbnew.VECTOR2I(int(pcbnew.FromMM(cur_x)), int(pcbnew.FromMM(cur_y))))
                t1.SetEnd(pcbnew.VECTOR2I(int(pcbnew.FromMM(mid_x)), int(pcbnew.FromMM(mid_y))))
                t1.SetWidth(int(pcbnew.FromMM(track_width)))
                t1.SetLayer(layer_id)
                if net_item:
                    t1.SetNet(net_item)
                board.Add(t1)
                created_tracks.append(t1)

                # Go forward
                fwd_x = mid_x + ux * half_seg
                fwd_y = mid_y + uy * half_seg

                t2 = pcbnew.PCB_TRACK(board)
                t2.SetStart(pcbnew.VECTOR2I(int(pcbnew.FromMM(mid_x)), int(pcbnew.FromMM(mid_y))))
                t2.SetEnd(pcbnew.VECTOR2I(int(pcbnew.FromMM(fwd_x)), int(pcbnew.FromMM(fwd_y))))
                t2.SetWidth(int(pcbnew.FromMM(track_width)))
                t2.SetLayer(layer_id)
                if net_item:
                    t2.SetNet(net_item)
                board.Add(t2)
                created_tracks.append(t2)

                # Return perpendicular
                next_x = fwd_x - nx * amplitude_mm * direction
                next_y = fwd_y - ny * amplitude_mm * direction

                t3 = pcbnew.PCB_TRACK(board)
                t3.SetStart(pcbnew.VECTOR2I(int(pcbnew.FromMM(fwd_x)), int(pcbnew.FromMM(fwd_y))))
                t3.SetEnd(pcbnew.VECTOR2I(int(pcbnew.FromMM(next_x)), int(pcbnew.FromMM(next_y))))
                t3.SetWidth(int(pcbnew.FromMM(track_width)))
                t3.SetLayer(layer_id)
                if net_item:
                    t3.SetNet(net_item)
                board.Add(t3)
                created_tracks.append(t3)

                cur_x = next_x
                cur_y = next_y

            # Lead-out segment
            t_out = pcbnew.PCB_TRACK(board)
            t_out.SetStart(pcbnew.VECTOR2I(int(pcbnew.FromMM(cur_x)), int(pcbnew.FromMM(cur_y))))
            t_out.SetEnd(pcbnew.VECTOR2I(int(pcbnew.FromMM(ex)), int(pcbnew.FromMM(ey))))
            t_out.SetWidth(int(pcbnew.FromMM(track_width)))
            t_out.SetLayer(layer_id)
            if net_item:
                t_out.SetNet(net_item)
            board.Add(t_out)
            created_tracks.append(t_out)

            pcbnew.Refresh()

            # Measure new length
            new_length = 0
            for t in board.GetTracks():
                if t.GetNetname() == net_name and isinstance(t, pcbnew.PCB_TRACK) and not isinstance(t, pcbnew.PCB_VIA):
                    s = t.GetStart()
                    e = t.GetEnd()
                    new_length += math.sqrt(
                        (pcbnew.ToMM(e.x) - pcbnew.ToMM(s.x)) ** 2 +
                        (pcbnew.ToMM(e.y) - pcbnew.ToMM(s.y)) ** 2
                    )

            return {
                "success": True,
                "message": f"Added {num_meanders} serpentine meanders to '{net_name}'",
                "previous_length_mm": round(current_length, 3),
                "new_length_mm": round(new_length, 3),
                "target_length_mm": target_length_mm,
                "segments_added": len(created_tracks),
                "meander_count": num_meanders,
                "amplitude_mm": amplitude_mm,
            }

        except Exception as e:
            logger.error(f"Add serpentine failed: {e}")
            return {"success": False, "error": str(e)}
