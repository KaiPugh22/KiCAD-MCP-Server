/**
 * A* PCB Router Tools
 * Provides Rust-accelerated A* grid routing via KiCadRoutingTools
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerAStarRouterTools(
  server: McpServer,
  callKicadScript: (cmd: string, args: Record<string, unknown>) => Promise<string>
) {
  server.tool(
    "astar_route",
    `Route nets using A* grid pathfinding (Rust-accelerated).
Handles single-ended nets with configurable grid resolution, via costs,
bus detection, and rip-up-and-reroute. Much faster than Freerouting for
targeted net routing. Writes output to a new .kicad_pcb file.`,
    {
      net_names: z.array(z.string()).optional()
        .describe("Specific nets to route (routes all unrouted if omitted)"),
      board_path: z.string().optional()
        .describe("Path to .kicad_pcb (uses current board if omitted)"),
      output_path: z.string().optional()
        .describe("Output .kicad_pcb path (default: <stem>.routed.kicad_pcb)"),
      layers: z.array(z.string()).optional()
        .describe("Layers to route on (e.g. ['F.Cu', 'B.Cu'])"),
      grid_step: z.number().optional()
        .describe("Grid resolution in mm (default 0.1, smaller = finer but slower)"),
      max_iterations: z.number().optional()
        .describe("Max A* iterations per net (default 200000)"),
      track_width: z.number().optional()
        .describe("Track width in mm (default from design rules)"),
      clearance: z.number().optional()
        .describe("Clearance in mm (default from design rules)"),
      via_size: z.number().optional()
        .describe("Via diameter in mm"),
      via_drill: z.number().optional()
        .describe("Via drill size in mm"),
      via_cost: z.number().optional()
        .describe("Via penalty for A* (higher = fewer vias, default 80)"),
      bus_enabled: z.boolean().optional()
        .describe("Enable bus-aware routing (parallel track attraction)"),
      bus_detection_radius: z.number().optional()
        .describe("Bus detection radius in mm (default 5.0)"),
      track_width_from_class: z.boolean().optional()
        .describe("Use track width from net class assignments"),
      timeout: z.number().optional()
        .describe("Total timeout in seconds (default 600)"),
    },
    async (args) => {
      const result = await callKicadScript("astar_route", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "astar_route_differential",
    `Route differential pairs using A* with Dubins curves.
Supports USB, HDMI, Ethernet, PCIe differential pairs with configurable
spacing and impedance-matched track widths.`,
    {
      pair_nets: z.array(z.array(z.string()).length(2)).optional()
        .describe("Differential pairs as [[pos_net, neg_net], ...] (auto-detects if omitted)"),
      board_path: z.string().optional()
        .describe("Path to .kicad_pcb"),
      output_path: z.string().optional()
        .describe("Output path (default: <stem>.diffrouted.kicad_pcb)"),
      spacing: z.number().optional()
        .describe("Pair spacing in mm"),
      track_width: z.number().optional()
        .describe("Track width in mm"),
      timeout: z.number().optional()
        .describe("Timeout in seconds (default 600)"),
    },
    async (args) => {
      const result = await callKicadScript("astar_route_differential", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "check_astar_router",
    "Check if the A* router (KiCadRoutingTools) is installed with the Rust module built",
    {},
    async () => {
      const result = await callKicadScript("check_astar_router", {});
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "install_astar_router",
    "Download and install KiCadRoutingTools (Rust A* router). Requires Rust toolchain for the grid_router module.",
    {
      force: z.boolean().optional().describe("Force reinstall"),
    },
    async (args) => {
      const result = await callKicadScript("install_astar_router", args);
      return { content: [{ type: "text", text: result }] };
    }
  );
}
