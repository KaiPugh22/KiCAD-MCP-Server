/**
 * KiCad Live Bridge Tools
 *
 * MCP tool registrations for the real-time bridge to the KiCad plugin.
 * These tools connect to the TCP server running inside KiCad and send
 * commands that execute immediately on the open board.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import * as net from "net";

const BRIDGE_PORT = 9876;
const BRIDGE_HOST = "127.0.0.1";
const TIMEOUT_MS = 10000;

/**
 * Send a JSON command to the KiCad bridge plugin and return the response.
 */
async function bridgeCommand(
  command: string,
  params: Record<string, unknown> = {}
): Promise<Record<string, unknown>> {
  return new Promise((resolve, reject) => {
    const client = new net.Socket();
    let buffer = "";
    let gotHello = false;
    const timer = setTimeout(() => {
      client.destroy();
      reject(new Error("Bridge command timed out"));
    }, TIMEOUT_MS);

    client.connect(BRIDGE_PORT, BRIDGE_HOST, () => {
      // Wait for hello, then send command
    });

    client.on("data", (data) => {
      buffer += data.toString();
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const msg = JSON.parse(line);
          if (!gotHello) {
            // First message is the hello
            gotHello = true;
            // Now send our command
            client.write(
              JSON.stringify({ command, params }) + "\n"
            );
          } else {
            clearTimeout(timer);
            client.destroy();
            resolve(msg);
          }
        } catch {
          // Ignore malformed lines
        }
      }
    });

    client.on("error", (err) => {
      clearTimeout(timer);
      reject(
        new Error(
          `Cannot connect to KiCad bridge on port ${BRIDGE_PORT}. ` +
            `Make sure the MCP AI Bridge plugin is running in KiCad. ` +
            `Error: ${err.message}`
        )
      );
    });

    client.on("close", () => {
      clearTimeout(timer);
    });
  });
}

