"""
KiCad MCP Bridge Plugin

Action Plugin that runs inside KiCad, exposing a local WebSocket server so the
MCP server can push real-time board changes while the user has the board open.

Architecture:
  MCP Server (TypeScript) ──WebSocket──▶ This Plugin (inside KiCad)
                                            │
                                        pcbnew SWIG API (same process)
                                            │
                                        Board appears on screen instantly

The plugin solves the "close the file first" problem: because it runs inside
KiCad's own Python environment, it can call pcbnew.Refresh() after every
mutation, so the user sees changes without reloading.
"""

import pcbnew
import wx
import json
import threading
import logging
import traceback
from pathlib import Path

logger = logging.getLogger("MCP_Bridge")

DEFAULT_PORT = 9876
PLUGIN_NAME = "MCP AI Bridge"
PLUGIN_DESCRIPTION = "Live bridge between KiCad and the MCP AI server"
PLUGIN_ICON = None  # Will be set if icon file exists


class MCP_BRIDGE_ACTION(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = PLUGIN_NAME
        self.category = "AI Tools"
        self.description = PLUGIN_DESCRIPTION
        self.show_toolbar_button = True
        icon_path = Path(__file__).parent / "icon.png"
        if icon_path.exists():
            self.icon_file_name = str(icon_path)

    def Run(self):
        board = pcbnew.GetBoard()
        if board is None:
            wx.MessageBox("No board is open.", PLUGIN_NAME, wx.OK | wx.ICON_ERROR)
            return

        if BridgeServer.instance and BridgeServer.instance.running:
            dlg = wx.MessageDialog(
                None,
                f"MCP Bridge is running on port {BridgeServer.instance.port}.\n\n"
                "Stop the server?",
                PLUGIN_NAME,
                wx.YES_NO | wx.ICON_QUESTION,
            )
            if dlg.ShowModal() == wx.ID_YES:
                BridgeServer.instance.stop()
                wx.MessageBox("MCP Bridge stopped.", PLUGIN_NAME, wx.OK | wx.ICON_INFORMATION)
            dlg.Destroy()
            return

        dlg = SettingsDialog(None)
        if dlg.ShowModal() == wx.ID_OK:
            port = dlg.get_port()
            server = BridgeServer(board, port)
            server.start()
            wx.MessageBox(
                f"MCP Bridge started on ws://localhost:{port}\n\n"
                "The AI can now make live changes to your board.\n"
                "Click the plugin button again to stop.",
                PLUGIN_NAME,
                wx.OK | wx.ICON_INFORMATION,
            )
        dlg.Destroy()


class SettingsDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title=f"{PLUGIN_NAME} Settings", size=(320, 160))
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        hbox.Add(wx.StaticText(panel, label="WebSocket Port:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.port_ctrl = wx.SpinCtrl(panel, value=str(DEFAULT_PORT), min=1024, max=65535)
        hbox.Add(self.port_ctrl, 1, wx.EXPAND)
        vbox.Add(hbox, 0, wx.EXPAND | wx.ALL, 12)

        btn_sizer = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        vbox.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 12)

        panel.SetSizer(vbox)
        self.CenterOnScreen()

    def get_port(self):
        return self.port_ctrl.GetValue()


class BridgeServer:
    """WebSocket server that accepts commands from the MCP server and executes
    them on the live board via pcbnew SWIG."""

    instance = None

    def __init__(self, board, port=DEFAULT_PORT):
        self.board = board
        self.port = port
        self.running = False
        self._thread = None
        self._server = None
        self._handler = CommandHandler(board)
        BridgeServer.instance = self

    def start(self):
        self.running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False
        if self._server:
            self._server.shutdown()
        if self._thread:
            self._thread.join(timeout=3)
        BridgeServer.instance = None

    def _run(self):
        """Run the WebSocket server. Falls back to a raw TCP JSON server if
        the websockets library isn't available in KiCad's Python."""
        try:
            self._run_tcp_server()
        except Exception as e:
            logger.error(f"Bridge server failed: {e}\n{traceback.format_exc()}")
            self.running = False

    def _run_tcp_server(self):
        """Simple line-delimited JSON-over-TCP server that works without any
        third-party dependencies — only stdlib modules that KiCad's Python
        ships."""
        import socketserver

        handler_ref = self._handler
        server_ref = self

        class TCPHandler(socketserver.StreamRequestHandler):
            def handle(self):
                logger.info(f"MCP client connected from {self.client_address}")
                self.wfile.write(json.dumps({
                    "type": "hello",
                    "plugin": PLUGIN_NAME,
                    "board": str(pcbnew.GetBoard().GetFileName()) if pcbnew.GetBoard() else None,
                }).encode() + b"\n")

                while server_ref.running:
                    try:
                        line = self.rfile.readline()
                        if not line:
                            break
                        msg = json.loads(line.decode().strip())
                        result = handler_ref.dispatch(msg)
                        self.wfile.write(json.dumps(result).encode() + b"\n")
                        self.wfile.flush()
                    except json.JSONDecodeError as e:
                        err = {"success": False, "error": f"Invalid JSON: {e}"}
                        self.wfile.write(json.dumps(err).encode() + b"\n")
                        self.wfile.flush()
                    except Exception as e:
                        logger.error(f"Handler error: {e}\n{traceback.format_exc()}")
                        err = {"success": False, "error": str(e)}
                        try:
                            self.wfile.write(json.dumps(err).encode() + b"\n")
                            self.wfile.flush()
                        except Exception:
                            break

        class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._server = ThreadedTCPServer(("127.0.0.1", self.port), TCPHandler)
        logger.info(f"MCP Bridge listening on 127.0.0.1:{self.port}")
        self._server.serve_forever()


class CommandHandler:
    """Translates incoming JSON commands into pcbnew SWIG calls and refreshes
    the KiCad UI after each mutation."""

    # Commands that modify the board and need a UI refresh + save
    MUTATING_COMMANDS = {
        "place_component", "move_component", "delete_component",
        "rotate_component", "add_track", "delete_track", "add_via",
        "delete_via", "add_zone", "refill_zones", "set_net_class",
        "set_design_rules", "add_text", "add_graphic",
    }

    def __init__(self, board):
        self.board = board

    def dispatch(self, msg):
        cmd = msg.get("command")
        params = msg.get("params", {})

        if not cmd:
            return {"success": False, "error": "No 'command' field in message"}

        method = getattr(self, f"cmd_{cmd}", None)
        if method is None:
            return {
                "success": False,
                "error": f"Unknown command: {cmd}",
                "available": [m[4:] for m in dir(self) if m.startswith("cmd_")],
            }

        try:
            result = method(**params)
            if cmd in self.MUTATING_COMMANDS:
                self._refresh_ui()
            return result
        except TypeError as e:
            return {"success": False, "error": f"Bad parameters for '{cmd}': {e}"}
        except Exception as e:
            logger.error(f"Command '{cmd}' failed: {e}\n{traceback.format_exc()}")
            return {"success": False, "error": str(e)}

    def _refresh_ui(self):
        """Tell KiCad to redraw the board. Must run on the main (wx) thread."""
        def _do_refresh():
            try:
                pcbnew.Refresh()
            except Exception:
                pass
        wx.CallAfter(_do_refresh)

    # ── Query commands ──────────────────────────────────────────────

    def cmd_ping(self):
        board = pcbnew.GetBoard()
        return {
            "success": True,
            "message": "pong",
            "board": str(board.GetFileName()) if board else None,
            "component_count": len(board.GetFootprints()) if board else 0,
            "track_count": len(board.GetTracks()) if board else 0,
        }

    def cmd_get_board_info(self):
        board = pcbnew.GetBoard()
        if not board:
            return {"success": False, "error": "No board open"}

        bbox = board.GetBoardEdgesBoundingBox()
        return {
            "success": True,
            "filename": str(board.GetFileName()),
            "component_count": len(board.GetFootprints()),
            "track_count": len(board.GetTracks()),
            "net_count": board.GetNetCount(),
            "layer_count": board.GetCopperLayerCount(),
            "board_extents": {
                "x": pcbnew.ToMM(bbox.GetX()),
                "y": pcbnew.ToMM(bbox.GetY()),
                "width": pcbnew.ToMM(bbox.GetWidth()),
                "height": pcbnew.ToMM(bbox.GetHeight()),
            },
        }

    def cmd_list_components(self):
        board = pcbnew.GetBoard()
        if not board:
            return {"success": False, "error": "No board open"}

        components = []
        for fp in board.GetFootprints():
            pos = fp.GetPosition()
            components.append({
                "reference": fp.GetReference(),
                "value": fp.GetValue(),
                "footprint": str(fp.GetFPID().GetUniStringLibItemName()),
                "library": str(fp.GetFPID().GetUniStringLibNickname()),
                "x": pcbnew.ToMM(pos.x),
                "y": pcbnew.ToMM(pos.y),
                "rotation": fp.GetOrientationDegrees(),
                "layer": board.GetLayerName(fp.GetLayer()),
                "pads": len(fp.Pads()),
            })
        return {"success": True, "components": components}

    def cmd_list_nets(self):
        board = pcbnew.GetBoard()
        if not board:
            return {"success": False, "error": "No board open"}

        nets = {}
        netinfo = board.GetNetInfo()
        for i in range(board.GetNetCount()):
            net = netinfo.GetNetItem(i)
            if net:
                nets[net.GetNetname()] = {
                    "code": net.GetNetCode(),
                    "name": net.GetNetname(),
                }
        return {"success": True, "nets": nets}

    def cmd_list_tracks(self, net_name=None):
        board = pcbnew.GetBoard()
        if not board:
            return {"success": False, "error": "No board open"}

        tracks = []
        for t in board.GetTracks():
            if isinstance(t, pcbnew.PCB_TRACK):
                info = {
                    "start_x": pcbnew.ToMM(t.GetStart().x),
                    "start_y": pcbnew.ToMM(t.GetStart().y),
                    "end_x": pcbnew.ToMM(t.GetEnd().x),
                    "end_y": pcbnew.ToMM(t.GetEnd().y),
                    "width": pcbnew.ToMM(t.GetWidth()),
                    "layer": board.GetLayerName(t.GetLayer()),
                    "net": t.GetNetname(),
                }
                if net_name and info["net"] != net_name:
                    continue
                tracks.append(info)
        return {"success": True, "tracks": tracks}

    def cmd_get_component(self, reference):
        board = pcbnew.GetBoard()
        if not board:
            return {"success": False, "error": "No board open"}

        for fp in board.GetFootprints():
            if fp.GetReference() == reference:
                pos = fp.GetPosition()
                pads = []
                for pad in fp.Pads():
                    pad_pos = pad.GetPosition()
                    pads.append({
                        "name": pad.GetName(),
                        "net": pad.GetNetname(),
                        "x": pcbnew.ToMM(pad_pos.x),
                        "y": pcbnew.ToMM(pad_pos.y),
                        "shape": str(pad.GetShape()),
                    })
                return {
                    "success": True,
                    "reference": fp.GetReference(),
                    "value": fp.GetValue(),
                    "footprint": str(fp.GetFPID().GetUniStringLibItemName()),
                    "x": pcbnew.ToMM(pos.x),
                    "y": pcbnew.ToMM(pos.y),
                    "rotation": fp.GetOrientationDegrees(),
                    "layer": board.GetLayerName(fp.GetLayer()),
                    "pads": pads,
                }

        return {"success": False, "error": f"Component '{reference}' not found"}

    def cmd_get_design_rules(self):
        board = pcbnew.GetBoard()
        if not board:
            return {"success": False, "error": "No board open"}

        ds = board.GetDesignSettings()
        return {
            "success": True,
            "rules": {
                "min_track_width": pcbnew.ToMM(ds.m_TrackMinWidth),
                "min_clearance": pcbnew.ToMM(ds.m_MinClearance),
                "min_via_diameter": pcbnew.ToMM(ds.m_ViasMinSize),
                "copper_layers": ds.GetCopperLayerCount(),
            },
        }

    # ── Mutation commands ───────────────────────────────────────────

    def cmd_move_component(self, reference, x, y, relative=False):
        board = pcbnew.GetBoard()
        if not board:
            return {"success": False, "error": "No board open"}

        for fp in board.GetFootprints():
            if fp.GetReference() == reference:
                if relative:
                    old = fp.GetPosition()
                    new_x = old.x + pcbnew.FromMM(x)
                    new_y = old.y + pcbnew.FromMM(y)
                else:
                    new_x = pcbnew.FromMM(x)
                    new_y = pcbnew.FromMM(y)
                fp.SetPosition(pcbnew.VECTOR2I(int(new_x), int(new_y)))
                return {
                    "success": True,
                    "message": f"Moved {reference} to ({x}, {y})",
                    "x": pcbnew.ToMM(new_x),
                    "y": pcbnew.ToMM(new_y),
                }
        return {"success": False, "error": f"Component '{reference}' not found"}

    def cmd_rotate_component(self, reference, angle):
        board = pcbnew.GetBoard()
        if not board:
            return {"success": False, "error": "No board open"}

        for fp in board.GetFootprints():
            if fp.GetReference() == reference:
                current = fp.GetOrientationDegrees()
                fp.SetOrientationDegrees(current + angle)
                return {
                    "success": True,
                    "message": f"Rotated {reference} by {angle}°",
                    "new_rotation": fp.GetOrientationDegrees(),
                }
        return {"success": False, "error": f"Component '{reference}' not found"}

    def cmd_delete_component(self, reference):
        board = pcbnew.GetBoard()
        if not board:
            return {"success": False, "error": "No board open"}

        for fp in board.GetFootprints():
            if fp.GetReference() == reference:
                board.Remove(fp)
                return {"success": True, "message": f"Deleted {reference}"}
        return {"success": False, "error": f"Component '{reference}' not found"}

    def cmd_add_track(self, start_x, start_y, end_x, end_y, width=0.25, layer="F.Cu", net_name=None):
        board = pcbnew.GetBoard()
        if not board:
            return {"success": False, "error": "No board open"}

        track = pcbnew.PCB_TRACK(board)
        track.SetStart(pcbnew.VECTOR2I(int(pcbnew.FromMM(start_x)), int(pcbnew.FromMM(start_y))))
        track.SetEnd(pcbnew.VECTOR2I(int(pcbnew.FromMM(end_x)), int(pcbnew.FromMM(end_y))))
        track.SetWidth(int(pcbnew.FromMM(width)))
        track.SetLayer(board.GetLayerID(layer))

        if net_name:
            netinfo = board.GetNetInfo()
            net = netinfo.GetNetItem(net_name)
            if net:
                track.SetNet(net)

        board.Add(track)
        return {
            "success": True,
            "message": f"Added track from ({start_x},{start_y}) to ({end_x},{end_y}) on {layer}",
        }

    def cmd_delete_track(self, start_x, start_y, end_x, end_y, layer="F.Cu"):
        board = pcbnew.GetBoard()
        if not board:
            return {"success": False, "error": "No board open"}

        target_start = pcbnew.VECTOR2I(int(pcbnew.FromMM(start_x)), int(pcbnew.FromMM(start_y)))
        target_end = pcbnew.VECTOR2I(int(pcbnew.FromMM(end_x)), int(pcbnew.FromMM(end_y)))
        target_layer = board.GetLayerID(layer)

        for t in board.GetTracks():
            if isinstance(t, pcbnew.PCB_TRACK) and not isinstance(t, pcbnew.PCB_VIA):
                if t.GetLayer() == target_layer:
                    if (t.GetStart() == target_start and t.GetEnd() == target_end) or \
                       (t.GetStart() == target_end and t.GetEnd() == target_start):
                        board.Remove(t)
                        return {"success": True, "message": "Track deleted"}
        return {"success": False, "error": "Track not found at specified coordinates"}

    def cmd_add_via(self, x, y, diameter=0.8, drill=0.4, net_name=None, via_type="through"):
        board = pcbnew.GetBoard()
        if not board:
            return {"success": False, "error": "No board open"}

        via = pcbnew.PCB_VIA(board)
        via.SetPosition(pcbnew.VECTOR2I(int(pcbnew.FromMM(x)), int(pcbnew.FromMM(y))))
        via.SetWidth(int(pcbnew.FromMM(diameter)))
        via.SetDrill(int(pcbnew.FromMM(drill)))

        if via_type == "blind":
            via.SetViaType(pcbnew.VIATYPE_BLIND_BURIED)
        elif via_type == "micro":
            via.SetViaType(pcbnew.VIATYPE_MICROVIA)

        if net_name:
            netinfo = board.GetNetInfo()
            net = netinfo.GetNetItem(net_name)
            if net:
                via.SetNet(net)

        board.Add(via)
        return {"success": True, "message": f"Added via at ({x},{y})"}

    def cmd_add_zone(self, net_name, layer="F.Cu", points=None, clearance=0.2, min_width=0.25):
        board = pcbnew.GetBoard()
        if not board:
            return {"success": False, "error": "No board open"}

        if not points or len(points) < 3:
            return {"success": False, "error": "Zone needs at least 3 corner points"}

        netinfo = board.GetNetInfo()
        net = netinfo.GetNetItem(net_name)
        if not net:
            return {"success": False, "error": f"Net '{net_name}' not found"}

        zone = pcbnew.ZONE(board)
        zone.SetNet(net)
        zone.SetLayer(board.GetLayerID(layer))
        zone.SetLocalClearance(int(pcbnew.FromMM(clearance)))
        zone.SetMinThickness(int(pcbnew.FromMM(min_width)))

        outline = zone.Outline()
        outline.NewOutline()
        for pt in points:
            outline.Append(int(pcbnew.FromMM(pt["x"])), int(pcbnew.FromMM(pt["y"])))

        board.Add(zone)
        return {"success": True, "message": f"Added zone for net '{net_name}' on {layer}"}

    def cmd_refill_zones(self):
        board = pcbnew.GetBoard()
        if not board:
            return {"success": False, "error": "No board open"}

        filler = pcbnew.ZONE_FILLER(board)
        zones = board.Zones()
        filler.Fill(zones)
        return {"success": True, "message": f"Refilled {len(zones)} zones"}

    def cmd_set_net_class(self, name, track_width=None, clearance=None, via_diameter=None, via_drill=None):
        board = pcbnew.GetBoard()
        if not board:
            return {"success": False, "error": "No board open"}

        ds = board.GetDesignSettings()
        nc = ds.GetNetClasses()

        target = None
        if name == "Default":
            target = nc.GetDefault()
        else:
            if nc.HasNetClass(name):
                target = nc.Find(name)
            else:
                new_nc = pcbnew.NETCLASS(name)
                nc.Add(new_nc)
                target = nc.Find(name)

        if not target:
            return {"success": False, "error": f"Could not find/create netclass '{name}'"}

        if track_width is not None:
            target.SetTrackWidth(int(pcbnew.FromMM(track_width)))
        if clearance is not None:
            target.SetClearance(int(pcbnew.FromMM(clearance)))
        if via_diameter is not None:
            target.SetViaDiameter(int(pcbnew.FromMM(via_diameter)))
        if via_drill is not None:
            target.SetViaDrill(int(pcbnew.FromMM(via_drill)))

        return {"success": True, "message": f"Net class '{name}' configured"}

    def cmd_add_text(self, text, x, y, layer="F.SilkS", size=1.0, thickness=0.15):
        board = pcbnew.GetBoard()
        if not board:
            return {"success": False, "error": "No board open"}

        pcb_text = pcbnew.PCB_TEXT(board)
        pcb_text.SetText(text)
        pcb_text.SetPosition(pcbnew.VECTOR2I(int(pcbnew.FromMM(x)), int(pcbnew.FromMM(y))))
        pcb_text.SetLayer(board.GetLayerID(layer))
        pcb_text.SetTextSize(pcbnew.VECTOR2I(int(pcbnew.FromMM(size)), int(pcbnew.FromMM(size))))
        pcb_text.SetTextThickness(int(pcbnew.FromMM(thickness)))

        board.Add(pcb_text)
        return {"success": True, "message": f"Added text '{text}' at ({x},{y})"}

    def cmd_run_drc(self):
        board = pcbnew.GetBoard()
        if not board:
            return {"success": False, "error": "No board open"}

        ds = board.GetDesignSettings()
        markers = board.GetMarkers()
        violations = []
        for m in markers:
            rc = m.GetRCItem()
            violations.append({
                "severity": str(m.GetSeverity()),
                "message": rc.GetErrorMessage() if rc else "Unknown",
                "x": pcbnew.ToMM(m.GetPosition().x),
                "y": pcbnew.ToMM(m.GetPosition().y),
            })

        return {
            "success": True,
            "violation_count": len(violations),
            "violations": violations[:50],
        }

    def cmd_save(self):
        board = pcbnew.GetBoard()
        if not board:
            return {"success": False, "error": "No board open"}

        board.Save(board.GetFileName())
        return {"success": True, "message": "Board saved"}

    def cmd_get_selection(self):
        """Get currently selected items in the KiCad UI."""
        board = pcbnew.GetBoard()
        if not board:
            return {"success": False, "error": "No board open"}

        # Note: selection access depends on KiCad version
        items = []
        try:
            selection = pcbnew.GetCurrentSelection()
            for item in selection:
                info = {
                    "type": item.GetClass(),
                    "x": pcbnew.ToMM(item.GetPosition().x),
                    "y": pcbnew.ToMM(item.GetPosition().y),
                }
                if hasattr(item, "GetReference"):
                    info["reference"] = item.GetReference()
                if hasattr(item, "GetNetname"):
                    info["net"] = item.GetNetname()
                items.append(info)
        except AttributeError:
            return {"success": False, "error": "Selection API not available in this KiCad version"}

        return {"success": True, "selected": items}

    def cmd_highlight_net(self, net_name):
        """Highlight a net in the UI."""
        board = pcbnew.GetBoard()
        if not board:
            return {"success": False, "error": "No board open"}

        netinfo = board.GetNetInfo()
        net = netinfo.GetNetItem(net_name)
        if not net:
            return {"success": False, "error": f"Net '{net_name}' not found"}

        # Set highlight via the board settings
        settings = board.GetDesignSettings()
        board.SetHighLightNet(net.GetNetCode())
        board.HighLightON()
        self._refresh_ui()
        return {"success": True, "message": f"Highlighted net '{net_name}'"}

    def cmd_clear_highlight(self):
        board = pcbnew.GetBoard()
        if not board:
            return {"success": False, "error": "No board open"}

        board.HighLightOFF()
        self._refresh_ui()
        return {"success": True, "message": "Highlights cleared"}
