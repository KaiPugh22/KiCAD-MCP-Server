/**
 * Trace Length Matching Tools
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerLengthMatchingTools(
  server: McpServer,
  callKicadScript: (cmd: string, args: Record<string, unknown>) => Promise<string>
) {
  server.tool(
    "measure_net_lengths",
    "Measure total routed trace length for a group of nets (for length matching verification)",
    {
      net_names: z
        .array(z.string())
        .describe("List of net names to measure"),
    },
    async ({ net_names }) => {
      const result = await callKicadScript("measure_net_lengths", { net_names });
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "check_length_matching",
    "Check if a group of nets are length-matched within tolerance (for DDR, USB, HDMI, etc.)",
    {
      net_names: z
        .array(z.string())
        .describe("Nets that should be length-matched"),
      tolerance_mm: z
        .number()
        .optional()
        .describe("Maximum allowed length difference in mm (default 2.0)"),
      reference_net: z
        .string()
        .optional()
        .describe("Net to match against (default: longest net)"),
    },
    async (args) => {
      const result = await callKicadScript("check_length_matching", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "auto_detect_bus_groups",
    "Auto-detect bus groups on the board (DDR, USB, HDMI, Ethernet, PCIe) by matching net name patterns",
    {},
    async () => {
      const result = await callKicadScript("auto_detect_bus_groups", {});
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "add_serpentine",
    "Add serpentine/meander tuning to a trace to increase its length for length matching",
    {
      net_name: z.string().describe("Net to add serpentine to"),
      target_length_mm: z.number().describe("Desired total net length after tuning"),
      amplitude_mm: z
        .number()
        .optional()
        .describe("Serpentine peak-to-peak amplitude in mm (default 0.5)"),
      segment_length_mm: z
        .number()
        .optional()
        .describe("Length of each serpentine segment in mm (default 1.0)"),
      layer: z
        .string()
        .optional()
        .describe("Layer to add serpentine on (default F.Cu)"),
    },
    async (args) => {
      const result = await callKicadScript("add_serpentine", args);
      return { content: [{ type: "text", text: result }] };
    }
  );
}
