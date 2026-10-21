/**
 * Return Path Analyzer Tools
 * Check reference plane continuity under signal traces
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerReturnPathTools(
  server: McpServer,
  callKicadScript: (cmd: string, args: Record<string, unknown>) => Promise<string>
) {
  server.tool(
    "analyze_return_paths",
    `Analyze return path continuity for signal traces. Finds layer
transitions without nearby stitching vias and traces without a
reference plane underneath. Critical for EMC compliance.`,
    {
      nets: z.array(z.string()).optional()
        .describe("Specific nets to analyze (all signal nets if omitted)"),
      via_search_radius_mm: z.number().optional()
        .describe("Radius to search for stitching vias in mm (default 2.0)"),
      ref_plane_nets: z.array(z.string()).optional()
        .describe("Reference plane net names (default ['GND'])"),
    },
    async (args) => {
      const result = await callKicadScript("analyze_return_paths", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "check_signal_over_split",
    "Check if a specific signal crosses over a plane split",
    {
      net: z.string().describe("Net name to check"),
    },
    async (args) => {
      const result = await callKicadScript("check_signal_over_split", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "suggest_stitching_locations",
    `Suggest where to add stitching vias based on return path analysis.
Returns locations where layer transitions lack nearby ground vias.`,
    {
      nets: z.array(z.string()).optional()
        .describe("Specific nets to analyze"),
      ref_plane_nets: z.array(z.string()).optional()
        .describe("Reference plane nets (default ['GND'])"),
    },
    async (args) => {
      const result = await callKicadScript("suggest_stitching_locations", args);
      return { content: [{ type: "text", text: result }] };
    }
  );
}
