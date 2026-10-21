"""
Routing-related command implementations for KiCAD interface
"""

import os
import pcbnew
import logging
import math
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger("kicad_interface")


class RoutingCommands:
    """Handles routing-related KiCAD operations"""

    def __init__(self, board: Optional[pcbnew.BOARD] = None):
        """Initialize with optional board instance"""
        self.board = board

    def add_net(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a new net to the PCB"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            name = params.get("name")
            net_class = params.get("class")

            if not name:
                return {
                    "success": False,
                    "message": "Missing net name",
                    "errorDetails": "name parameter is required",
                }

            # Create new net
            netinfo = self.board.GetNetInfo()
            nets_map = netinfo.NetsByName()
            if nets_map.has_key(name):
                net = nets_map[name]
            else:
                net = pcbnew.NETINFO_ITEM(self.board, name)
                self.board.Add(net)

            # Set net class if provided
            if net_class:
                net_classes = self.board.GetNetClasses()
                if net_classes.Find(net_class):
                    net.SetClass(net_classes.Find(net_class))

            return {
                "success": True,
                "message": f"Added net: {name}",
                "net": {
                    "name": name,
                    "class": net_class if net_class else "Default",
                    "netcode": net.GetNetCode(),
                },
            }

        except Exception as e:
            logger.error(f"Error adding net: {str(e)}")
            return {
                "success": False,
                "message": "Failed to add net",
                "errorDetails": str(e),
            }

    def route_pad_to_pad(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Route a trace directly from one component pad to another.

        Looks up pad positions automatically, then creates a trace.
        Convenience wrapper around route_trace that eliminates the need
        for separate get_pad_position calls.
        """
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            from_ref = params.get("fromRef")
            from_pad = str(params.get("fromPad", ""))
            to_ref = params.get("toRef")
            to_pad = str(params.get("toPad", ""))
            layer = params.get("layer", "F.Cu")
            width = params.get("width")
            net = params.get("net")  # optional override

            if not from_ref or not from_pad or not to_ref or not to_pad:
                return {
                    "success": False,
                    "message": "Missing parameters",
                    "errorDetails": "fromRef, fromPad, toRef, toPad are all required",
                }

            scale = 1000000  # nm to mm

            # Find pads
            footprints = {fp.GetReference(): fp for fp in self.board.GetFootprints()}

            for ref in [from_ref, to_ref]:
                if ref not in footprints:
                    return {
                        "success": False,
                        "message": f"Component not found: {ref}",
                        "errorDetails": f"'{ref}' does not exist on the board",
                    }

            def find_pad(ref: str, pad_num: str):
                fp = footprints[ref]
                for pad in fp.Pads():
                    if pad.GetNumber() == pad_num:
                        return pad
                return None

            start_pad = find_pad(from_ref, from_pad)
            end_pad = find_pad(to_ref, to_pad)

            if not start_pad:
                return {
                    "success": False,
                    "message": f"Pad not found: {from_ref} pad {from_pad}",
                    "errorDetails": f"Check pad number for {from_ref}",
                }
            if not end_pad:
                return {
                    "success": False,
                    "message": f"Pad not found: {to_ref} pad {to_pad}",
                    "errorDetails": f"Check pad number for {to_ref}",
                }

            start_pos = start_pad.GetPosition()
            end_pos = end_pad.GetPosition()

            # Use net from start pad if not overridden
            if not net:
                net = start_pad.GetNetname() or end_pad.GetNetname() or ""

            # Detect if pads are on different copper layers → need via.
            # SMD pad.GetLayer() reports F.Cu even on flipped B.Cu footprints in
            # KiCAD 9 SWIG. Use footprint.GetLayer() instead — it always reflects
            # the actual placed layer after Flip().
            fp_start = footprints[from_ref]
            fp_end   = footprints[to_ref]
            start_layer = self.board.GetLayerName(fp_start.GetLayer())
            end_layer   = self.board.GetLayerName(fp_end.GetLayer())
            copper_layers = {"F.Cu", "B.Cu"}
            needs_via = (
                start_layer in copper_layers
                and end_layer in copper_layers
                and start_layer != end_layer
            )

            if needs_via:
                # Place via directly below the start pad (same X).
                # Using the geometric midpoint X causes all vias to stack at
                # the same X when pads are back-to-back mirrored (e.g. J1/J2
                # on F.Cu/B.Cu): midpoint is always the board center.
                via_x = start_pos.x / scale
                via_y = (start_pos.y + end_pos.y) / 2 / scale

                # Trace on start layer: start_pad → via
                r1 = self.route_trace({
                    "start": {"x": start_pos.x / scale, "y": start_pos.y / scale, "unit": "mm"},
                    "end":   {"x": via_x, "y": via_y, "unit": "mm"},
                    "layer": start_layer, "width": width, "net": net,
                })
                # Via connecting both layers
                self.add_via({
                    "position": {"x": via_x, "y": via_y, "unit": "mm"},
                    "net": net,
                    "from_layer": start_layer,
                    "to_layer": end_layer,
                })
                # Trace on end layer: via → end_pad
                r2 = self.route_trace({
                    "start": {"x": via_x, "y": via_y, "unit": "mm"},
                    "end":   {"x": end_pos.x / scale, "y": end_pos.y / scale, "unit": "mm"},
                    "layer": end_layer, "width": width, "net": net,
                })
                success = r1.get("success") and r2.get("success")
                result = {
                    "success": success,
                    "message": f"Routed {from_ref}.{from_pad} → via → {to_ref}.{to_pad} (net: {net}, via at {via_x:.2f},{via_y:.2f})",
                    "via_added": True,
                    "via_position": {"x": via_x, "y": via_y},
                }
            else:
                # Same layer — direct trace
                result = self.route_trace({
                    "start": {"x": start_pos.x / scale, "y": start_pos.y / scale, "unit": "mm"},
                    "end":   {"x": end_pos.x / scale, "y": end_pos.y / scale, "unit": "mm"},
                    "layer": layer if layer else start_layer,
                    "width": width, "net": net,
                })

            if result.get("success"):
                result["fromPad"] = {
                    "ref": from_ref, "pad": from_pad,
                    "x": start_pos.x / scale, "y": start_pos.y / scale,
                }
                result["toPad"] = {
                    "ref": to_ref, "pad": to_pad,
                    "x": end_pos.x / scale, "y": end_pos.y / scale,
                }

            return result

        except Exception as e:
            logger.error(f"Error in route_pad_to_pad: {str(e)}")
            return {
                "success": False,
                "message": "Failed to route pad to pad",
                "errorDetails": str(e),
            }

    def route_trace(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Route a trace between two points or pads"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            start = params.get("start")
            end = params.get("end")
            layer = params.get("layer", "F.Cu")
            width = params.get("width")
            net = params.get("net")
            via = params.get("via", False)

            if not start or not end:
                return {
                    "success": False,
                    "message": "Missing parameters",
                    "errorDetails": "start and end points are required",
                }

            # Get layer ID
            layer_id = self.board.GetLayerID(layer)
            if layer_id < 0:
                return {
                    "success": False,
                    "message": "Invalid layer",
                    "errorDetails": f"Layer '{layer}' does not exist",
                }

            # Get start point
            start_point = self._get_point(start)
            end_point = self._get_point(end)

            # Create track segment
            track = pcbnew.PCB_TRACK(self.board)
            track.SetStart(start_point)
            track.SetEnd(end_point)
            track.SetLayer(layer_id)

            # Set width (default to board's current track width)
            if width:
                track.SetWidth(int(width * 1000000))  # Convert mm to nm
            else:
                track.SetWidth(self.board.GetDesignSettings().GetCurrentTrackWidth())

            # Set net if provided
            if net:
                netinfo = self.board.GetNetInfo()
                nets_map = netinfo.NetsByName()
                if nets_map.has_key(net):
                    net_obj = nets_map[net]
                    track.SetNet(net_obj)

            # Add track to board
            self.board.Add(track)

            # Add via if requested and net is specified
            if via and net:
                via_point = end_point
                self.add_via(
                    {
                        "position": {
                            "x": via_point.x / 1000000,
                            "y": via_point.y / 1000000,
                            "unit": "mm",
                        },
                        "net": net,
                    }
                )

            return {
                "success": True,
                "message": "Added trace",
                "trace": {
                    "start": {
                        "x": start_point.x / 1000000,
                        "y": start_point.y / 1000000,
                        "unit": "mm",
                    },
                    "end": {
                        "x": end_point.x / 1000000,
                        "y": end_point.y / 1000000,
                        "unit": "mm",
                    },
                    "layer": layer,
                    "width": track.GetWidth() / 1000000,
                    "net": net,
                },
            }

        except Exception as e:
            logger.error(f"Error routing trace: {str(e)}")
            return {
                "success": False,
                "message": "Failed to route trace",
                "errorDetails": str(e),
            }

    def add_via(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a via at the specified location"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            position = params.get("position")
            size = params.get("size")
            drill = params.get("drill")
            net = params.get("net")
            from_layer = params.get("from_layer", "F.Cu")
            to_layer = params.get("to_layer", "B.Cu")

            if not position:
                return {
                    "success": False,
                    "message": "Missing position",
                    "errorDetails": "position parameter is required",
                }

            # Create via
            via = pcbnew.PCB_VIA(self.board)

            # Set position
            scale = (
                1000000 if position["unit"] == "mm" else 25400000
            )  # mm or inch to nm
            x_nm = int(position["x"] * scale)
            y_nm = int(position["y"] * scale)
            via.SetPosition(pcbnew.VECTOR2I(x_nm, y_nm))

            # Set size and drill (default to board's current via settings)
            design_settings = self.board.GetDesignSettings()
            via.SetWidth(
                int(size * 1000000) if size else design_settings.GetCurrentViaSize()
            )
            via.SetDrill(
                int(drill * 1000000) if drill else design_settings.GetCurrentViaDrill()
            )

            # Set layers
            from_id = self.board.GetLayerID(from_layer)
            to_id = self.board.GetLayerID(to_layer)
            if from_id < 0 or to_id < 0:
                return {
                    "success": False,
                    "message": "Invalid layer",
                    "errorDetails": "Specified layers do not exist",
                }
            via.SetLayerPair(from_id, to_id)

            # Set net if provided
            if net:
                netinfo = self.board.GetNetInfo()
                nets_map = netinfo.NetsByName()
                if nets_map.has_key(net):
                    net_obj = nets_map[net]
                    via.SetNet(net_obj)

            # Add via to board
            self.board.Add(via)

            return {
                "success": True,
                "message": "Added via",
                "via": {
                    "position": {
                        "x": position["x"],
                        "y": position["y"],
                        "unit": position["unit"],
                    },
                    "size": via.GetWidth(pcbnew.F_Cu) / 1000000,
                    "drill": via.GetDrill() / 1000000,
                    "from_layer": from_layer,
                    "to_layer": to_layer,
                    "net": net,
                },
            }

        except Exception as e:
            logger.error(f"Error adding via: {str(e)}")
            return {
                "success": False,
                "message": "Failed to add via",
                "errorDetails": str(e),
            }

    def delete_trace(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Delete a trace from the PCB"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            trace_uuid = params.get("traceUuid")
            position = params.get("position")
            net_name = params.get("net")
            layer = params.get("layer")
            include_vias = params.get("includeVias", False)

            if not trace_uuid and not position and not net_name:
                return {
                    "success": False,
                    "message": "Missing parameters",
                    "errorDetails": "One of traceUuid, position, or net must be provided",
                }

            # Delete by net name (bulk delete)
            if net_name:
                tracks_to_remove = []
                for track in list(self.board.Tracks()):
                    if track.GetNetname() != net_name:
                        continue

                    # Skip vias if not requested
                    is_via = track.Type() == pcbnew.PCB_VIA_T
                    if is_via and not include_vias:
                        continue

                    # Filter by layer if specified (only for non-vias)
                    if layer and not is_via:
                        layer_id = self.board.GetLayerID(layer)
                        if track.GetLayer() != layer_id:
                            continue

                    tracks_to_remove.append(track)

                deleted_count = len(tracks_to_remove)
                for track in tracks_to_remove:
                    self.board.Remove(track)
                tracks_to_remove.clear()
                self.board.SetModified()

                return {
                    "success": True,
                    "message": f"Deleted {deleted_count} traces on net '{net_name}'",
                    "deletedCount": deleted_count,
                }

            # Find track by UUID
            if trace_uuid:
                track = None
                for item in list(self.board.Tracks()):
                    if item.m_Uuid.AsString() == trace_uuid:
                        track = item
                        break

                if not track:
                    return {
                        "success": False,
                        "message": "Track not found",
                        "errorDetails": f"Could not find track with UUID: {trace_uuid}",
                    }

                self.board.Remove(track)
                track = None
                self.board.SetModified()
                return {"success": True, "message": f"Deleted track: {trace_uuid}"}

            # No valid parameters provided
            if not position:
                return {
                    "success": False,
                    "message": "No valid search parameter provided",
                    "errorDetails": "Provide traceUuid, position, or net parameter",
                }

            # Find track by position
            if position:
                scale = (
                    1000000 if position["unit"] == "mm" else 25400000
                )  # mm or inch to nm
                x_nm = int(position["x"] * scale)
                y_nm = int(position["y"] * scale)
                point = pcbnew.VECTOR2I(x_nm, y_nm)

                # Find closest track
                closest_track = None
                min_distance = float("inf")
                for track in list(self.board.Tracks()):
                    dist = self._point_to_track_distance(point, track)
                    if dist < min_distance:
                        min_distance = dist
                        closest_track = track

                if closest_track and min_distance < 1000000:  # Within 1mm
                    self.board.Remove(closest_track)
                    closest_track = None
                    self.board.SetModified()
                    return {
                        "success": True,
                        "message": "Deleted track at specified position",
                    }
                else:
                    return {
                        "success": False,
                        "message": "No track found",
                        "errorDetails": "No track found near specified position",
                    }

        except Exception as e:
            logger.error(f"Error deleting trace: {str(e)}")
            return {
                "success": False,
                "message": "Failed to delete trace",
                "errorDetails": str(e),
            }
        return {
            "success": False,
            "message": "No action taken",
            "errorDetails": "No matching trace found for given parameters",
        }

    def get_nets_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get a list of all nets in the PCB"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            nets = []
            netinfo = self.board.GetNetInfo()
            for net_code in range(netinfo.GetNetCount()):
                net = netinfo.GetNetItem(net_code)
                if net:
                    nets.append(
                        {
                            "name": net.GetNetname(),
                            "code": net.GetNetCode(),
                            "class": net.GetNetClassName(),
                        }
                    )

            return {"success": True, "nets": nets}

        except Exception as e:
            logger.error(f"Error getting nets list: {str(e)}")
            return {
                "success": False,
                "message": "Failed to get nets list",
                "errorDetails": str(e),
            }

    def query_traces(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Query traces by net, layer, or bounding box"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            # Get filter parameters
            net_name = params.get("net")
            layer = params.get("layer")
            bbox = params.get("boundingBox")  # {x1, y1, x2, y2, unit}
            include_vias = params.get("includeVias", False)

            scale = 1000000  # nm to mm conversion factor
            traces = []
            vias = []

            # Process tracks
            for track in list(self.board.Tracks()):
                try:
                    # Check if it's a via
                    is_via = track.Type() == pcbnew.PCB_VIA_T

                    if is_via and not include_vias:
                        continue

                    # Filter by net
                    if net_name and track.GetNetname() != net_name:
                        continue

                    # Filter by layer (only for tracks, not vias)
                    if layer and not is_via:
                        layer_id = self.board.GetLayerID(layer)
                        if track.GetLayer() != layer_id:
                            continue

                    # Filter by bounding box
                    if bbox:
                        bbox_unit = bbox.get("unit", "mm")
                        bbox_scale = scale if bbox_unit == "mm" else 25400000
                        x1 = int(bbox.get("x1", 0) * bbox_scale)
                        y1 = int(bbox.get("y1", 0) * bbox_scale)
                        x2 = int(bbox.get("x2", 0) * bbox_scale)
                        y2 = int(bbox.get("y2", 0) * bbox_scale)

                        if is_via:
                            pos = track.GetPosition()
                            if not (x1 <= pos.x <= x2 and y1 <= pos.y <= y2):
                                continue
                        else:
                            start = track.GetStart()
                            end = track.GetEnd()
                            # Check if either endpoint is within bbox
                            start_in = x1 <= start.x <= x2 and y1 <= start.y <= y2
                            end_in = x1 <= end.x <= x2 and y1 <= end.y <= y2
                            if not (start_in or end_in):
                                continue

                    if is_via:
                        pos = track.GetPosition()
                        vias.append(
                            {
                                "uuid": track.m_Uuid.AsString(),
                                "position": {
                                    "x": pos.x / scale,
                                    "y": pos.y / scale,
                                    "unit": "mm",
                                },
                                "net": track.GetNetname(),
                                "netCode": track.GetNetCode(),
                                "diameter": track.GetWidth() / scale,
                                "drill": track.GetDrillValue() / scale,
                            }
                        )
                    else:
                        start = track.GetStart()
                        end = track.GetEnd()
                        traces.append(
                            {
                                "uuid": track.m_Uuid.AsString(),
                                "net": track.GetNetname(),
                                "netCode": track.GetNetCode(),
                                "layer": self.board.GetLayerName(track.GetLayer()),
                                "width": track.GetWidth() / scale,
                                "start": {
                                    "x": start.x / scale,
                                    "y": start.y / scale,
                                    "unit": "mm",
                                },
                                "end": {
                                    "x": end.x / scale,
                                    "y": end.y / scale,
                                    "unit": "mm",
                                },
                                "length": track.GetLength() / scale,
                            }
                        )
                except Exception as track_err:
                    logger.warning(f"Skipping invalid track object: {track_err}")
                    continue

            result = {"success": True, "traceCount": len(traces), "traces": traces}

            if include_vias:
                result["viaCount"] = len(vias)
                result["vias"] = vias

            return result

        except Exception as e:
            logger.error(f"Error querying traces: {str(e)}")
            return {
                "success": False,
                "message": "Failed to query traces",
                "errorDetails": str(e),
            }

    def modify_trace(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Modify properties of an existing trace

        Allows changing trace width, layer, and net assignment.
        Find trace by UUID or position.
        """
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            # Identification parameters
            trace_uuid = params.get("uuid")
            position = params.get("position")  # {x, y, unit}

            # Modification parameters
            new_width = params.get("width")  # in mm
            new_layer = params.get("layer")
            new_net = params.get("net")

            if not trace_uuid and not position:
                return {
                    "success": False,
                    "message": "Missing trace identifier",
                    "errorDetails": "Provide either 'uuid' or 'position' to identify the trace",
                }

            scale = 1000000  # nm to mm conversion

            # Find the track
            track = None

            if trace_uuid:
                for item in list(self.board.Tracks()):
                    if item.m_Uuid.AsString() == trace_uuid:
                        track = item
                        break
            elif position:
                pos_unit = position.get("unit", "mm")
                pos_scale = scale if pos_unit == "mm" else 25400000
                x_nm = int(position["x"] * pos_scale)
                y_nm = int(position["y"] * pos_scale)
                point = pcbnew.VECTOR2I(x_nm, y_nm)

                # Find closest track
                min_distance = float("inf")
                for item in list(self.board.Tracks()):
                    dist = self._point_to_track_distance(point, item)
                    if dist < min_distance:
                        min_distance = dist
                        track = item

                # Only accept if within 1mm
                if min_distance >= 1000000:
                    track = None

            if not track:
                return {
                    "success": False,
                    "message": "Track not found",
                    "errorDetails": "Could not find track with specified identifier",
                }

            # Check if it's a via (some modifications don't apply)
            is_via = track.Type() == pcbnew.PCB_VIA_T
            modifications = []

            # Apply modifications
            if new_width is not None:
                width_nm = int(new_width * scale)
                track.SetWidth(width_nm)
                modifications.append(f"width={new_width}mm")

            if new_layer and not is_via:
                layer_id = self.board.GetLayerID(new_layer)
                if layer_id < 0:
                    return {
                        "success": False,
                        "message": "Invalid layer",
                        "errorDetails": f"Layer '{new_layer}' not found",
                    }
                track.SetLayer(layer_id)
                modifications.append(f"layer={new_layer}")

            if new_net:
                netinfo = self.board.GetNetInfo()
                net = netinfo.GetNetItem(new_net)
                if not net:
                    return {
                        "success": False,
                        "message": "Invalid net",
                        "errorDetails": f"Net '{new_net}' not found",
                    }
                track.SetNet(net)
                modifications.append(f"net={new_net}")

            if not modifications:
                return {
                    "success": False,
                    "message": "No modifications specified",
                    "errorDetails": "Provide at least one of: width, layer, net",
                }

            return {
                "success": True,
                "message": f"Modified trace: {', '.join(modifications)}",
                "uuid": track.m_Uuid.AsString(),
                "modifications": modifications,
            }

        except Exception as e:
            logger.error(f"Error modifying trace: {str(e)}")
            return {
                "success": False,
                "message": "Failed to modify trace",
                "errorDetails": str(e),
            }

    def copy_routing_pattern(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Copy routing pattern from source components to target components

        This enables routing replication between identical component groups.
        The pattern is copied with a translation offset calculated from
        the position difference between source and target components.
        """
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            source_refs = params.get("sourceRefs", [])  # e.g., ["U1", "U2", "U3"]
            target_refs = params.get("targetRefs", [])  # e.g., ["U4", "U5", "U6"]
            include_vias = params.get("includeVias", True)
            trace_width = params.get("traceWidth")  # Optional override

            if not source_refs or not target_refs:
                return {
                    "success": False,
                    "message": "Missing component references",
                    "errorDetails": "Provide both 'sourceRefs' and 'targetRefs' arrays",
                }

            if len(source_refs) != len(target_refs):
                return {
                    "success": False,
                    "message": "Mismatched component counts",
                    "errorDetails": f"sourceRefs has {len(source_refs)} items, targetRefs has {len(target_refs)}",
                }

            scale = 1000000  # nm to mm conversion

            # Get footprints
            footprints = {fp.GetReference(): fp for fp in self.board.GetFootprints()}

            # Validate all references exist
            for ref in source_refs + target_refs:
                if ref not in footprints:
                    return {
                        "success": False,
                        "message": "Component not found",
                        "errorDetails": f"Component '{ref}' not found on board",
                    }

            # Calculate offset from first source to first target component
            source_fp = footprints[source_refs[0]]
            target_fp = footprints[target_refs[0]]
            source_pos = source_fp.GetPosition()
            target_pos = target_fp.GetPosition()

            offset_x = target_pos.x - source_pos.x
            offset_y = target_pos.y - source_pos.y

            # Build mapping from source refs to target refs
            ref_mapping = dict(zip(source_refs, target_refs))

            # Collect all nets connected to source components
            source_nets = set()
            source_pad_positions = []  # (x, y) in nm for geometric fallback
            for ref in source_refs:
                fp = footprints[ref]
                for pad in fp.Pads():
                    net_name = pad.GetNetname()
                    if net_name and net_name != "":
                        source_nets.add(net_name)
                    pos = pad.GetPosition()
                    source_pad_positions.append((pos.x, pos.y))

            # Build bounding box around source pads (with 5mm tolerance in nm)
            TOLERANCE_NM = int(5 * scale)
            if source_pad_positions:
                xs = [p[0] for p in source_pad_positions]
                ys = [p[1] for p in source_pad_positions]
                bbox_x1 = min(xs) - TOLERANCE_NM
                bbox_x2 = max(xs) + TOLERANCE_NM
                bbox_y1 = min(ys) - TOLERANCE_NM
                bbox_y2 = max(ys) + TOLERANCE_NM
            else:
                # Fall back to component position ± 25mm
                sp = source_fp.GetPosition()
                bbox_x1 = sp.x - int(25 * scale)
                bbox_x2 = sp.x + int(25 * scale)
                bbox_y1 = sp.y - int(25 * scale)
                bbox_y2 = sp.y + int(25 * scale)

            def point_in_bbox(px: int, py: int) -> bool:
                return bbox_x1 <= px <= bbox_x2 and bbox_y1 <= py <= bbox_y2

            # Collect traces: by net name (if available) OR by geometric proximity
            use_net_filter = len(source_nets) > 0
            traces_to_copy = []
            vias_to_copy = []

            for track in list(self.board.Tracks()):
                is_via = track.Type() == pcbnew.PCB_VIA_T

                if use_net_filter:
                    # Primary: net-based filter
                    if track.GetNetname() not in source_nets:
                        continue
                else:
                    # Fallback: geometric filter – trace start OR end inside source bbox
                    if is_via:
                        pos = track.GetPosition()
                        if not point_in_bbox(pos.x, pos.y):
                            continue
                    else:
                        s = track.GetStart()
                        e = track.GetEnd()
                        if not (point_in_bbox(s.x, s.y) or point_in_bbox(e.x, e.y)):
                            continue

                if is_via:
                    if include_vias:
                        vias_to_copy.append(track)
                else:
                    traces_to_copy.append(track)

            filter_method = (
                "net-based" if use_net_filter else "geometric (pads have no nets)"
            )
            logger.info(
                f"copy_routing_pattern: {len(traces_to_copy)} traces, "
                f"{len(vias_to_copy)} vias selected via {filter_method}"
            )

            # Create new traces with offset
            created_traces = 0
            created_vias = 0

            for track in traces_to_copy:
                start = track.GetStart()
                end = track.GetEnd()

                # Create new track
                new_track = pcbnew.PCB_TRACK(self.board)
                new_track.SetStart(
                    pcbnew.VECTOR2I(start.x + offset_x, start.y + offset_y)
                )
                new_track.SetEnd(pcbnew.VECTOR2I(end.x + offset_x, end.y + offset_y))
                new_track.SetLayer(track.GetLayer())

                # Set width (use override or original)
                if trace_width:
                    new_track.SetWidth(int(trace_width * scale))
                else:
                    new_track.SetWidth(track.GetWidth())

                # Try to find corresponding target net
                # This is a simplification - more sophisticated mapping would be needed
                # for complex designs
                self.board.Add(new_track)
                created_traces += 1

            for via in vias_to_copy:
                pos = via.GetPosition()

                # Create new via
                new_via = pcbnew.PCB_VIA(self.board)
                new_via.SetPosition(pcbnew.VECTOR2I(pos.x + offset_x, pos.y + offset_y))
                new_via.SetWidth(via.GetWidth(pcbnew.F_Cu))
                new_via.SetDrill(via.GetDrillValue())
                new_via.SetViaType(via.GetViaType())

                self.board.Add(new_via)
                created_vias += 1

            result = {
                "success": True,
                "message": f"Copied routing pattern: {created_traces} traces, {created_vias} vias",
                "filterMethod": filter_method,
                "offset": {"x": offset_x / scale, "y": offset_y / scale, "unit": "mm"},
                "createdTraces": created_traces,
                "createdVias": created_vias,
                "sourceComponents": source_refs,
                "targetComponents": target_refs,
            }

            return result

        except Exception as e:
            logger.error(f"Error copying routing pattern: {str(e)}")
            return {
                "success": False,
                "message": "Failed to copy routing pattern",
                "errorDetails": str(e),
            }

    def create_netclass(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new net class with specified properties"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            name = params.get("name")
            clearance = params.get("clearance")
            track_width = params.get("trackWidth")
            via_diameter = params.get("viaDiameter")
            via_drill = params.get("viaDrill")
            uvia_diameter = params.get("uviaDiameter")
            uvia_drill = params.get("uviaDrill")
            diff_pair_width = params.get("diffPairWidth")
            diff_pair_gap = params.get("diffPairGap")
            nets = params.get("nets", [])

            if not name:
                return {
                    "success": False,
                    "message": "Missing netclass name",
                    "errorDetails": "name parameter is required",
                }

            # Get net classes
            net_classes = self.board.GetNetClasses()

            # Create new net class if it doesn't exist
            if not net_classes.Find(name):
                netclass = pcbnew.NETCLASS(name)
                net_classes.Add(netclass)
            else:
                netclass = net_classes.Find(name)

            # Set properties
            scale = 1000000  # mm to nm
            if clearance is not None:
                netclass.SetClearance(int(clearance * scale))
            if track_width is not None:
                netclass.SetTrackWidth(int(track_width * scale))
            if via_diameter is not None:
                netclass.SetViaDiameter(int(via_diameter * scale))
            if via_drill is not None:
                netclass.SetViaDrill(int(via_drill * scale))
            if uvia_diameter is not None:
                netclass.SetMicroViaDiameter(int(uvia_diameter * scale))
            if uvia_drill is not None:
                netclass.SetMicroViaDrill(int(uvia_drill * scale))
            if diff_pair_width is not None:
                netclass.SetDiffPairWidth(int(diff_pair_width * scale))
            if diff_pair_gap is not None:
                netclass.SetDiffPairGap(int(diff_pair_gap * scale))

            # Add nets to net class
            netinfo = self.board.GetNetInfo()
            nets_map = netinfo.NetsByName()
            for net_name in nets:
                if nets_map.has_key(net_name):
                    net = nets_map[net_name]
                    net.SetClass(netclass)

            return {
                "success": True,
                "message": f"Created net class: {name}",
                "netClass": {
                    "name": name,
                    "clearance": netclass.GetClearance() / scale,
                    "trackWidth": netclass.GetTrackWidth() / scale,
                    "viaDiameter": netclass.GetViaDiameter() / scale,
                    "viaDrill": netclass.GetViaDrill() / scale,
                    "uviaDiameter": netclass.GetMicroViaDiameter() / scale,
                    "uviaDrill": netclass.GetMicroViaDrill() / scale,
                    "diffPairWidth": netclass.GetDiffPairWidth() / scale,
                    "diffPairGap": netclass.GetDiffPairGap() / scale,
                    "nets": nets,
                },
            }

        except Exception as e:
            logger.error(f"Error creating net class: {str(e)}")
            return {
                "success": False,
                "message": "Failed to create net class",
                "errorDetails": str(e),
            }

    def add_copper_pour(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a copper pour (zone) to the PCB"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            layer = params.get("layer", "F.Cu")
            net = params.get("net")
            clearance = params.get("clearance")
            min_width = params.get("minWidth", 0.2)
            points = params.get("outline", params.get("points", []))
            priority = params.get("priority", 0)
            fill_type = params.get("fillType", "solid")  # solid or hatched

            # If no outline provided, use board outline
            if not points or len(points) < 3:
                board_box = self.board.GetBoardEdgesBoundingBox()
                if board_box.GetWidth() > 0 and board_box.GetHeight() > 0:
                    scale = 1000000  # nm to mm
                    x1 = board_box.GetX() / scale
                    y1 = board_box.GetY() / scale
                    x2 = (board_box.GetX() + board_box.GetWidth()) / scale
                    y2 = (board_box.GetY() + board_box.GetHeight()) / scale

                    # Detect corner radius from Edge.Cuts arcs so the zone rectangle
                    # stays inside the rounded board corners (avoids zone visually
                    # extending outside Edge.Cuts before refill)
                    corner_radius = 0.0
                    edge_layer_id = self.board.GetLayerID("Edge.Cuts")
                    for item in self.board.GetDrawings():
                        if item.GetLayer() == edge_layer_id and item.GetClass() == "PCB_ARC":
                            r = item.GetRadius() / scale
                            if r > corner_radius:
                                corner_radius = r
                    # Inset the zone rectangle by the corner radius so its corners
                    # lie on the straight portions of the board edge.
                    inset = corner_radius
                    points = [
                        {"x": x1 + inset, "y": y1 + inset},
                        {"x": x2 - inset, "y": y1 + inset},
                        {"x": x2 - inset, "y": y2 - inset},
                        {"x": x1 + inset, "y": y2 - inset},
                    ]
                else:
                    return {
                        "success": False,
                        "message": "Missing outline",
                        "errorDetails": "Provide an outline array or add a board outline first",
                    }

            # Get layer ID
            layer_id = self.board.GetLayerID(layer)
            if layer_id < 0:
                return {
                    "success": False,
                    "message": "Invalid layer",
                    "errorDetails": f"Layer '{layer}' does not exist",
                }

            # Create zone
            zone = pcbnew.ZONE(self.board)
            zone.SetLayer(layer_id)

            # Set net if provided
            if net:
                netinfo = self.board.GetNetInfo()
                nets_map = netinfo.NetsByName()
                if nets_map.has_key(net):
                    net_obj = nets_map[net]
                    zone.SetNet(net_obj)

            # Set zone properties
            scale = 1000000  # mm to nm
            zone.SetAssignedPriority(priority)

            if clearance is not None:
                zone.SetLocalClearance(int(clearance * scale))

            zone.SetMinThickness(int(min_width * scale))

            # Set fill type
            if fill_type == "hatched":
                zone.SetFillMode(pcbnew.ZONE_FILL_MODE_HATCH_PATTERN)
            else:
                zone.SetFillMode(pcbnew.ZONE_FILL_MODE_POLYGONS)

            # Create outline
            outline = zone.Outline()
            outline.NewOutline()  # Create a new outline contour first

            # Add points to outline
            for point in points:
                scale = 1000000 if point.get("unit", "mm") == "mm" else 25400000
                x_nm = int(point["x"] * scale)
                y_nm = int(point["y"] * scale)
                outline.Append(pcbnew.VECTOR2I(x_nm, y_nm))  # Add point to outline

            # Add zone to board
            self.board.Add(zone)

            # Fill zone
            # Note: Zone filling can cause issues with SWIG API
            # Comment out for now - zones will be filled when board is saved/opened in KiCAD
            # filler = pcbnew.ZONE_FILLER(self.board)
            # filler.Fill(self.board.Zones())

            return {
                "success": True,
                "message": "Added copper pour",
                "pour": {
                    "layer": layer,
                    "net": net,
                    "clearance": clearance,
                    "minWidth": min_width,
                    "priority": priority,
                    "fillType": fill_type,
                    "pointCount": len(points),
                },
            }

        except Exception as e:
            logger.error(f"Error adding copper pour: {str(e)}")
            return {
                "success": False,
                "message": "Failed to add copper pour",
                "errorDetails": str(e),
            }

    def route_differential_pair(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Route a differential pair between two sets of points or pads"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            start_pos = params.get("startPos")
            end_pos = params.get("endPos")
            net_pos = params.get("netPos")
            net_neg = params.get("netNeg")
            layer = params.get("layer", "F.Cu")
            width = params.get("width")
            gap = params.get("gap")

            if not start_pos or not end_pos or not net_pos or not net_neg:
                return {
                    "success": False,
                    "message": "Missing parameters",
                    "errorDetails": "startPos, endPos, netPos, and netNeg are required",
                }

            # Get layer ID
            layer_id = self.board.GetLayerID(layer)
            if layer_id < 0:
                return {
                    "success": False,
                    "message": "Invalid layer",
                    "errorDetails": f"Layer '{layer}' does not exist",
                }

            # Get nets
            netinfo = self.board.GetNetInfo()
            nets_map = netinfo.NetsByName()

            net_pos_obj = nets_map[net_pos] if nets_map.has_key(net_pos) else None
            net_neg_obj = nets_map[net_neg] if nets_map.has_key(net_neg) else None

            if not net_pos_obj or not net_neg_obj:
                return {
                    "success": False,
                    "message": "Nets not found",
                    "errorDetails": "One or both nets specified for the differential pair do not exist",
                }

            # Get start and end points
            start_point = self._get_point(start_pos)
            end_point = self._get_point(end_pos)

            # Calculate offset vectors for the two traces
            # First, get the direction vector from start to end
            dx = end_point.x - start_point.x
            dy = end_point.y - start_point.y
            length = math.sqrt(dx * dx + dy * dy)

            if length <= 0:
                return {
                    "success": False,
                    "message": "Invalid points",
                    "errorDetails": "Start and end points must be different",
                }

            # Normalize direction vector
            dx /= length
            dy /= length

            # Get perpendicular vector
            px = -dy
            py = dx

            # Set default gap if not provided
            if gap is None:
                gap = 0.2  # mm

            # Convert to nm
            gap_nm = int(gap * 1000000)

            # Calculate offsets
            offset_x = int(px * gap_nm / 2)
            offset_y = int(py * gap_nm / 2)

            # Create positive and negative trace points
            pos_start = pcbnew.VECTOR2I(
                int(start_point.x + offset_x), int(start_point.y + offset_y)
            )
            pos_end = pcbnew.VECTOR2I(
                int(end_point.x + offset_x), int(end_point.y + offset_y)
            )
            neg_start = pcbnew.VECTOR2I(
                int(start_point.x - offset_x), int(start_point.y - offset_y)
            )
            neg_end = pcbnew.VECTOR2I(
                int(end_point.x - offset_x), int(end_point.y - offset_y)
            )

            # Create positive trace
            pos_track = pcbnew.PCB_TRACK(self.board)
            pos_track.SetStart(pos_start)
            pos_track.SetEnd(pos_end)
            pos_track.SetLayer(layer_id)
            pos_track.SetNet(net_pos_obj)

            # Create negative trace
            neg_track = pcbnew.PCB_TRACK(self.board)
            neg_track.SetStart(neg_start)
            neg_track.SetEnd(neg_end)
            neg_track.SetLayer(layer_id)
            neg_track.SetNet(net_neg_obj)

            # Set width
            if width:
                trace_width_nm = int(width * 1000000)
                pos_track.SetWidth(trace_width_nm)
                neg_track.SetWidth(trace_width_nm)
            else:
                # Get default width from design rules or net class
                trace_width = self.board.GetDesignSettings().GetCurrentTrackWidth()
                pos_track.SetWidth(trace_width)
                neg_track.SetWidth(trace_width)

            # Add tracks to board
            self.board.Add(pos_track)
            self.board.Add(neg_track)

            return {
                "success": True,
                "message": "Added differential pair traces",
                "diffPair": {
                    "posNet": net_pos,
                    "negNet": net_neg,
                    "layer": layer,
                    "width": pos_track.GetWidth() / 1000000,
                    "gap": gap,
                    "length": length / 1000000,
                },
            }

        except Exception as e:
            logger.error(f"Error routing differential pair: {str(e)}")
            return {
                "success": False,
                "message": "Failed to route differential pair",
                "errorDetails": str(e),
            }

    def route_differential_pairs(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Route multiple differential pairs as a bus with waypoints.

        Routes pairs like USB (D+/D-, SSRX+/SSRX-) or HDMI TMDS channels
        simultaneously, maintaining configurable inter-pair spacing.
        Supports waypoints so the bus can turn corners.
        """
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            pairs = params.get("pairs", [])
            layer = params.get("layer", "F.Cu")
            width = params.get("width")
            gap = params.get("gap", 0.2)
            inter_pair_spacing = params.get("interPairSpacing", 0.5)
            waypoints = params.get("waypoints", [])

            if not pairs or len(pairs) < 1:
                return {
                    "success": False,
                    "message": "Missing pairs",
                    "errorDetails": "Provide at least one pair with netPos and netNeg",
                }

            if len(waypoints) < 2:
                return {
                    "success": False,
                    "message": "Need at least 2 waypoints",
                    "errorDetails": "Provide start and end points as waypoints",
                }

            layer_id = self.board.GetLayerID(layer)
            if layer_id < 0:
                return {
                    "success": False,
                    "message": "Invalid layer",
                    "errorDetails": f"Layer '{layer}' does not exist",
                }

            netinfo = self.board.GetNetInfo()
            nets_map = netinfo.NetsByName()

            scale = 1000000
            gap_nm = int(gap * scale)
            pair_pitch_nm = int(inter_pair_spacing * scale)

            if width:
                trace_width_nm = int(width * scale)
            else:
                trace_width_nm = self.board.GetDesignSettings().GetCurrentTrackWidth()

            num_pairs = len(pairs)
            total_bus_width_nm = (num_pairs - 1) * pair_pitch_nm
            routed_pairs = []
            total_segments = 0

            for pair_idx, pair in enumerate(pairs):
                net_pos_name = pair.get("netPos")
                net_neg_name = pair.get("netNeg")
                if not net_pos_name or not net_neg_name:
                    return {
                        "success": False,
                        "message": f"Pair {pair_idx} missing netPos or netNeg",
                        "errorDetails": "Each pair must have netPos and netNeg",
                    }

                net_pos_obj = nets_map[net_pos_name] if nets_map.has_key(net_pos_name) else None
                net_neg_obj = nets_map[net_neg_name] if nets_map.has_key(net_neg_name) else None

                if not net_pos_obj or not net_neg_obj:
                    missing = []
                    if not net_pos_obj:
                        missing.append(net_pos_name)
                    if not net_neg_obj:
                        missing.append(net_neg_name)
                    return {
                        "success": False,
                        "message": f"Nets not found: {', '.join(missing)}",
                        "errorDetails": "Create the nets first with add_net",
                    }

                pair_center_offset_nm = int(pair_idx * pair_pitch_nm - total_bus_width_nm / 2)

                for seg_idx in range(len(waypoints) - 1):
                    wp_start = waypoints[seg_idx]
                    wp_end = waypoints[seg_idx + 1]

                    sx = wp_start["x"] * scale
                    sy = wp_start["y"] * scale
                    ex = wp_end["x"] * scale
                    ey = wp_end["y"] * scale

                    dx = ex - sx
                    dy = ey - sy
                    seg_len = math.sqrt(dx * dx + dy * dy)
                    if seg_len <= 0:
                        continue

                    nx = -dy / seg_len
                    ny = dx / seg_len

                    pos_offset = pair_center_offset_nm + gap_nm // 2
                    neg_offset = pair_center_offset_nm - gap_nm // 2

                    pos_track = pcbnew.PCB_TRACK(self.board)
                    pos_track.SetStart(pcbnew.VECTOR2I(
                        int(sx + nx * pos_offset), int(sy + ny * pos_offset)))
                    pos_track.SetEnd(pcbnew.VECTOR2I(
                        int(ex + nx * pos_offset), int(ey + ny * pos_offset)))
                    pos_track.SetLayer(layer_id)
                    pos_track.SetWidth(trace_width_nm)
                    pos_track.SetNet(net_pos_obj)
                    self.board.Add(pos_track)

                    neg_track = pcbnew.PCB_TRACK(self.board)
                    neg_track.SetStart(pcbnew.VECTOR2I(
                        int(sx + nx * neg_offset), int(sy + ny * neg_offset)))
                    neg_track.SetEnd(pcbnew.VECTOR2I(
                        int(ex + nx * neg_offset), int(ey + ny * neg_offset)))
                    neg_track.SetLayer(layer_id)
                    neg_track.SetWidth(trace_width_nm)
                    neg_track.SetNet(net_neg_obj)
                    self.board.Add(neg_track)

                    total_segments += 2

                routed_pairs.append({
                    "netPos": net_pos_name,
                    "netNeg": net_neg_name,
                    "segments": len(waypoints) - 1,
                })

            return {
                "success": True,
                "message": f"Routed {num_pairs} differential pairs with {total_segments} trace segments",
                "pairs": routed_pairs,
                "totalSegments": total_segments,
                "layer": layer,
                "width": trace_width_nm / scale,
                "gap": gap,
                "interPairSpacing": inter_pair_spacing,
            }

        except Exception as e:
            logger.error(f"Error routing differential pairs: {str(e)}")
            return {
                "success": False,
                "message": "Failed to route differential pairs",
                "errorDetails": str(e),
            }

    def route_with_waypoints(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Route a trace through multiple waypoints with optional layer changes.

        Creates connected trace segments through all waypoints.
        If a waypoint specifies a different layer, a via is auto-inserted.
        """
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            waypoints = params.get("waypoints", [])
            net = params.get("net")
            width = params.get("width")
            default_layer = params.get("layer", "F.Cu")

            if len(waypoints) < 2:
                return {
                    "success": False,
                    "message": "Need at least 2 waypoints",
                    "errorDetails": "Provide at least start and end waypoints",
                }

            scale = 1000000

            if width:
                trace_width_nm = int(width * scale)
            else:
                trace_width_nm = self.board.GetDesignSettings().GetCurrentTrackWidth()

            net_obj = None
            if net:
                netinfo = self.board.GetNetInfo()
                nets_map = netinfo.NetsByName()
                if nets_map.has_key(net):
                    net_obj = nets_map[net]

            segments_created = 0
            vias_created = 0
            current_layer = default_layer

            for i in range(len(waypoints) - 1):
                wp_start = waypoints[i]
                wp_end = waypoints[i + 1]

                start_layer = wp_start.get("layer", current_layer)
                end_layer = wp_end.get("layer", start_layer)

                start_point = self._get_point({"x": wp_start["x"], "y": wp_start["y"], "unit": "mm"})
                end_point = self._get_point({"x": wp_end["x"], "y": wp_end["y"], "unit": "mm"})

                if start_layer != end_layer:
                    track1 = pcbnew.PCB_TRACK(self.board)
                    track1.SetStart(start_point)
                    track1.SetEnd(end_point)
                    track1.SetLayer(self.board.GetLayerID(start_layer))
                    track1.SetWidth(trace_width_nm)
                    if net_obj:
                        track1.SetNet(net_obj)
                    self.board.Add(track1)
                    segments_created += 1

                    via = pcbnew.PCB_VIA(self.board)
                    via.SetPosition(end_point)
                    design_settings = self.board.GetDesignSettings()
                    via.SetWidth(design_settings.GetCurrentViaSize())
                    via.SetDrill(design_settings.GetCurrentViaDrill())
                    from_id = self.board.GetLayerID(start_layer)
                    to_id = self.board.GetLayerID(end_layer)
                    via.SetLayerPair(from_id, to_id)
                    if net_obj:
                        via.SetNet(net_obj)
                    self.board.Add(via)
                    vias_created += 1

                    current_layer = end_layer
                else:
                    track = pcbnew.PCB_TRACK(self.board)
                    track.SetStart(start_point)
                    track.SetEnd(end_point)
                    track.SetLayer(self.board.GetLayerID(start_layer))
                    track.SetWidth(trace_width_nm)
                    if net_obj:
                        track.SetNet(net_obj)
                    self.board.Add(track)
                    segments_created += 1

                    current_layer = start_layer

            return {
                "success": True,
                "message": f"Routed {segments_created} segments with {vias_created} vias through {len(waypoints)} waypoints",
                "segments": segments_created,
                "vias": vias_created,
                "waypointCount": len(waypoints),
                "net": net,
                "width": trace_width_nm / scale,
            }

        except Exception as e:
            logger.error(f"Error routing with waypoints: {str(e)}")
            return {
                "success": False,
                "message": "Failed to route with waypoints",
                "errorDetails": str(e),
            }

    def route_pad_to_pad_smart(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Route between pads using L-shaped or Z-shaped paths.

        Supports strategies: direct, L_horizontal_first, L_vertical_first, Z.
        Auto-detects net from pads, auto-inserts vias for layer transitions.
        """
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            from_ref = params.get("fromRef")
            from_pad = str(params.get("fromPad", ""))
            to_ref = params.get("toRef")
            to_pad = str(params.get("toPad", ""))
            layer = params.get("layer", "F.Cu")
            width = params.get("width")
            net = params.get("net")
            strategy = params.get("strategy", "L_horizontal_first")
            z_midpoint = params.get("zMidpoint", 0.5)

            if not from_ref or not from_pad or not to_ref or not to_pad:
                return {
                    "success": False,
                    "message": "Missing parameters",
                    "errorDetails": "fromRef, fromPad, toRef, toPad are all required",
                }

            scale = 1000000
            footprints = {fp.GetReference(): fp for fp in self.board.GetFootprints()}

            for ref in [from_ref, to_ref]:
                if ref not in footprints:
                    return {
                        "success": False,
                        "message": f"Component not found: {ref}",
                        "errorDetails": f"'{ref}' does not exist on the board",
                    }

            def find_pad(ref: str, pad_num: str):
                fp = footprints[ref]
                for pad in fp.Pads():
                    if pad.GetNumber() == pad_num:
                        return pad
                return None

            start_pad = find_pad(from_ref, from_pad)
            end_pad = find_pad(to_ref, to_pad)

            if not start_pad:
                return {
                    "success": False,
                    "message": f"Pad not found: {from_ref} pad {from_pad}",
                    "errorDetails": f"Check pad number for {from_ref}",
                }
            if not end_pad:
                return {
                    "success": False,
                    "message": f"Pad not found: {to_ref} pad {to_pad}",
                    "errorDetails": f"Check pad number for {to_ref}",
                }

            start_pos = start_pad.GetPosition()
            end_pos = end_pad.GetPosition()

            if not net:
                net = start_pad.GetNetname() or end_pad.GetNetname() or ""

            fp_start = footprints[from_ref]
            fp_end = footprints[to_ref]
            start_layer = self.board.GetLayerName(fp_start.GetLayer())
            end_layer = self.board.GetLayerName(fp_end.GetLayer())
            copper_layers = {"F.Cu", "B.Cu"}
            needs_via = (
                start_layer in copper_layers
                and end_layer in copper_layers
                and start_layer != end_layer
            )

            sx = start_pos.x / scale
            sy = start_pos.y / scale
            ex = end_pos.x / scale
            ey = end_pos.y / scale

            if strategy == "direct":
                waypoints_list = [
                    {"x": sx, "y": sy},
                    {"x": ex, "y": ey},
                ]
            elif strategy == "L_horizontal_first":
                waypoints_list = [
                    {"x": sx, "y": sy},
                    {"x": ex, "y": sy},
                    {"x": ex, "y": ey},
                ]
            elif strategy == "L_vertical_first":
                waypoints_list = [
                    {"x": sx, "y": sy},
                    {"x": sx, "y": ey},
                    {"x": ex, "y": ey},
                ]
            elif strategy == "Z":
                mid_x = sx + (ex - sx) * z_midpoint
                waypoints_list = [
                    {"x": sx, "y": sy},
                    {"x": mid_x, "y": sy},
                    {"x": mid_x, "y": ey},
                    {"x": ex, "y": ey},
                ]
            else:
                return {
                    "success": False,
                    "message": f"Unknown strategy: {strategy}",
                    "errorDetails": "Use direct, L_horizontal_first, L_vertical_first, or Z",
                }

            route_layer = layer if layer else start_layer

            if needs_via:
                via_wp = waypoints_list[-1]
                via_x = via_wp["x"]
                via_y = via_wp["y"]

                for i in range(len(waypoints_list) - 1):
                    wp_s = waypoints_list[i]
                    wp_e = waypoints_list[i + 1]
                    self.route_trace({
                        "start": {"x": wp_s["x"], "y": wp_s["y"], "unit": "mm"},
                        "end": {"x": wp_e["x"], "y": wp_e["y"], "unit": "mm"},
                        "layer": start_layer, "width": width, "net": net,
                    })

                self.add_via({
                    "position": {"x": via_x, "y": via_y, "unit": "mm"},
                    "net": net,
                    "from_layer": start_layer,
                    "to_layer": end_layer,
                })

                return {
                    "success": True,
                    "message": f"Smart-routed {from_ref}.{from_pad} → {to_ref}.{to_pad} ({strategy}, via at {via_x:.2f},{via_y:.2f})",
                    "strategy": strategy,
                    "segments": len(waypoints_list) - 1,
                    "via_added": True,
                    "fromPad": {"ref": from_ref, "pad": from_pad, "x": sx, "y": sy},
                    "toPad": {"ref": to_ref, "pad": to_pad, "x": ex, "y": ey},
                    "waypoints": waypoints_list,
                }
            else:
                for i in range(len(waypoints_list) - 1):
                    wp_s = waypoints_list[i]
                    wp_e = waypoints_list[i + 1]
                    self.route_trace({
                        "start": {"x": wp_s["x"], "y": wp_s["y"], "unit": "mm"},
                        "end": {"x": wp_e["x"], "y": wp_e["y"], "unit": "mm"},
                        "layer": route_layer, "width": width, "net": net,
                    })

                return {
                    "success": True,
                    "message": f"Smart-routed {from_ref}.{from_pad} → {to_ref}.{to_pad} ({strategy})",
                    "strategy": strategy,
                    "segments": len(waypoints_list) - 1,
                    "via_added": False,
                    "fromPad": {"ref": from_ref, "pad": from_pad, "x": sx, "y": sy},
                    "toPad": {"ref": to_ref, "pad": to_pad, "x": ex, "y": ey},
                    "waypoints": waypoints_list,
                }

        except Exception as e:
            logger.error(f"Error in route_pad_to_pad_smart: {str(e)}")
            return {
                "success": False,
                "message": "Failed to smart-route pad to pad",
                "errorDetails": str(e),
            }

    def autoroute_advanced(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Multi-seed autoroute using Freerouting, picking the best result by DRC score.

        Runs Freerouting N times with different random seeds, scores each by
        DRC violation count, and keeps the best result.
        """
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            from commands.freerouting import FreeroutingCommands

            seeds = params.get("seeds", 3)
            max_passes = params.get("maxPasses", 20)
            timeout = params.get("timeout", 300)
            board_path = params.get("boardPath") or self.board.GetFileName()
            jar_path = params.get("freeroutingJar")

            if not board_path:
                return {
                    "success": False,
                    "message": "No board file path available",
                    "errorDetails": "Provide boardPath or open a project first",
                }

            seeds = max(1, min(seeds, 10))

            self.board.Save(board_path)

            fr = FreeroutingCommands(board=None)
            board_dir = os.path.dirname(board_path)
            board_stem = os.path.splitext(os.path.basename(board_path))[0]

            import shutil as _shutil
            import tempfile

            results = []
            best_idx = -1
            best_violations = float("inf")

            for seed_idx in range(seeds):
                work_dir = tempfile.mkdtemp(prefix=f"autoroute_seed{seed_idx}_")
                work_board = os.path.join(work_dir, os.path.basename(board_path))
                _shutil.copy2(board_path, work_board)

                try:
                    seed_board = pcbnew.LoadBoard(work_board)
                except Exception as e:
                    results.append({
                        "seed": seed_idx,
                        "success": False,
                        "error": f"Failed to load board copy: {e}",
                    })
                    continue

                fr_seed = FreeroutingCommands(board=seed_board)
                fr_params = {
                    "boardPath": work_board,
                    "maxPasses": max_passes,
                    "timeout": timeout,
                }
                if jar_path:
                    fr_params["freeroutingJar"] = jar_path

                result = fr_seed.autoroute(fr_params)

                if not result.get("success"):
                    results.append({
                        "seed": seed_idx,
                        "success": False,
                        "error": result.get("errorDetails", result.get("message", "Unknown error")),
                    })
                    continue

                violation_count = 0
                drc_json = os.path.join(work_dir, f"{board_stem}_drc.json")
                try:
                    import subprocess as _subprocess
                    kicad_cli = _shutil.which("kicad-cli")
                    if kicad_cli:
                        _subprocess.run(
                            [kicad_cli, "pcb", "drc",
                             "--output", drc_json,
                             "--format", "json",
                             "--severity-all",
                             work_board],
                            capture_output=True, text=True, timeout=60,
                        )
                        if os.path.isfile(drc_json):
                            import json
                            with open(drc_json, "r") as f:
                                drc_data = json.load(f)
                            violation_count = len(drc_data.get("violations", []))
                except Exception as drc_err:
                    logger.warning(f"DRC scoring failed for seed {seed_idx}: {drc_err}")
                    violation_count = 0

                track_count = result.get("board_stats", {}).get("tracks", 0)
                via_count = result.get("board_stats", {}).get("vias", 0)

                seed_result = {
                    "seed": seed_idx,
                    "success": True,
                    "violations": violation_count,
                    "tracks": track_count,
                    "vias": via_count,
                    "elapsed": result.get("elapsed_seconds", 0),
                    "boardPath": work_board,
                }
                results.append(seed_result)

                if violation_count < best_violations:
                    best_violations = violation_count
                    best_idx = seed_idx

            if best_idx < 0:
                return {
                    "success": False,
                    "message": "All autoroute seeds failed",
                    "errorDetails": "No seed produced a valid result",
                    "seeds": results,
                }

            best_result = results[best_idx]
            best_board_path = best_result["boardPath"]

            try:
                _shutil.copy2(best_board_path, board_path)
                self.board = pcbnew.LoadBoard(board_path)
            except Exception as e:
                return {
                    "success": False,
                    "message": "Failed to apply best result",
                    "errorDetails": str(e),
                    "seeds": results,
                }

            for r in results:
                work_path = r.get("boardPath", "")
                work_dir = os.path.dirname(work_path) if work_path else ""
                if work_dir and work_dir != board_dir and os.path.isdir(work_dir):
                    try:
                        _shutil.rmtree(work_dir)
                    except Exception:
                        pass

            return {
                "success": True,
                "message": f"Best result from seed {best_idx} with {best_violations} DRC violations",
                "bestSeed": best_idx,
                "bestViolations": best_violations,
                "bestTracks": best_result.get("tracks", 0),
                "bestVias": best_result.get("vias", 0),
                "totalSeeds": seeds,
                "seeds": results,
            }

        except Exception as e:
            logger.error(f"Error in autoroute_advanced: {str(e)}")
            return {
                "success": False,
                "message": "Failed to run advanced autoroute",
                "errorDetails": str(e),
            }

    def _get_point(self, point_spec: Dict[str, Any]) -> pcbnew.VECTOR2I:
        """Convert point specification to KiCAD point"""
        if "x" in point_spec and "y" in point_spec:
            scale = 1000000 if point_spec.get("unit", "mm") == "mm" else 25400000
            x_nm = int(point_spec["x"] * scale)
            y_nm = int(point_spec["y"] * scale)
            return pcbnew.VECTOR2I(x_nm, y_nm)
        elif "pad" in point_spec and "componentRef" in point_spec:
            module = self.board.FindFootprintByReference(point_spec["componentRef"])
            if module:
                pad = module.FindPadByName(point_spec["pad"])
                if pad:
                    return pad.GetPosition()
        raise ValueError("Invalid point specification")

    def _point_to_track_distance(
        self, point: pcbnew.VECTOR2I, track: pcbnew.PCB_TRACK
    ) -> float:
        """Calculate distance from point to track segment"""
        start = track.GetStart()
        end = track.GetEnd()

        # Vector from start to end
        v = pcbnew.VECTOR2I(end.x - start.x, end.y - start.y)
        # Vector from start to point
        w = pcbnew.VECTOR2I(point.x - start.x, point.y - start.y)

        # Length of track squared
        c1 = v.x * v.x + v.y * v.y
        if c1 == 0:
            return self._point_distance(point, start)

        # Projection coefficient
        c2 = float(w.x * v.x + w.y * v.y) / c1

        if c2 < 0:
            return self._point_distance(point, start)
        elif c2 > 1:
            return self._point_distance(point, end)

        # Point on line
        proj = pcbnew.VECTOR2I(int(start.x + c2 * v.x), int(start.y + c2 * v.y))
        return self._point_distance(point, proj)

    def _point_distance(self, p1: pcbnew.VECTOR2I, p2: pcbnew.VECTOR2I) -> float:
        """Calculate distance between two points"""
        dx = p1.x - p2.x
        dy = p1.y - p2.y
        return (dx * dx + dy * dy) ** 0.5
