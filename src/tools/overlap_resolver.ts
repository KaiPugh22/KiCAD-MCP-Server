/**
 * Overlap Resolver Tools
 * Detect and auto-fix component courtyard/placement overlaps
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerOverlapResolverTools(
  server: McpServer,
  callKicadScript: (cmd: string, args: Record<string, unknown>) => Promise<string>
) {
  server.tool(
    "detect_overlaps",
    `Detect all component courtyard and placement overlaps on the board.
Reports overlap dimensions and area for each pair.`,
    {
      margin_mm: z.number().optional()
        .describe("Extra clearance margin in mm (default 0)"),
    },
    async (args) => {
      const result = await callKicadScript("detect_overlaps", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "resolve_overlaps",
    `Compute and apply minimum moves to resolve all overlaps using
force-directed repulsion. Respects locked components.`,
    {
      margin_mm: z.number().optional()
        .describe("Required clearance between components in mm (default 0.25)"),
      max_iterations: z.number().optional()
        .describe("Max solver iterations (default 50)"),
      locked: z.array(z.string()).optional()
        .describe("Component refs that must not move"),
      dry_run: z.boolean().optional()
        .describe("If true, compute moves but don't apply them (default false)"),
    },
    async (args) => {
      const result = await callKicadScript("resolve_overlaps", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "suggest_overlap_fixes",
    "Dry-run overlap resolution — shows what moves would be needed without applying them",
    {
      margin_mm: z.number().optional()
        .describe("Required clearance in mm (default 0.25)"),
      locked: z.array(z.string()).optional()
        .describe("Component refs that must not move"),
    },
    async (args) => {
      const result = await callKicadScript("suggest_overlap_fixes", args);
      return { content: [{ type: "text", text: result }] };
    }
  );
}
