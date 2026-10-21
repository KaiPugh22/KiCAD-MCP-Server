/**
 * Component Placement Optimizer Tools
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerPlacementTools(
  server: McpServer,
  callKicadScript: (cmd: string, args: Record<string, unknown>) => Promise<string>
) {
  server.tool(
    "auto_place_bypass_caps",
    "Automatically place bypass/decoupling capacitors near their associated ICs based on net connectivity",
    {
      max_distance_mm: z
        .number()
        .optional()
        .describe("Maximum distance from IC power pin (default 3mm)"),
      preferred_side: z
        .enum(["same", "opposite"])
        .optional()
        .describe("Place on same or opposite layer as IC"),
      grid_pitch: z
        .number()
        .optional()
        .describe("Snap-to-grid pitch in mm (default 0.5)"),
    },
    async (args) => {
      const result = await callKicadScript("auto_place_bypass_caps", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "group_components_by_function",
    "Analyze board and group components by function (ICs, power, bypass, signal, connectors, crystals)",
    {},
    async () => {
      const result = await callKicadScript("group_by_function", {});
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "optimize_placement",
    "Optimize component placement to minimize ratsnest length using simulated annealing",
    {
      references: z
        .array(z.string())
        .optional()
        .describe("Components to optimize (omit for all unlocked)"),
      iterations: z
        .number()
        .optional()
        .describe("Optimization iterations (default 100, more = better)"),
      grid_pitch: z
        .number()
        .optional()
        .describe("Grid snap pitch in mm (default 0.5)"),
      dry_run: z
        .boolean()
        .optional()
        .describe("If true (default), only report improvements without moving"),
    },
    async (args) => {
      const result = await callKicadScript("optimize_placement", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "arrange_in_line",
    "Arrange components in a horizontal or vertical line with even spacing",
    {
      references: z
        .array(z.string())
        .describe("Component references to arrange"),
      start_x: z.number().describe("Starting X position in mm"),
      start_y: z.number().describe("Starting Y position in mm"),
      direction: z
        .enum(["horizontal", "vertical"])
        .optional()
        .describe("Arrangement direction (default horizontal)"),
      spacing_mm: z
        .number()
        .optional()
        .describe("Center-to-center spacing in mm (default 2.0)"),
    },
    async (args) => {
      const result = await callKicadScript("arrange_in_line", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "spread_components",
    "Spread all overlapping components apart on a grid (useful as first step before optimization)",
    {
      spacing_mm: z
        .number()
        .optional()
        .describe("Minimum spacing between centers in mm (default 5)"),
      center_x: z
        .number()
        .optional()
        .describe("Center X of spread area in mm (default 100)"),
      center_y: z
        .number()
        .optional()
        .describe("Center Y of spread area in mm (default 100)"),
    },
    async (args) => {
      const result = await callKicadScript("spread_components", args);
      return { content: [{ type: "text", text: result }] };
    }
  );
}
