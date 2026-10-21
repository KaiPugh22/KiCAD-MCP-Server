/**
 * Test Point Management Tools
 * Suggest, place, and audit test points for DFT compliance
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerTestPointTools(
  server: McpServer,
  callKicadScript: (cmd: string, args: Record<string, unknown>) => Promise<string>
) {
  server.tool(
    "suggest_test_points",
    `Identify nets that should have test points. Categorizes into power,
debug (SWD/JTAG), communication (I2C/SPI/UART), and custom nets.
Checks which critical nets already have test points.`,
    {
      include_power: z.boolean().optional()
        .describe("Include power rail nets (default true)"),
      include_debug: z.boolean().optional()
        .describe("Include debug interface nets (default true)"),
      include_comms: z.boolean().optional()
        .describe("Include communication bus nets (default true)"),
      custom_nets: z.array(z.string()).optional()
        .describe("Additional net names to include"),
      exclude_nets: z.array(z.string()).optional()
        .describe("Net names to exclude from suggestions"),
    },
    async (args) => {
      const result = await callKicadScript("suggest_test_points", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "add_test_points",
    `Add test point footprints to specified nets on the PCB.
Supports SMD pads, through-hole pads, or pad-only styles.
Places test points to the right of the board for manual repositioning.`,
    {
      net_names: z.array(z.string())
        .describe("Net names to add test points to"),
      style: z.enum(["smd", "through_hole", "pad_only"]).optional()
        .describe("Test point style (default 'smd')"),
      size_mm: z.number().optional()
        .describe("Pad diameter in mm (default 1.0)"),
      side: z.enum(["front", "back"]).optional()
        .describe("Board side (default 'front')"),
    },
    async (args) => {
      const result = await callKicadScript("add_test_points", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "audit_test_coverage",
    `Audit test point coverage across critical nets. Reports which
power, debug, and communication nets have test points and which
are missing. Returns coverage percentage.`,
    {},
    async () => {
      const result = await callKicadScript("audit_test_coverage", {});
      return { content: [{ type: "text", text: result }] };
    }
  );
}
