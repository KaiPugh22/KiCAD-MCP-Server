/**
 * Decoupling capacitor intelligence tools for KiCAD MCP server
 *
 * Analyze, map, and validate decoupling capacitor placement.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

type CommandFunction = (
  command: string,
  params: Record<string, unknown>,
) => Promise<any>;

export function registerDecouplingTools(
  server: McpServer,
  callKicadScript: CommandFunction,
): void {
  // ------------------------------------------------------------------
  // Analyze Decoupling Map (Schematic)
  // ------------------------------------------------------------------
  server.tool(
    "analyze_decoupling",
    "Analyze a schematic to map which decoupling capacitors serve which ICs. Traces power net connectivity to build cap-to-IC associations. Also identifies ICs that lack decoupling caps.",
    {
      schematicPath: z
        .string()
        .describe("Path to the .kicad_sch schematic file to analyze"),
    },
    async (args) => {
      const result = await callKicadScript("analyze_decoupling", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  // ------------------------------------------------------------------
  // Analyze Decoupling Placement (Board)
  // ------------------------------------------------------------------
  server.tool(
    "analyze_decoupling_placement",
    "Analyze PCB placement quality of decoupling capacitors. Checks physical distance from each bypass cap to its associated IC and rates placement as good (<5mm), acceptable (<10mm), or too far. Requires a loaded board.",
    {
      maxGoodDistance: z
        .number()
        .optional()
        .describe(
          "Maximum distance in mm for 'good' rating (default: 5.0)",
        ),
      maxOkDistance: z
        .number()
        .optional()
        .describe(
          "Maximum distance in mm for 'acceptable' rating (default: 10.0)",
        ),
    },
    async (args) => {
      const result = await callKicadScript(
        "analyze_decoupling_placement",
        args,
      );
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  // ------------------------------------------------------------------
  // Suggest Decoupling Strategy
  // ------------------------------------------------------------------
  server.tool(
    "suggest_decoupling",
    "Get decoupling capacitor recommendations for an IC. Returns suggested cap values, quantities, packages, and placement rules based on IC type, frequency, and number of power pins. Covers STM32, ESP32, FPGA, ADC/DAC, regulators, and generic ICs.",
    {
      icType: z
        .string()
        .optional()
        .describe(
          "IC type or family (e.g., 'STM32F4', 'ESP32', 'FPGA', 'ADC', 'LDO'). Leave empty for generic.",
        ),
      numPowerPins: z
        .number()
        .optional()
        .describe("Number of VCC/VDD power pins (default: 1)"),
      maxFrequency: z
        .number()
        .optional()
        .describe(
          "Maximum operating frequency in MHz (default: 100). Higher frequencies need smaller caps closer to the IC.",
        ),
      supplyVoltage: z
        .number()
        .optional()
        .describe("Supply voltage in volts (default: 3.3)"),
    },
    async (args) => {
      const result = await callKicadScript("suggest_decoupling", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );
}
