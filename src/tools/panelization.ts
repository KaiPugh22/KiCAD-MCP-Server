/**
 * Panelization Tools
 * Panel layout calculation, KiKit integration, and fiducial placement
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerPanelizationTools(
  server: McpServer,
  callKicadScript: (cmd: string, args: Record<string, unknown>) => Promise<string>
) {
  server.tool(
    "calculate_panel_layout",
    `Calculate optimal panel layout for PCB fabrication. Finds best
rows x columns configuration, checks rotated layout for higher yield,
and enforces JLCPCB panel size constraints (70-400mm).`,
    {
      board_width_mm: z.number().optional()
        .describe("Board width in mm (auto-detected if omitted)"),
      board_height_mm: z.number().optional()
        .describe("Board height in mm (auto-detected if omitted)"),
      separation_mm: z.union([z.string(), z.number()]).optional()
        .describe("'v_score', 'mouse_bite', or gap in mm (default 'v_score')"),
      add_rails: z.boolean().optional()
        .describe("Add assembly rails (default true)"),
      rail_width_mm: z.number().optional()
        .describe("Rail width in mm (default 5.0)"),
      target_quantity: z.number().optional()
        .describe("Target board quantity for production estimate"),
      max_panel_width_mm: z.number().optional()
        .describe("Override max panel width"),
      max_panel_height_mm: z.number().optional()
        .describe("Override max panel height"),
    },
    async (args) => {
      const result = await callKicadScript("calculate_panel_layout", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "generate_panel",
    `Generate a panelized KiCad PCB file. Uses KiKit CLI if installed,
otherwise returns manual instructions with the calculated layout.
Supports tabs, mouse bites, rails, fiducials, and tooling holes.`,
    {
      rows: z.number().optional().describe("Number of rows (default 2)"),
      cols: z.number().optional().describe("Number of columns (default 2)"),
      gap_mm: z.number().optional().describe("Gap between boards in mm (default 2.0)"),
      add_rails: z.boolean().optional().describe("Add assembly rails (default true)"),
      rail_width_mm: z.number().optional().describe("Rail width in mm (default 5.0)"),
      add_fiducials: z.boolean().optional().describe("Add fiducial markers (default true)"),
      add_tooling_holes: z.boolean().optional().describe("Add tooling holes (default true)"),
      output_path: z.string().optional().describe("Output file path"),
    },
    async (args) => {
      const result = await callKicadScript("generate_panel", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "add_fiducials",
    `Add assembly fiducial markers to the board. Places circular
copper pads with solder mask clearance at board corners for
pick-and-place machine alignment.`,
    {
      count: z.number().optional()
        .describe("Number of fiducials (default 3)"),
      diameter_mm: z.number().optional()
        .describe("Copper pad diameter in mm (default 1.0)"),
      clearance_mm: z.number().optional()
        .describe("Solder mask clearance in mm (default 2.0)"),
      placement: z.enum(["corners", "custom"]).optional()
        .describe("Placement mode (default 'corners')"),
      side: z.enum(["front", "back", "both"]).optional()
        .describe("Board side (default 'both')"),
      positions: z.array(z.object({ x: z.number(), y: z.number() })).optional()
        .describe("Custom positions [{x,y},...] in mm"),
    },
    async (args) => {
      const result = await callKicadScript("add_fiducials", args);
      return { content: [{ type: "text", text: result }] };
    }
  );
}
