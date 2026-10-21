/**
 * Copper Analysis, Design Diff, and Interactive BOM Tools
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerCopperAnalysisTools(
  server: McpServer,
  callKicadScript: (cmd: string, args: Record<string, unknown>) => Promise<string>
) {
  server.tool(
    "analyze_copper_balance",
    `Analyze copper distribution across all layers for warpage prediction.
Reports fill percentage per layer, stackup imbalance, and risk level.
Recommends adding ground pours when imbalance exceeds thresholds.`,
    {},
    async () => {
      const result = await callKicadScript("analyze_copper_balance", {});
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "design_diff",
    `Compare two board revisions and report differences: added/removed
components, moved/rotated parts, value changes, footprint changes,
side swaps, and net changes. Useful for design review.`,
    {
      board_a: z.string().optional()
        .describe("Path to first board revision (uses current board if omitted)"),
      board_b: z.string()
        .describe("Path to second board revision to compare against"),
    },
    async (args) => {
      const result = await callKicadScript("design_diff", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "generate_interactive_bom",
    `Generate an Interactive HTML BOM with component highlighting.
Uses InteractiveHtmlBom if installed, includes tracks and nets overlay.
Output is a self-contained HTML file for design review.`,
    {
      board_path: z.string().optional()
        .describe("Path to .kicad_pcb (uses current board if omitted)"),
      output_dir: z.string().optional()
        .describe("Output directory (default: <board_dir>/bom/)"),
    },
    async (args) => {
      const result = await callKicadScript("generate_ibom", args);
      return { content: [{ type: "text", text: result }] };
    }
  );
}
