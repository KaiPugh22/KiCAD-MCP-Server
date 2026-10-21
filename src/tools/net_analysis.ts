/**
 * Net Analysis & Connectivity Intelligence Tools
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerNetAnalysisTools(
  server: McpServer,
  callKicadScript: (cmd: string, args: Record<string, unknown>) => Promise<string>
) {
  server.tool(
    "trace_net",
    "Trace a net through the board: show all connected components, pads, tracks, vias, and total length",
    {
      net_name: z.string().describe("Net name to trace (e.g. GND, VCC, Net-U1-PA0)"),
    },
    async ({ net_name }) => {
      const result = await callKicadScript("trace_net", { net_name });
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "find_longest_ratsnest",
    "Find the longest unrouted connections — these represent the hardest routing challenges",
    {
      limit: z.number().optional().describe("Number of results (default 10)"),
    },
    async (args) => {
      const result = await callKicadScript("find_longest_ratsnest", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "find_bottleneck_traces",
    "Find traces that may be too narrow for their net (current bottlenecks on power nets)",
    {
      limit: z.number().optional().describe("Number of results (default 10)"),
    },
    async (args) => {
      const result = await callKicadScript("find_bottleneck_traces", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "net_length_report",
    "Generate a report of total routed trace length per net (useful for length matching)",
    {},
    async () => {
      const result = await callKicadScript("net_length_report", {});
      return { content: [{ type: "text", text: result }] };
    }
  );
}
