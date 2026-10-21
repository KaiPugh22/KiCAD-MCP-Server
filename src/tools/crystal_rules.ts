/**
 * Crystal/Oscillator Layout Rule Enforcer Tools
 * Audit crystal placement, keep-out, load caps, guard ring
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerCrystalRulesTools(
  server: McpServer,
  callKicadScript: (cmd: string, args: Record<string, unknown>) => Promise<string>
) {
  server.tool(
    "audit_crystal_layout",
    `Comprehensive audit of crystal/oscillator layouts. Checks:
- Distance from MCU (should be < 15mm)
- Load capacitor placement (within max distance)
- Signal traces routing under crystal (keep-out violation)
- Nearby GND vias for return path
- Guard ring/pour presence
Reports per-crystal pass/fail with specific fix instructions.`,
    {
      max_cap_distance_mm: z.number().optional()
        .describe("Max allowed distance for load caps in mm (default 5.0)"),
      keepout_margin_mm: z.number().optional()
        .describe("Keep-out zone margin around crystal in mm (default 1.0)"),
    },
    async (args) => {
      const result = await callKicadScript("audit_crystal_layout", args);
      return { content: [{ type: "text", text: result }] };
    }
  );
}
