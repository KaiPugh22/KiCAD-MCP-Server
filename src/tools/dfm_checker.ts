/**
 * DFM (Design for Manufacturing) Checker Tools
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerDFMCheckerTools(
  server: McpServer,
  callKicadScript: (cmd: string, args: Record<string, unknown>) => Promise<string>
) {
  server.tool(
    "run_dfm_check",
    "Run DFM checks against a specific fab house (JLCPCB, OSH Park, PCBWay) — checks trace widths, drill sizes, annular rings, board edge clearance, and more",
    {
      fab_house: z
        .enum(["jlcpcb_standard", "jlcpcb_advanced", "oshpark", "pcbway_standard"])
        .optional()
        .describe("Target fab house preset (default jlcpcb_standard)"),
      board_thickness: z
        .number()
        .optional()
        .describe("Board thickness in mm for drill aspect ratio check (default 1.6)"),
    },
    async (args) => {
      const result = await callKicadScript("run_dfm_check", {
        fab_house: args.fab_house ?? "jlcpcb_standard",
        board_thickness: args.board_thickness ?? 1.6,
      });
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "check_unconnected_nets",
    "Find nets with only one connection point (likely unconnected pins or missing traces)",
    {},
    async () => {
      const result = await callKicadScript("check_unconnected_nets", {});
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "check_silk_clearance",
    "Check for silkscreen text overlapping component pads",
    {
      min_clearance_mm: z
        .number()
        .optional()
        .describe("Minimum silk-to-pad clearance in mm (default 0.15)"),
    },
    async (args) => {
      const result = await callKicadScript("check_silk_clearance", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "list_fab_presets",
    "List available fabrication house presets and their manufacturing constraints",
    {},
    async () => {
      const result = await callKicadScript("list_fab_presets", {});
      return { content: [{ type: "text", text: result }] };
    }
  );
}
