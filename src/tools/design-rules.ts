/**
 * Design rules tools for KiCAD MCP server
 * 
 * These tools handle design rule checking and configuration
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import { logger } from '../logger.js';

// Command function type for KiCAD script calls
type CommandFunction = (command: string, params: Record<string, unknown>) => Promise<any>;

/**
 * Register design rule tools with the MCP server
 * 
 * @param server MCP server instance
 * @param callKicadScript Function to call KiCAD script commands
 */
export function registerDesignRuleTools(server: McpServer, callKicadScript: CommandFunction): void {
  logger.info('Registering design rule tools');
  
  // ------------------------------------------------------
  // Set Design Rules Tool
  // ------------------------------------------------------
  server.tool(
    "set_design_rules",
    "Set PCB design rules (clearances, trace widths, via sizes). For prototype boards, use apply_manufacturing_preset instead for safe defaults. Typical values: clearance 0.15-0.2mm, trackWidth 0.2-0.25mm for signals / 0.5-1.0mm for power, viaDiameter 0.6mm, viaDrill 0.3mm. Budget fabs (JLCPCB) minimum: 0.127mm trace/clearance, 0.3mm via drill.",
    {
      clearance: z.number().optional().describe("Minimum clearance between copper items (mm). JLCPCB min: 0.127, recommended: 0.15-0.2"),
      trackWidth: z.number().optional().describe("Default track width (mm). Signals: 0.2-0.25, Power: 0.5-1.0 (~1mm per 1A at 1oz copper)"),
      viaDiameter: z.number().optional().describe("Default via pad diameter (mm). Standard: 0.6-0.8, Power: 1.0"),
      viaDrill: z.number().optional().describe("Default via drill size (mm). Standard: 0.3-0.4, JLCPCB min: 0.3"),
      microViaDiameter: z.number().optional().describe("Default micro via diameter (mm). Advanced fab only."),
      microViaDrill: z.number().optional().describe("Default micro via drill size (mm). Advanced fab only."),
      minTrackWidth: z.number().optional().describe("Absolute minimum track width (mm). JLCPCB: 0.127, OSHPark: 0.152"),
      minViaDiameter: z.number().optional().describe("Minimum via pad diameter (mm). JLCPCB: 0.6"),
      minViaDrill: z.number().optional().describe("Minimum via drill size (mm). JLCPCB: 0.3, OSHPark: 0.254"),
      minMicroViaDiameter: z.number().optional().describe("Minimum micro via diameter (mm)"),
      minMicroViaDrill: z.number().optional().describe("Minimum micro via drill size (mm)"),
      minHoleDiameter: z.number().optional().describe("Minimum hole diameter (mm)"),
      requireCourtyard: z.boolean().optional().describe("Whether to require courtyards for all footprints (recommended: true)"),
      courtyardClearance: z.number().optional().describe("Minimum clearance between courtyards (mm). Recommended: 0.25")
    },
    async (params) => {
      logger.debug('Setting design rules');
      const result = await callKicadScript("set_design_rules", params);
      
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Get Design Rules Tool
  // ------------------------------------------------------
  server.tool(
    "get_design_rules",
    {},
    async () => {
      logger.debug('Getting design rules');
      const result = await callKicadScript("get_design_rules", {});
      
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Run DRC Tool
  // ------------------------------------------------------
  server.tool(
    "run_drc",
    {
      reportPath: z.string().optional().describe("Optional path to save the DRC report")
    },
    async ({ reportPath }) => {
      logger.debug('Running DRC check');
      const result = await callKicadScript("run_drc", { reportPath });
      
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Add Net Class Tool
  // ------------------------------------------------------
  server.tool(
    "add_net_class",
    {
      name: z.string().describe("Name of the net class"),
      description: z.string().optional().describe("Optional description of the net class"),
      clearance: z.number().describe("Clearance for this net class (mm)"),
      trackWidth: z.number().describe("Track width for this net class (mm)"),
      viaDiameter: z.number().describe("Via diameter for this net class (mm)"),
      viaDrill: z.number().describe("Via drill size for this net class (mm)"),
      uvia_diameter: z.number().optional().describe("Micro via diameter for this net class (mm)"),
      uvia_drill: z.number().optional().describe("Micro via drill size for this net class (mm)"),
      diff_pair_width: z.number().optional().describe("Differential pair width for this net class (mm)"),
      diff_pair_gap: z.number().optional().describe("Differential pair gap for this net class (mm)"),
      nets: z.array(z.string()).optional().describe("Array of net names to assign to this class")
    },
    async ({ name, description, clearance, trackWidth, viaDiameter, viaDrill, uvia_diameter, uvia_drill, diff_pair_width, diff_pair_gap, nets }) => {
      logger.debug(`Adding net class: ${name}`);
      const result = await callKicadScript("add_net_class", {
        name,
        description,
        clearance,
        trackWidth,
        viaDiameter,
        viaDrill,
        uvia_diameter,
        uvia_drill,
        diff_pair_width,
        diff_pair_gap,
        nets
      });
      
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Assign Net to Class Tool
  // ------------------------------------------------------
  server.tool(
    "assign_net_to_class",
    {
      net: z.string().describe("Name of the net"),
      netClass: z.string().describe("Name of the net class")
    },
    async ({ net, netClass }) => {
      logger.debug(`Assigning net ${net} to class ${netClass}`);
      const result = await callKicadScript("assign_net_to_class", {
        net,
        netClass
      });
      
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Set Layer Constraints Tool
  // ------------------------------------------------------
  server.tool(
    "set_layer_constraints",
    {
      layer: z.string().describe("Layer name (e.g., 'F.Cu')"),
      minTrackWidth: z.number().optional().describe("Minimum track width for this layer (mm)"),
      minClearance: z.number().optional().describe("Minimum clearance for this layer (mm)"),
      minViaDiameter: z.number().optional().describe("Minimum via diameter for this layer (mm)"),
      minViaDrill: z.number().optional().describe("Minimum via drill size for this layer (mm)")
    },
    async ({ layer, minTrackWidth, minClearance, minViaDiameter, minViaDrill }) => {
      logger.debug(`Setting constraints for layer: ${layer}`);
      const result = await callKicadScript("set_layer_constraints", {
        layer,
        minTrackWidth,
        minClearance,
        minViaDiameter,
        minViaDrill
      });
      
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Check Clearance Tool
  // ------------------------------------------------------
  server.tool(
    "check_clearance",
    {
      item1: z.object({
        type: z.enum(["track", "via", "pad", "zone", "component"]).describe("Type of the first item"),
        id: z.string().optional().describe("ID of the first item (if applicable)"),
        reference: z.string().optional().describe("Reference designator (for component)"),
        position: z.object({
          x: z.number().optional(),
          y: z.number().optional(),
          unit: z.enum(["mm", "inch"]).optional()
        }).optional().describe("Position to check (if ID not provided)")
      }).describe("First item to check"),
      item2: z.object({
        type: z.enum(["track", "via", "pad", "zone", "component"]).describe("Type of the second item"),
        id: z.string().optional().describe("ID of the second item (if applicable)"),
        reference: z.string().optional().describe("Reference designator (for component)"),
        position: z.object({
          x: z.number().optional(),
          y: z.number().optional(),
          unit: z.enum(["mm", "inch"]).optional()
        }).optional().describe("Position to check (if ID not provided)")
      }).describe("Second item to check")
    },
    async ({ item1, item2 }) => {
      logger.debug(`Checking clearance between ${item1.type} and ${item2.type}`);
      const result = await callKicadScript("check_clearance", {
        item1,
        item2
      });
      
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Get DRC Violations Tool
  // ------------------------------------------------------
  server.tool(
    "get_drc_violations",
    {
      severity: z.enum(["error", "warning", "all"]).optional().describe("Filter violations by severity")
    },
    async ({ severity }) => {
      logger.debug('Getting DRC violations');
      const result = await callKicadScript("get_drc_violations", { severity });
      
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Apply Manufacturing Preset Tool
  // ------------------------------------------------------
  server.tool(
    "apply_manufacturing_preset",
    "Apply a PCB manufacturer's recommended design rules to the board. Presets include clearances, trace widths, via sizes, and drill constraints that are guaranteed to be within the fab house's capabilities. Use 'list' to see all available presets. Always apply a preset before starting layout to avoid DFM issues.",
    {
      preset: z.enum(["jlcpcb_2layer", "jlcpcb_4layer", "oshpark_2layer", "pcbway_2layer", "list"]).describe(
        "Manufacturer preset to apply. 'jlcpcb_2layer' is the most common for cheap prototypes. Use 'list' to see all options with descriptions."
      )
    },
    async ({ preset }) => {
      logger.debug(`Applying manufacturing preset: ${preset}`);
      const result = await callKicadScript("apply_manufacturing_preset", { preset });

      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Validate for Manufacturing (DFM Check) Tool
  // ------------------------------------------------------
  server.tool(
    "validate_for_manufacturing",
    "Run a Design-for-Manufacturing (DFM) check against a specific fab house's capabilities. Checks all traces, vias, and design rules against the manufacturer's minimums. Reports errors (will be rejected by fab), warnings (may increase cost), and info (optimization suggestions). Run this before exporting Gerbers.",
    {
      preset: z.enum(["jlcpcb_2layer", "jlcpcb_4layer", "oshpark_2layer", "pcbway_2layer"]).optional().describe(
        "Manufacturer to validate against (default: jlcpcb_2layer)"
      )
    },
    async ({ preset }) => {
      logger.debug(`Validating for manufacturing: ${preset || 'jlcpcb_2layer'}`);
      const result = await callKicadScript("validate_for_manufacturing", { preset });

      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  logger.info('Design rule tools registered');
}
