/**
 * Auto-Placement Tools
 * Connectivity-aware component placement via KiCad-Autoplace
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerAutoPlaceTools(
  server: McpServer,
  callKicadScript: (cmd: string, args: Record<string, unknown>) => Promise<string>
) {
  server.tool(
    "auto_place_components",
    `Connectivity-aware auto-placement using simulated annealing.
Multi-strategy seeding (force-directed, topological, floorplan), block
detection from hierarchical sheets, connector edge affinity, decoupling
cap proximity optimization. Writes result to a new .kicad_pcb file.`,
    {
      board_path: z.string().optional()
        .describe("Path to .kicad_pcb (uses current board if omitted)"),
      output_path: z.string().optional()
        .describe("Output path (default: <stem>.autoplaced.kicad_pcb)"),
      strategy: z.enum(["auto", "topo", "floorplan", "compact", "mixed", "keep"]).optional()
        .describe("Placement strategy (default 'auto')"),
      seed: z.number().optional()
        .describe("Random seed for reproducibility (default 0)"),
      orient_pass: z.boolean().optional()
        .describe("Final pass to rotate parts reducing net crossings"),
      cross_weight: z.number().optional()
        .describe("Penalty per net crossing (default 0, try 1.0 for crossing reduction)"),
      connectors: z.array(z.string()).optional()
        .describe("Component refs to pin to board edges (e.g. ['J1', 'J2'])"),
      locked: z.array(z.string()).optional()
        .describe("Component refs that must not be moved (e.g. ['U1', 'Y1'])"),
      timeout: z.number().optional()
        .describe("Placement timeout in seconds (default 300)"),
    },
    async (args) => {
      const result = await callKicadScript("auto_place", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "auto_place_multi_seed",
    `Run multi-seed auto-placement: generates N candidate layouts with different
strategies, evaluates each by HPWL and net crossings, and keeps the best.
Best for complex boards where a single seed may not find the optimal layout.`,
    {
      board_path: z.string().optional()
        .describe("Path to .kicad_pcb"),
      output_path: z.string().optional()
        .describe("Output path"),
      num_seeds: z.number().optional()
        .describe("Number of seed candidates to evaluate (default 6)"),
      strategy: z.enum(["auto", "topo", "floorplan", "compact", "mixed"]).optional()
        .describe("Strategy (default 'mixed' - alternates strategies per seed)"),
      orient_pass: z.boolean().optional()
        .describe("Orientation optimization pass"),
      timeout: z.number().optional()
        .describe("Total timeout in seconds (default 900)"),
    },
    async (args) => {
      const result = await callKicadScript("auto_place_multi_seed", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "placement_metrics",
    "Evaluate current placement quality: HPWL (half-perimeter wirelength), net crossings, overlaps",
    {
      board_path: z.string().optional()
        .describe("Path to .kicad_pcb"),
    },
    async (args) => {
      const result = await callKicadScript("placement_metrics", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "check_autoplace",
    "Check if KiCad-Autoplace is installed and KiCad Python is available",
    {},
    async () => {
      const result = await callKicadScript("check_autoplace", {});
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "install_autoplace",
    "Download and install KiCad-Autoplace (requires KiCad's Python with pcbnew)",
    {
      force: z.boolean().optional().describe("Force reinstall"),
    },
    async (args) => {
      const result = await callKicadScript("install_autoplace", args);
      return { content: [{ type: "text", text: result }] };
    }
  );
}
