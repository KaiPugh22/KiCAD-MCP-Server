/**
 * Power Integrity / PDN Analysis Tools
 *
 * MCP tool registrations for PDN analysis, cap staging, and voltage drop.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerPowerIntegrityTools(
  server: McpServer,
  callKicadScript: (cmd: string, args: Record<string, unknown>) => Promise<string>
) {
  server.tool(
    "analyze_pdn",
    "Analyze power distribution network: target impedance, capacitor staging, and adequacy grading",
    {
      voltage: z.number().describe("Rail voltage (e.g. 3.3, 1.8, 5.0)"),
      max_current: z.number().describe("Maximum transient current in amps"),
      max_ripple_pct: z
        .number()
        .optional()
        .describe("Max voltage ripple percentage (default 3%)"),
      frequency_range: z
        .array(z.number())
        .length(2)
        .optional()
        .describe("[min_Hz, max_Hz] frequency range of interest"),
      copper_weight: z
        .enum(["0.5oz", "1oz", "2oz", "3oz"])
        .optional()
        .describe("Copper weight for plane impedance estimate"),
      num_caps_installed: z
        .record(z.number())
        .optional()
        .describe('Existing cap inventory, e.g. {"100nF": 10, "10uF": 4}'),
    },
    async (args) => {
      const result = await callKicadScript("analyze_pdn", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "calculate_voltage_drop_plane",
    "Calculate DC voltage drop across a copper plane or wide trace segment",
    {
      current: z.number().describe("Current in amps"),
      length_mm: z.number().describe("Current path length in mm"),
      width_mm: z.number().describe("Effective current path width in mm"),
      copper_weight: z
        .enum(["0.5oz", "1oz", "2oz", "3oz"])
        .optional()
        .describe("Copper weight (default 1oz)"),
      temperature: z
        .number()
        .optional()
        .describe("Operating temperature in °C (default 25)"),
    },
    async (args) => {
      const result = await callKicadScript("calculate_voltage_drop_plane", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "suggest_bypass_strategy",
    "Get IC-specific bypass/decoupling capacitor strategy with placement guidance",
    {
      ic_type: z
        .enum(["mcu", "fpga", "adc", "dac", "rf", "ldo", "ddr", "pll"])
        .describe("IC category"),
      power_pins: z
        .number()
        .optional()
        .describe("Number of VCC pins on the IC (default 1)"),
      max_current: z
        .number()
        .optional()
        .describe("Maximum current draw in amps (default 0.5)"),
      voltage: z
        .number()
        .optional()
        .describe("Supply voltage (default 3.3)"),
    },
    async (args) => {
      const result = await callKicadScript("suggest_bypass_strategy", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "analyze_power_tree",
    "Analyze the power distribution tree from the board: identify rails, regulators, and loads",
    {},
    async () => {
      const result = await callKicadScript("analyze_power_tree", {});
      return { content: [{ type: "text", text: result }] };
    }
  );
}
