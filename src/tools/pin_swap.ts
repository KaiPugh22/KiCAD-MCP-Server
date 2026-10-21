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
}
