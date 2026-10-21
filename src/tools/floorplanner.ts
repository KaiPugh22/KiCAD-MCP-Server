/**
 * Floorplanner Tools
 * Generate spatial floorplans from component analysis
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerFloorplannerTools(
  server: McpServer,
  callKicadScript: (cmd: string, args: Record<string, unknown>) => Promise<string>
) {
  server.tool(
    "analyze_functional_blocks",
    `Classify all board components into functional blocks: power, analog,
digital, RF, connectors, passives. Uses component values, reference
designators, and connected net names for classification.`,
    {},
    async () => {
      const result = await callKicadScript("analyze_functional_blocks", {});
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "generate_floorplan",
    `Generate a spatial floorplan with zone assignments. Places connectors
on edges, isolates power and analog sections, centers digital.
Use dry_run=true (default) to preview before applying.`,
    {
      board_margin_mm: z.number().optional()
        .describe("Board edge margin in mm (default 2.0)"),
      connector_edge: z.enum(["left", "right", "top", "bottom"]).optional()
        .describe("Edge for connectors (default 'left')"),
      power_position: z.enum(["top_left", "top_right", "bottom_left", "bottom_right"]).optional()
        .describe("Zone for power section (default 'top_right')"),
      analog_position: z.enum(["top_left", "top_right", "bottom_left", "bottom_right"]).optional()
        .describe("Zone for analog section (default 'bottom_left')"),
      dry_run: z.boolean().optional()
        .describe("Preview only, don't move components (default true)"),
    },
    async (args) => {
      const result = await callKicadScript("generate_floorplan", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "estimate_board_size",
    `Estimate minimum board size from component areas and count.
Uses a packing factor to account for routing and clearance.`,
    {
      packing_factor: z.number().optional()
        .describe("Component area / board area ratio (default 0.4, lower = more space)"),
      aspect_ratio: z.number().optional()
        .describe("Width/height ratio (default 1.0 = square)"),
    },
    async (args) => {
      const result = await callKicadScript("estimate_board_size", args);
      return { content: [{ type: "text", text: result }] };
    }
  );
}
