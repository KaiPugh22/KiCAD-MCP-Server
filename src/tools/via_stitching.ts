/**
 * Via Stitching Tools
 * Ground stitching, via fences, and thermal via arrays
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerViaStitchingTools(
  server: McpServer,
  callKicadScript: (cmd: string, args: Record<string, unknown>) => Promise<string>
) {
  server.tool(
    "add_via_stitching",
    `Add ground via stitching across the board or within a region.
Places vias in a grid pattern with collision avoidance (skips footprints
and existing tracks). Essential for EMC compliance and return current paths.`,
    {
      net_name: z.string().optional()
        .describe("Net for stitching vias (default 'GND')"),
      pitch_mm: z.number().optional()
        .describe("Grid pitch in mm (default 3.0)"),
      via_size_mm: z.number().optional()
        .describe("Via pad diameter in mm (default 0.6)"),
      via_drill_mm: z.number().optional()
        .describe("Via drill diameter in mm (default 0.3)"),
      clearance_mm: z.number().optional()
        .describe("Clearance from existing items in mm (default 0.5)"),
      region: z.object({
        x1: z.number(), y1: z.number(),
        x2: z.number(), y2: z.number(),
      }).optional().describe("Region to stitch {x1,y1,x2,y2} in mm, or whole board if omitted"),
    },
    async (args) => {
      const result = await callKicadScript("add_via_stitching", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "add_via_fence",
    `Add a via fence (shielding wall) along a path. Used for signal
isolation between sensitive RF/analog traces and noisy digital sections.`,
    {
      net_name: z.string().optional()
        .describe("Net for fence vias (default 'GND')"),
      points: z.array(z.object({ x: z.number(), y: z.number() }))
        .describe("Path waypoints [{x,y},...] in mm"),
      pitch_mm: z.number().optional()
        .describe("Via spacing along path in mm (default 1.0)"),
      via_size_mm: z.number().optional()
        .describe("Via pad diameter in mm (default 0.6)"),
      via_drill_mm: z.number().optional()
        .describe("Via drill diameter in mm (default 0.3)"),
      offset_mm: z.number().optional()
        .describe("Offset from path centerline in mm (default 0)"),
    },
    async (args) => {
      const result = await callKicadScript("add_via_fence", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "add_thermal_vias",
    `Add thermal via array under a component's exposed/thermal pad.
Auto-detects the thermal pad (EP, GND, Slug, or largest pad > 2mm).
Critical for QFN, DFN, and power component heat dissipation.`,
    {
      reference: z.string().describe("Component reference (e.g. 'U1')"),
      pitch_mm: z.number().optional()
        .describe("Via grid pitch in mm (default 1.2)"),
      via_size_mm: z.number().optional()
        .describe("Via pad diameter in mm (default 0.6)"),
      via_drill_mm: z.number().optional()
        .describe("Via drill diameter in mm (default 0.3)"),
      margin_mm: z.number().optional()
        .describe("Inset from pad edge in mm (default 0.3)"),
    },
    async (args) => {
      const result = await callKicadScript("add_thermal_vias", args);
      return { content: [{ type: "text", text: result }] };
    }
  );
}
