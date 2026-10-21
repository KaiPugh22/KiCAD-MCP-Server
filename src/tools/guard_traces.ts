/**
 * Differential Pair Guard Trace Tools
 * Auto-insert grounded guard traces flanking diff pairs
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerGuardTraceTools(
  server: McpServer,
  callKicadScript: (cmd: string, args: Record<string, unknown>) => Promise<string>
) {
  server.tool(
    "find_diff_pairs",
    `Find differential pairs on the board by net naming patterns.
Detects USB, HDMI, Ethernet, LVDS pairs and checks if they
already have guard traces.`,
    {},
    async () => {
      const result = await callKicadScript("find_diff_pairs", {});
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "add_guard_traces",
    `Add grounded guard traces flanking a differential pair with
via stitching at endpoints. Spacing is auto-calculated from the
pair type (USB2/USB3/HDMI/Ethernet/LVDS) or can be overridden.`,
    {
      positive_net: z.string().describe("Positive net name (e.g. 'USB_D+')"),
      negative_net: z.string().describe("Negative net name (e.g. 'USB_D-')"),
      guard_net: z.string().optional()
        .describe("Net for guard traces (default 'GND')"),
      guard_spacing_mm: z.number().optional()
        .describe("Spacing from diff pair to guard trace in mm (auto from pair type)"),
      guard_width_mm: z.number().optional()
        .describe("Guard trace width in mm (auto from pair type)"),
      add_stitching_vias: z.boolean().optional()
        .describe("Add ground vias at guard trace endpoints (default true)"),
      via_pitch_mm: z.number().optional()
        .describe("Stitching via spacing in mm (default 3.0)"),
    },
    async (args) => {
      const result = await callKicadScript("add_guard_traces", args);
      return { content: [{ type: "text", text: result }] };
    }
  );
}
