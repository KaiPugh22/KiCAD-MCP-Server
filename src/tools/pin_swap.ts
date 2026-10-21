/**
 * Pin Swap Optimization Tools
 * Find and execute pin swaps to simplify routing
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerPinSwapTools(
  server: McpServer,
  callKicadScript: (cmd: string, args: Record<string, unknown>) => Promise<string>
) {
  server.tool(
    "find_swappable_pins",
    `Identify GPIO pins on a component that could be swapped to reduce
routing distance. Compares Manhattan distance for current vs swapped
net assignments, reporting improvement percentage (threshold: 15%).`,
    {
      reference: z.string()
        .describe("Component reference to analyze (e.g. 'U1')"),
    },
    async (args) => {
      const result = await callKicadScript("find_swappable_pins", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "execute_pin_swap",
    `Execute a pin swap on the PCB — swaps net assignments between two
pads. WARNING: This is a PCB-only change; update the schematic to match.`,
    {
      reference: z.string()
        .describe("Component reference (e.g. 'U1')"),
      pin1: z.string()
        .describe("First pin name/number"),
      pin2: z.string()
        .describe("Second pin name/number"),
    },
    async (args) => {
      const result = await callKicadScript("execute_pin_swap", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "suggest_all_swaps",
    `Scan all ICs on the board and rank beneficial pin swaps.
Only analyzes components with at least min_pins pads (default 8).
Returns top improvements sorted by total routing distance saved.`,
    {
      min_pins: z.number().optional()
        .describe("Minimum pin count to consider (default 8)"),
    },
    async (args) => {
      const result = await callKicadScript("suggest_all_swaps", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "define_swap_group",
    `Define a group of pins that are functionally interchangeable.
Validates that all pins exist on the component and returns their
current net assignments. Use before optimize_pin_assignment.`,
    {
      reference: z.string().describe("Component reference (e.g. 'U1')"),
      group_name: z.string().optional().describe("Name for this swap group"),
      pin_names: z.array(z.string())
        .describe("Pin names/numbers that can be swapped with each other"),
    },
    async (args) => {
      const result = await callKicadScript("define_swap_group", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "optimize_pin_assignment",
    `Find the optimal pin-to-net assignment for a swap group to minimize
total routing distance. Uses exhaustive search for ≤8 pins (guaranteed
optimal), greedy pairwise for larger groups. Auto-detects GPIO pins
if pin_names omitted.`,
    {
      reference: z.string().describe("Component reference (e.g. 'U1')"),
      pin_names: z.array(z.string()).optional()
        .describe("Swappable pin names (auto-detects GPIOs if omitted)"),
    },
    async (args) => {
      const result = await callKicadScript("optimize_pin_assignment", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "bulk_pin_swap",
    `Apply multiple pin swaps at once from an optimization result.
Takes the swaps array from optimize_pin_assignment output.
WARNING: PCB-only changes; update schematic to match.`,
    {
      reference: z.string().describe("Component reference (e.g. 'U1')"),
      swaps: z.array(z.object({
        pin: z.string().describe("Pin name"),
        optimal_net: z.string().optional().describe("Target net (from optimize output)"),
        new_net: z.string().optional().describe("Target net (alternative field name)"),
      })).describe("Swaps to apply"),
    },
    async (args) => {
      const result = await callKicadScript("bulk_pin_swap", args);
      return { content: [{ type: "text", text: result }] };
    }
  );
}
