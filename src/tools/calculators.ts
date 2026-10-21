/**
 * PCB Design Calculator tools for KiCAD MCP server
 *
 * IPC-2221 trace width, via current, impedance, voltage drop,
 * and automated netclass parameter suggestion.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

type CommandFunction = (
  command: string,
  params: Record<string, unknown>,
) => Promise<any>;

export function registerCalculatorTools(
  server: McpServer,
  callKicadScript: CommandFunction,
): void {
  // ------------------------------------------------------------------
  // Trace Width Calculator (IPC-2221)
  // ------------------------------------------------------------------
  server.tool(
    "calculate_trace_width",
    "Calculate required PCB trace width for a given current using IPC-2221. Returns width in mm and mils, plus resistance and voltage drop per cm. Essential for power traces and netclass setup.",
    {
      current: z
        .number()
        .describe("Current in Amps that the trace must carry"),
      tempRise: z
        .number()
        .optional()
        .describe(
          "Acceptable temperature rise above ambient in °C (default: 10)",
        ),
      copperWeight: z
        .number()
        .optional()
        .describe("Copper weight in oz/ft² (default: 1.0, typical: 1 or 2)"),
      layerType: z
        .enum(["external", "internal"])
        .optional()
        .describe(
          "Layer type affects heat dissipation (default: external). Internal layers need wider traces.",
        ),
      ambientTemp: z
        .number()
        .optional()
        .describe("Ambient temperature in °C (default: 25)"),
    },
    async (args) => {
      const result = await callKicadScript("calculate_trace_width", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  // ------------------------------------------------------------------
  // Via Current Capacity Calculator
  // ------------------------------------------------------------------
  server.tool(
    "calculate_via_current",
    "Calculate current-carrying capacity of a PCB via based on drill size and plating thickness. Useful for determining how many vias are needed for power connections.",
    {
      drillDiameter: z
        .number()
        .describe("Via drill diameter in mm (JLCPCB min: 0.3)"),
      platingThickness: z
        .number()
        .optional()
        .describe(
          "Barrel plating thickness in micrometers (default: 25, typical: 18-25)",
        ),
      tempRise: z
        .number()
        .optional()
        .describe("Acceptable temperature rise in °C (default: 10)"),
      numVias: z
        .number()
        .optional()
        .describe(
          "Number of parallel vias (default: 1). Total current = per-via × count.",
        ),
    },
    async (args) => {
      const result = await callKicadScript("calculate_via_current", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  // ------------------------------------------------------------------
  // Impedance Calculator
  // ------------------------------------------------------------------
  server.tool(
    "calculate_impedance",
    "Calculate trace impedance for microstrip or stripline geometry. Supports single-ended and differential impedance. Use for controlled-impedance designs (USB, HDMI, PCIe, DDR, Ethernet).",
    {
      geometry: z
        .enum(["microstrip", "stripline"])
        .optional()
        .describe(
          "Trace geometry (default: microstrip). Microstrip = outer layer, stripline = inner between planes.",
        ),
      traceWidth: z
        .number()
        .describe("Trace width in mm"),
      dielectricHeight: z
        .number()
        .describe(
          "Height of dielectric in mm. For microstrip: distance from trace to ground plane. For stripline: distance between ground planes.",
        ),
      dielectricConstant: z
        .number()
        .optional()
        .describe(
          "Relative permittivity Er (default: 4.5 for FR4). Typical FR4: 4.2-4.8.",
        ),
      copperThickness: z
        .number()
        .optional()
        .describe("Copper thickness in mm (default: 0.035 = 1oz)"),
      spacing: z
        .number()
        .optional()
        .describe(
          "Edge-to-edge spacing in mm for differential impedance calculation. Omit for single-ended only.",
        ),
    },
    async (args) => {
      const result = await callKicadScript("calculate_impedance", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  // ------------------------------------------------------------------
  // Solve Trace Width for Target Impedance
  // ------------------------------------------------------------------
  server.tool(
    "solve_trace_width_for_impedance",
    "Find the trace width needed to achieve a target impedance. Iteratively solves the impedance equation. Specify your stackup parameters and desired impedance (e.g., 50Ω single-ended, 90Ω differential for USB).",
    {
      targetImpedance: z
        .number()
        .describe("Target impedance in ohms (e.g., 50 for RF, 90 for USB)"),
      geometry: z
        .enum(["microstrip", "stripline"])
        .optional()
        .describe("Trace geometry (default: microstrip)"),
      dielectricHeight: z
        .number()
        .describe("Dielectric height in mm"),
      dielectricConstant: z
        .number()
        .optional()
        .describe("Dielectric constant Er (default: 4.5)"),
      copperThickness: z
        .number()
        .optional()
        .describe("Copper thickness in mm (default: 0.035)"),
      targetDifferentialImpedance: z
        .number()
        .optional()
        .describe(
          "Target differential impedance in ohms (requires spacing parameter)",
        ),
      spacing: z
        .number()
        .optional()
        .describe("Trace spacing in mm (required for differential solve)"),
    },
    async (args) => {
      const result = await callKicadScript(
        "solve_trace_width_for_impedance",
        args,
      );
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  // ------------------------------------------------------------------
  // Voltage Drop Calculator
  // ------------------------------------------------------------------
  server.tool(
    "calculate_voltage_drop",
    "Calculate voltage drop and power loss across a PCB trace. Critical for power delivery analysis — ensures supply voltages remain within tolerance at the load.",
    {
      current: z.number().describe("Current in Amps"),
      traceLength: z.number().describe("Trace length in mm"),
      traceWidth: z.number().describe("Trace width in mm"),
      copperWeight: z
        .number()
        .optional()
        .describe("Copper weight in oz/ft² (default: 1.0)"),
      temperature: z
        .number()
        .optional()
        .describe("Operating temperature in °C (default: 25)"),
    },
    async (args) => {
      const result = await callKicadScript("calculate_voltage_drop", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  // ------------------------------------------------------------------
  // Suggest Netclass Parameters
  // ------------------------------------------------------------------
  server.tool(
    "suggest_netclass_params",
    "Suggest netclass parameters (trace width, via size, clearance) based on current requirements, signal type, and manufacturer capabilities. Use this BEFORE creating a netclass to get the right values automatically.",
    {
      current: z
        .number()
        .optional()
        .describe("Expected current in Amps (default: 0.1)"),
      signalType: z
        .enum(["signal", "power", "highspeed", "differential"])
        .optional()
        .describe("Signal type (default: signal)"),
      manufacturer: z
        .enum(["jlcpcb", "jlcpcb_4layer", "oshpark", "pcbway"])
        .optional()
        .describe(
          "Target manufacturer for minimum constraints (default: jlcpcb)",
        ),
      copperWeight: z
        .number()
        .optional()
        .describe("Copper weight in oz/ft² (default: 1.0)"),
      impedanceTarget: z
        .number()
        .optional()
        .describe(
          "Target impedance in ohms — adjusts trace width for controlled impedance",
        ),
    },
    async (args) => {
      const result = await callKicadScript("suggest_netclass_params", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  // ------------------------------------------------------------------
  // Auto-Create Power Netclasses
  // ------------------------------------------------------------------
  server.tool(
    "auto_create_power_netclasses",
    "Automatically detect power nets (VCC, VDD, 3V3, 5V, GND, etc.) and create appropriately-sized netclasses with correct trace widths, via sizes, and clearances. Runs in dry-run mode by default — set dryRun=false to apply.",
    {
      manufacturer: z
        .enum(["jlcpcb", "jlcpcb_4layer", "oshpark", "pcbway"])
        .optional()
        .describe("Target manufacturer (default: jlcpcb)"),
      copperWeight: z
        .number()
        .optional()
        .describe("Copper weight in oz/ft² (default: 1.0)"),
      dryRun: z
        .boolean()
        .optional()
        .describe(
          "If true (default), shows what would be created without applying. Set false to create.",
        ),
      currentOverrides: z
        .record(z.number())
        .optional()
        .describe(
          'Override current estimates for specific nets, e.g. {"VCC": 2.0, "3V3": 1.5}',
        ),
    },
    async (args) => {
      const result = await callKicadScript(
        "auto_create_power_netclasses",
        args,
      );
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );
}
