/**
 * Bus-Aware Component Ordering Tools
 * Detect buses and reorder components to eliminate net crossings
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerBusOrderingTools(
  server: McpServer,
  callKicadScript: (cmd: string, args: Record<string, unknown>) => Promise<string>
) {
  server.tool(
    "detect_bus_groups",
    `Detect bus-connected component groups on the board. Identifies
data buses (D0-D7, ADDR[0:15], GPIO_0..N) by net naming patterns,
finds the source IC and destination components.`,
    {
      min_bus_width: z.number().optional()
        .describe("Minimum number of nets to be considered a bus (default 2)"),
    },
    async (args) => {
      const result = await callKicadScript("detect_bus_groups", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "reorder_bus_components",
    `Analyze and suggest component reordering to match source IC pin order
and minimize net crossings for a specific bus.`,
    {
      bus_prefix: z.string().describe("Bus prefix (e.g. 'D', 'ADDR', 'GPIO_')"),
      source_ref: z.string().optional()
        .describe("Source component ref (auto-detected if omitted)"),
      target_refs: z.array(z.string()).optional()
        .describe("Target component refs to reorder (auto-detected if omitted)"),
      axis: z.enum(["auto", "x", "y"]).optional()
        .describe("Axis to order along (default 'auto')"),
    },
    async (args) => {
      const result = await callKicadScript("reorder_bus_components", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "analyze_crossing_count",
    "Count net crossings for all detected buses and report which ones benefit most from reordering",
    {
      min_bus_width: z.number().optional()
        .describe("Minimum bus width (default 2)"),
    },
    async (args) => {
      const result = await callKicadScript("analyze_crossing_count", args);
      return { content: [{ type: "text", text: result }] };
    }
  );
}
