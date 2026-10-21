/**
 * Design Analysis Tools
 * Wraps kicad-happy analyzers for comprehensive PCB/schematic/EMC/thermal analysis
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerDesignAnalysisTools(
  server: McpServer,
  callKicadScript: (cmd: string, args: Record<string, unknown>) => Promise<string>
) {
  server.tool(
    "analyze_pcb_layout",
    `Comprehensive PCB layout analysis: trace widths, via counts, connectivity,
copper fill, DFM scoring, tombstoning risk, crosstalk, current capacity,
thermal vias, and return path continuity. Returns structured findings with
severity levels. Powered by kicad-happy (60+ checks).`,
    {
      board_path: z.string().optional()
        .describe("Path to .kicad_pcb (uses current board if omitted)"),
      full: z.boolean().optional()
        .describe("Include individual track/via coordinate data"),
      proximity: z.boolean().optional()
        .describe("Run trace proximity analysis for crosstalk assessment"),
      stage: z.enum(["schematic", "layout", "pre_fab", "bring_up"]).optional()
        .describe("Filter findings by review stage"),
      timeout: z.number().optional()
        .describe("Analysis timeout in seconds (default 120)"),
    },
    async (args) => {
      const result = await callKicadScript("analyze_pcb", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "analyze_schematic_design",
    `Comprehensive schematic analysis with 60+ circuit detectors:
power regulators (Vout from feedback dividers), voltage dividers, RC/LC filters,
opamp circuits, transistor circuits, crystal load caps, bus detection
(I2C/SPI/UART/CAN/USB/Ethernet), ESD coverage audit, PDN impedance,
power budget, sleep current audit, and domain-specific detectors
(RF, BMS, motor drivers, display, audio, LED).`,
    {
      schematic_path: z.string().optional()
        .describe("Path to .kicad_sch (auto-detects from board if omitted)"),
      board_path: z.string().optional()
        .describe("Board path to derive schematic from"),
      stage: z.enum(["schematic", "layout", "pre_fab", "bring_up"]).optional()
        .describe("Filter findings by review stage"),
      timeout: z.number().optional()
        .describe("Analysis timeout in seconds (default 180)"),
    },
    async (args) => {
      const result = await callKicadScript("analyze_schematic", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "analyze_emc_compliance",
    `EMC pre-compliance analysis with 44 rule checks across 18 categories:
ground plane voids (GP), decoupling (DC), I/O filtering (IO),
switching harmonics (SW), clock routing (CK), differential pair skew (DP),
PDN impedance (PD), return paths (RP), crosstalk (XT), ESD paths (ES),
board edge radiation (BE), shielding (SH). Supports FCC/CISPR/automotive/MIL-STD-461G.`,
    {
      board_path: z.string().optional()
        .describe("Path to .kicad_pcb"),
      standard: z.string().optional()
        .describe("EMC standard to check against (e.g. 'fcc', 'cispr', 'automotive', 'mil-std-461g')"),
      schematic_json: z.string().optional()
        .describe("Path to schematic analysis JSON for enrichment"),
      timeout: z.number().optional()
        .describe("Analysis timeout in seconds (default 120)"),
    },
    async (args) => {
      const result = await callKicadScript("analyze_emc", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "analyze_thermal",
    `Thermal analysis: junction temperature estimation, thermal via correction
factors, proximity warnings for capacitors near hotspots, power dissipation
mapping, and cooling recommendations.`,
    {
      board_path: z.string().optional()
        .describe("Path to .kicad_pcb"),
      ambient_temp: z.number().optional()
        .describe("Ambient temperature in Celsius (default 25)"),
      timeout: z.number().optional()
        .describe("Analysis timeout in seconds (default 120)"),
    },
    async (args) => {
      const result = await callKicadScript("analyze_thermal", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "analyze_cross_domain",
    `Cross-domain analysis: schematic-to-PCB consistency check.
Finds mismatches between schematic intent and PCB layout, including
ESD protection gaps, decoupling adequacy, and net assignment issues.`,
    {
      board_path: z.string().optional()
        .describe("Path to .kicad_pcb"),
      schematic_path: z.string().optional()
        .describe("Path to .kicad_sch (auto-detects if omitted)"),
      timeout: z.number().optional()
        .describe("Analysis timeout in seconds (default 180)"),
    },
    async (args) => {
      const result = await callKicadScript("analyze_cross_domain", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "check_design_analyzers",
    "Check which design analysis tools (kicad-happy) are installed and available",
    {},
    async () => {
      const result = await callKicadScript("check_analyzers", {});
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "install_design_analyzers",
    "Download and install kicad-happy design analyzers (zero pip dependencies, Python 3.10+ only)",
    {
      force: z.boolean().optional().describe("Force reinstall"),
    },
    async (args) => {
      const result = await callKicadScript("install_analyzers", args);
      return { content: [{ type: "text", text: result }] };
    }
  );
}
