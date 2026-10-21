/**
 * Board Setup Automation Tools
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerBoardSetupTools(
  server: McpServer,
  callKicadScript: (cmd: string, args: Record<string, unknown>) => Promise<string>
) {
  server.tool(
    "auto_setup_board",
    "One-command board setup: configure design rules, net classes, and impedance targets from fab house and stackup specs",
    {
      fab_house: z
        .enum(["jlcpcb_standard", "jlcpcb_advanced", "oshpark", "pcbway_standard"])
        .optional()
        .describe("Fabrication house preset (default jlcpcb_standard)"),
      stackup: z
        .enum([
          "2layer_1.6mm",
          "4layer_1.6mm",
          "4layer_jlcpcb_jlc04161h",
          "6layer_1.6mm",
        ])
        .optional()
        .describe("PCB stackup (default 2layer_1.6mm)"),
      signal_types: z
        .array(
          z.enum([
            "single_ended_50",
            "single_ended_75",
            "differential_90",
            "differential_100",
            "usb2",
            "usb3",
            "hdmi",
            "ethernet",
            "pcie",
            "ddr4",
          ])
        )
        .optional()
        .describe("Signal types needing impedance control"),
      max_power_current: z
        .number()
        .optional()
        .describe("Max current on power nets in amps (default 1.0)"),
      dry_run: z
        .boolean()
        .optional()
        .describe("If true (default), only report config without applying"),
    },
    async (args) => {
      const result = await callKicadScript("auto_setup_board", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "list_stackups",
    "List available PCB stackup configurations (layer counts, dielectrics, thicknesses)",
    {},
    async () => {
      const result = await callKicadScript("list_stackups", {});
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "list_signal_types",
    "List available impedance-controlled signal types (USB, HDMI, Ethernet, PCIe, DDR, etc.)",
    {},
    async () => {
      const result = await callKicadScript("list_signal_types", {});
      return { content: [{ type: "text", text: result }] };
    }
  );
}