export function registerBridgeTools(
  server: McpServer,
  _callKicadScript: (cmd: string, args: Record<string, unknown>) => Promise<string>
) {
  // -- Connection test --
  server.tool(
    "bridge_ping",
    "Test connection to the KiCad live bridge plugin",
    {},
    async () => {
      try {
        const result = await bridgeCommand("ping");
        return {
          content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
        };
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        return {
          content: [{ type: "text", text: `Bridge not available: ${msg}` }],
          isError: true,
        };
      }
    }
  );

  // -- Board info --
  server.tool(
    "bridge_get_board_info",
    "Get live board info from KiCad (component count, nets, extents)",
    {},
    async () => {
      const result = await bridgeCommand("get_board_info");
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    }
  );

  // -- Live component list --
  server.tool(
    "bridge_list_components",
    "List all components on the board currently open in KiCad",
    {},
    async () => {
      const result = await bridgeCommand("list_components");
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    }
  );

  // -- Move component --
  server.tool(
    "bridge_move_component",
    "Move a component on the live board in KiCad. Changes appear instantly.",
    {
      reference: z.string().describe("Component reference (e.g. R1, U1)"),
      x: z.number().describe("Target X position in mm"),
      y: z.number().describe("Target Y position in mm"),
      relative: z
        .boolean()
        .optional()
        .describe("If true, x/y are relative offsets from current position"),
    },
    async ({ reference, x, y, relative }) => {
      const result = await bridgeCommand("move_component", {
        reference,
        x,
        y,
        relative: relative ?? false,
      });
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    }
  );

  // -- Rotate component --
  server.tool(
    "bridge_rotate_component",
    "Rotate a component on the live board in KiCad",
    {
      reference: z.string().describe("Component reference (e.g. R1, U1)"),
      angle: z.number().describe("Rotation angle in degrees (added to current)"),
    },
    async ({ reference, angle }) => {
      const result = await bridgeCommand("rotate_component", {
        reference,
        angle,
      });
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    }
  );

  // -- Add track --
  server.tool(
    "bridge_add_track",
    "Add a trace/track to the live board in KiCad. Appears instantly.",
    {
      start_x: z.number().describe("Start X in mm"),
      start_y: z.number().describe("Start Y in mm"),
      end_x: z.number().describe("End X in mm"),
      end_y: z.number().describe("End Y in mm"),
      width: z.number().optional().describe("Track width in mm (default 0.25)"),
      layer: z.string().optional().describe("Layer name (default F.Cu)"),
      net_name: z.string().optional().describe("Net to assign the track to"),
    },
    async ({ start_x, start_y, end_x, end_y, width, layer, net_name }) => {
      const result = await bridgeCommand("add_track", {
        start_x,
        start_y,
        end_x,
        end_y,
        width: width ?? 0.25,
        layer: layer ?? "F.Cu",
        net_name,
      });
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    }
  );

  // -- Add via --
  server.tool(
    "bridge_add_via",
    "Add a via to the live board in KiCad",
    {
      x: z.number().describe("X position in mm"),
      y: z.number().describe("Y position in mm"),
      diameter: z.number().optional().describe("Via diameter in mm (default 0.8)"),
      drill: z.number().optional().describe("Drill diameter in mm (default 0.4)"),
      net_name: z.string().optional().describe("Net to assign"),
      via_type: z
        .enum(["through", "blind", "micro"])
        .optional()
        .describe("Via type"),
    },
    async ({ x, y, diameter, drill, net_name, via_type }) => {
      const result = await bridgeCommand("add_via", {
        x,
        y,
        diameter: diameter ?? 0.8,
        drill: drill ?? 0.4,
        net_name,
        via_type: via_type ?? "through",
      });
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    }
  );

  // -- Add zone --
  server.tool(
    "bridge_add_zone",
    "Add a copper zone/pour to the live board in KiCad",
    {
      net_name: z.string().describe("Net name for the zone (e.g. GND)"),
      layer: z.string().optional().describe("Layer (default F.Cu)"),
      points: z
        .array(z.object({ x: z.number(), y: z.number() }))
        .min(3)
        .describe("Corner points of the zone polygon in mm"),
      clearance: z.number().optional().describe("Zone clearance in mm"),
      min_width: z.number().optional().describe("Min copper width in mm"),
    },
    async ({ net_name, layer, points, clearance, min_width }) => {
      const result = await bridgeCommand("add_zone", {
        net_name,
        layer: layer ?? "F.Cu",
        points,
        clearance: clearance ?? 0.2,
        min_width: min_width ?? 0.25,
      });
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    }
  );

  // -- Highlight net --
  server.tool(
    "bridge_highlight_net",
    "Highlight a net in KiCad's UI so the user can see it",
    {
      net_name: z.string().describe("Net to highlight"),
    },
    async ({ net_name }) => {
      const result = await bridgeCommand("highlight_net", { net_name });
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    }
  );

  // -- Clear highlight --
  server.tool(
    "bridge_clear_highlight",
    "Clear all net highlights in KiCad",
    {},
    async () => {
      const result = await bridgeCommand("clear_highlight");
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    }
  );

  // -- Get component detail --
  server.tool(
    "bridge_get_component",
    "Get detailed info about a specific component on the live board, including pads",
    {
      reference: z.string().describe("Component reference (e.g. U1)"),
    },
    async ({ reference }) => {
      const result = await bridgeCommand("get_component", { reference });
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    }
  );

  // -- List nets --
  server.tool(
    "bridge_list_nets",
    "List all nets on the live board in KiCad",
    {},
    async () => {
      const result = await bridgeCommand("list_nets");
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    }
  );

  // -- Save board --
  server.tool(
    "bridge_save",
    "Save the board currently open in KiCad",
    {},
    async () => {
      const result = await bridgeCommand("save");
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    }
  );

  // -- Set net class --
  server.tool(
    "bridge_set_net_class",
    "Create or modify a net class on the live board in KiCad",
    {
      name: z.string().describe("Net class name"),
      track_width: z.number().optional().describe("Track width in mm"),
      clearance: z.number().optional().describe("Clearance in mm"),
      via_diameter: z.number().optional().describe("Via diameter in mm"),
      via_drill: z.number().optional().describe("Via drill in mm"),
    },
    async ({ name, track_width, clearance, via_diameter, via_drill }) => {
      const result = await bridgeCommand("set_net_class", {
        name,
        track_width,
        clearance,
        via_diameter,
        via_drill,
      });
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    }
  );

  // -- Run DRC --
  server.tool(
    "bridge_run_drc",
    "Get current DRC violations from the live board in KiCad",
    {},
    async () => {
      const result = await bridgeCommand("run_drc");
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    }
  );

  // -- Get selection --
  server.tool(
    "bridge_get_selection",
    "Get the items currently selected in KiCad's UI",
    {},
    async () => {
      const result = await bridgeCommand("get_selection");
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    }
  );

  // -- Add text --
  server.tool(
    "bridge_add_text",
    "Add text to the live board in KiCad (silkscreen labels, fab notes, etc.)",
    {
      text: z.string().describe("Text content"),
      x: z.number().describe("X position in mm"),
      y: z.number().describe("Y position in mm"),
      layer: z.string().optional().describe("Layer (default F.SilkS)"),
      size: z.number().optional().describe("Text size in mm (default 1.0)"),
    },
    async ({ text, x, y, layer, size }) => {
      const result = await bridgeCommand("add_text", {
        text,
        x,
        y,
        layer: layer ?? "F.SilkS",
        size: size ?? 1.0,
      });
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    }
  );
}
