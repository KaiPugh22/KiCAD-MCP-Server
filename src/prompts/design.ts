/**
 * Design prompts for KiCAD MCP server
 * 
 * These prompts guide the LLM in providing assistance with general PCB design tasks
 * in KiCAD.
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import { logger } from '../logger.js';

/**
 * Register design prompts with the MCP server
 * 
 * @param server MCP server instance
 */
export function registerDesignPrompts(server: McpServer): void {
  logger.info('Registering design prompts');

  // ------------------------------------------------------
  // PCB Layout Review Prompt
  // ------------------------------------------------------
  server.prompt(
    "pcb_layout_review",
    {
      pcb_design_info: z.string().describe("Information about the current PCB design, including board dimensions, layer stack-up, component placement, and routing details")
    },
    () => ({
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text: `You're helping to review a PCB layout for potential issues and improvements. Here's information about the current PCB design:

{{pcb_design_info}}

When reviewing the PCB layout, consider these key areas:

1. Component Placement:
   - Logical grouping of related components
   - Orientation for efficient routing
   - Thermal considerations for heat-generating components
   - Mechanical constraints (mounting holes, connectors at edges)
   - Accessibility for testing and rework

2. Signal Integrity:
   - Trace lengths for critical signals
   - Differential pair routing quality
   - Potential crosstalk issues
   - Return path continuity
   - Decoupling capacitor placement

3. Power Distribution:
   - Adequate copper for power rails
   - Power plane design and continuity
   - Decoupling strategy effectiveness
   - Voltage regulator thermal management

4. EMI/EMC Considerations:
   - Ground plane integrity
   - Potential antenna effects
   - Shielding requirements
   - Loop area minimization
   - Edge radiation control

5. Manufacturing and Assembly:
   - DFM (Design for Manufacturing) issues
   - DFA (Design for Assembly) considerations
   - Testability features
   - Silkscreen clarity and usefulness
   - Solder mask considerations

Based on the provided information, identify potential issues and suggest specific improvements to enhance the PCB design.`
          }
        }
      ]
    })
  );

  // ------------------------------------------------------
  // Layer Stack-up Planning Prompt
  // ------------------------------------------------------
  server.prompt(
    "layer_stackup_planning",
    {
      design_requirements: z.string().describe("Information about the PCB design requirements, including signal types, speed/frequency, power requirements, and any special considerations")
    },
    () => ({
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text: `You're helping to plan an appropriate layer stack-up for a PCB design. Here's information about the design requirements:

{{design_requirements}}

When planning a PCB layer stack-up, consider these important factors:

1. Signal Integrity Requirements:
   - Controlled impedance needs
   - High-speed signal routing
   - EMI/EMC considerations
   - Crosstalk mitigation

2. Power Distribution Needs:
   - Current requirements for power rails
   - Power integrity considerations
   - Decoupling effectiveness
   - Thermal management

3. Manufacturing Constraints:
   - Fabrication capabilities and limitations
   - Cost considerations
   - Available materials and their properties
   - Standard vs. specialized processes

4. Layer Types and Arrangement:
   - Signal layers
   - Power and ground planes
   - Mixed signal/plane layers
   - Microstrip vs. stripline configurations

5. Material Selection:
   - Dielectric constant (Er) requirements
   - Loss tangent considerations for high-speed
   - Thermal properties
   - Mechanical stability

Based on the provided requirements, recommend an appropriate layer stack-up, including the number of layers, their arrangement, material specifications, and thickness parameters. Explain the rationale behind your recommendations.`
          }
        }
      ]
    })
  );

  // ------------------------------------------------------
  // Design Rule Development Prompt
  // ------------------------------------------------------
  server.prompt(
    "design_rule_development",
    {
      project_requirements: z.string().describe("Information about the PCB project requirements, including technology, speed/frequency, manufacturing capabilities, and any special considerations")
    },
    () => ({
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text: `You're helping to develop appropriate design rules for a PCB project. Here's information about the project requirements:

{{project_requirements}}

When developing PCB design rules, consider these key areas:

1. Clearance Rules:
   - Minimum spacing between copper features
   - Different clearance requirements for different net classes
   - High-voltage clearance requirements
   - Polygon pour clearances

2. Width Rules:
   - Minimum trace widths for signal nets
   - Power trace width requirements based on current
   - Differential pair width and spacing
   - Net class-specific width rules

3. Via Rules:
   - Minimum via size and drill diameter
   - Via annular ring requirements
   - Microvias and buried/blind via specifications
   - Via-in-pad rules

4. Manufacturing Constraints:
   - Minimum hole size
   - Aspect ratio limitations
   - Soldermask and silkscreen constraints
   - Edge clearances

5. Special Requirements:
   - Impedance control specifications
   - High-speed routing constraints
   - Thermal relief parameters
   - Teardrop specifications

Based on the provided project requirements, recommend a comprehensive set of design rules that will ensure signal integrity, manufacturability, and reliability of the PCB. Provide specific values where appropriate and explain the rationale behind critical rules.`
          }
        }
      ]
    })
  );

  // ------------------------------------------------------
  // Component Selection Guidance Prompt
  // ------------------------------------------------------
  server.prompt(
    "component_selection_guidance",
    {
      circuit_requirements: z.string().describe("Information about the circuit requirements, including functionality, performance needs, operating environment, and any special considerations")
    },
    () => ({
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text: `You're helping with component selection for a PCB design. Here's information about the circuit requirements:

{{circuit_requirements}}

When selecting components for a PCB design, consider these important factors:

1. Electrical Specifications:
   - Voltage and current ratings
   - Power handling capabilities
   - Speed/frequency requirements
   - Noise and precision considerations
   - Operating temperature range

2. Package and Footprint:
   - Space constraints on the PCB
   - Thermal dissipation requirements
   - Manual vs. automated assembly
   - Inspection and rework considerations
   - Available footprint libraries

3. Availability and Sourcing:
   - Multiple source options
   - Lead time considerations
   - Lifecycle status (new, mature, end-of-life)
   - Cost considerations
   - Minimum order quantities

4. Reliability and Quality:
   - Industrial vs. commercial vs. automotive grade
   - Expected lifetime of the product
   - Environmental conditions
   - Compliance with relevant standards

5. Special Considerations:
   - EMI/EMC performance
   - Thermal characteristics
   - Moisture sensitivity
   - RoHS/REACH compliance
   - Special handling requirements

Based on the provided circuit requirements, recommend appropriate component types, packages, and specific considerations for this design. Provide guidance on critical component selections and explain the rationale behind your recommendations.`
          }
        }
      ]
    })
  );

  // ------------------------------------------------------
  // PCB Design Optimization Prompt
  // ------------------------------------------------------
  server.prompt(
    "pcb_design_optimization",
    {
      design_info: z.string().describe("Information about the current PCB design, including board dimensions, layer stack-up, component placement, and routing details"),
      optimization_goals: z.string().describe("Specific goals for optimization, such as performance improvement, cost reduction, size reduction, or manufacturability enhancement")
    },
    () => ({
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text: `You're helping to optimize a PCB design. Here's information about the current design and optimization goals:

{{design_info}}
{{optimization_goals}}

When optimizing a PCB design, consider these key areas based on the stated goals:

1. Performance Optimization:
   - Critical signal path length reduction
   - Impedance control improvement
   - Decoupling strategy enhancement
   - Thermal management improvement
   - EMI/EMC reduction techniques

2. Manufacturability Optimization:
   - DFM rule compliance
   - Testability improvements
   - Assembly process simplification
   - Yield improvement opportunities
   - Tolerance and variation management

3. Cost Optimization:
   - Board size reduction opportunities
   - Layer count optimization
   - Component consolidation
   - Alternative component options
   - Panelization efficiency

4. Reliability Optimization:
   - Stress point identification and mitigation
   - Environmental robustness improvements
   - Failure mode mitigation
   - Margin analysis and improvement
   - Redundancy considerations

5. Space/Size Optimization:
   - Component placement density
   - 3D space utilization
   - Flex and rigid-flex opportunities
   - Alternative packaging approaches
   - Connector and interface optimization

Based on the provided information and optimization goals, suggest specific, actionable improvements to the PCB design. Prioritize your recommendations based on their potential impact and implementation feasibility.`
          }
        }
      ]
    })
  );

  // ------------------------------------------------------
  // PCB Manufacturing Readiness Guide
  // ------------------------------------------------------
  server.prompt(
    "manufacturing_readiness_guide",
    {
      manufacturer: z.string().optional().describe("Target manufacturer (jlcpcb, oshpark, pcbway)"),
      boardType: z.string().optional().describe("Board type: prototype, production, high-speed, power")
    },
    ({ manufacturer, boardType }) => ({
      messages: [
        {
          role: "user" as const,
          content: {
            type: "text" as const,
            text: `Guide me through making a PCB ready for manufacturing with ${manufacturer || 'JLCPCB'} (${boardType || 'prototype'} board).

## Step-by-Step Manufacturing Readiness Checklist

### 1. DESIGN RULES SETUP
Apply the correct manufacturing preset FIRST, before routing:
- Use \`apply_manufacturing_preset\` with the target fab house
- JLCPCB 2-layer: 0.127mm min trace/space, 0.3mm min drill, 0.6mm min via pad
- Recommended comfortable margins: 0.15mm clearance, 0.2mm trace, 0.3mm drill

### 2. TRACE WIDTH GUIDELINES
| Use Case | Width (mm) | Notes |
|----------|-----------|-------|
| Digital signals (3.3V/5V logic) | 0.2 - 0.25 | Standard, works everywhere |
| Fine-pitch routing (BGA, QFN) | 0.15 | Minimum for budget fabs |
| Power traces (< 1A) | 0.5 | Conservative for 1oz copper |
| Power traces (1-2A) | 0.75 - 1.0 | ~1mm per 1A at 10°C rise |
| Power traces (> 3A) | 2.0+ or copper pour | Use polygon pour for high current |
| USB 2.0 differential pair | 0.2 trace, 0.15 gap | ~90 ohm differential impedance |

### 3. VIA SIZING
| Type | Pad (mm) | Drill (mm) | Use |
|------|---------|-----------|-----|
| Standard signal | 0.6 | 0.3 | General routing, cheapest |
| Standard signal (comfortable) | 0.8 | 0.4 | Reliable, easier to inspect |
| Power via | 1.0 | 0.5 | Current-carrying paths |
| Thermal via array | 0.6 | 0.3 | Under thermal pads, 4-9 vias, 1.0mm pitch |

### 4. COPPER POUR BEST PRACTICES
- Add GND pour on bottom layer (B.Cu) for 2-layer boards — reduces EMI, provides return path
- Use thermal relief on ALL pads connecting to pours (default) — critical for hand soldering
- Add ground stitching vias every 5-10mm along board edges
- Keep pour clearance at 0.2mm minimum
- Avoid splitting ground plane under high-speed signals

### 5. COMPONENT PLACEMENT
- Decoupling caps: within 2-3mm of IC power pins, via directly to ground plane
- Typical values: 100nF on every power pin, 10uF bulk per IC cluster
- Keep analog and digital sections separated
- Orient all polarized components consistently (aids visual inspection)
- Minimum component-to-edge: 1.0mm (assembly requirement)

### 6. SILKSCREEN
- Minimum text height: 1.0mm (0.8mm absolute minimum)
- Minimum line width: 0.15mm
- Add reference designators for all components
- Add board name, revision, date on silkscreen
- Add pin-1 markers for ICs
- Keep silkscreen off pads (0.15mm clearance)

### 7. PRE-EXPORT CHECKLIST
1. Run \`validate_for_manufacturing\` with target fab preset
2. Run \`run_drc\` — fix ALL errors, review warnings
3. Verify board outline is closed (Edge.Cuts layer)
4. Check all mounting holes are correctly sized (M3 = 3.2mm hole, M2.5 = 2.7mm hole)
5. Verify no unconnected nets (unless intentional)

### 8. GERBER EXPORT
- Use \`export_gerber\` with: generateDrillFiles=true, useProtelExtensions=true
- Required files: F.Cu, B.Cu, F.SilkS, B.SilkS, F.Mask, B.Mask, Edge.Cuts + drill files
- ZIP all Gerber + drill files together for upload

### 9. ASSEMBLY FILES (if ordering SMT assembly)
- Export BOM in CSV format matching fab requirements
- Export position/centroid file (\`export_position_file\`)
- Verify LCSC part numbers if using JLCPCB assembly

What specific aspect would you like help with?`
          }
        }
      ]
    })
  );

  // ------------------------------------------------------
  // KiCad File Structure Guide
  // ------------------------------------------------------
  server.prompt(
    "kicad_file_structure_guide",
    {},
    () => ({
      messages: [
        {
          role: "user" as const,
          content: {
            type: "text" as const,
            text: `Explain KiCad's file structure and how the MCP tools manipulate them.

## KiCad Project File Structure

\`\`\`
project_name/
├── project_name.kicad_pro    # Project settings (JSON) — board stackup, libraries, DRC config
├── project_name.kicad_sch    # Schematic (S-expression) — symbols, wires, labels, power flags
├── project_name.kicad_pcb    # PCB layout (S-expression) — footprints, traces, zones, board outline
├── project_name-backups/     # Auto-backups
├── fp-lib-table              # Project-local footprint library paths
├── sym-lib-table             # Project-local symbol library paths
└── gerbers/                  # Export output directory
    ├── project_name-F_Cu.gtl     # Front copper Gerber
    ├── project_name-B_Cu.gbl     # Back copper Gerber
    ├── project_name-F_SilkS.gto  # Front silkscreen
    ├── project_name-B_SilkS.gbo  # Back silkscreen
    ├── project_name-F_Mask.gts   # Front solder mask
    ├── project_name-B_Mask.gbs   # Back solder mask
    ├── project_name-Edge_Cuts.gm1 # Board outline
    ├── project_name.drl          # Excellon drill file
    └── project_name-PTH.drl      # Plated through-hole drill
\`\`\`

## How MCP Tools Work With These Files

### Schematic (.kicad_sch) — S-expression format
The schematic file uses nested parenthesized expressions. MCP tools manipulate it by:
- **Text manipulation** for adding/removing components (avoids parser issues)
- **kicad-skip library** for reading symbol positions and properties
- **Regex-based UUID replacement** to ensure unique IDs on cloned symbols

Key sections:
- \`(lib_symbols ...)\` — Symbol definitions used in this schematic
- \`(symbol ...)\` — Placed symbol instances with position, rotation, properties
- \`(wire ...)\` — Electrical connections between pins
- \`(label ...)\` — Net labels that name wire connections
- \`(global_label ...)\` — Labels shared across hierarchical sheets
- \`(power_port ...)\` — Power symbols (VCC, GND, +3V3)

### PCB (.kicad_pcb) — S-expression format, manipulated via pcbnew SWIG API
The PCB file is manipulated through KiCad's Python bindings (pcbnew module), NOT by text editing.

Key objects:
- **BOARD** — Top-level container. Loaded with \`pcbnew.LoadBoard(path)\`
- **FOOTPRINT** — Placed component. Has pads, reference, value, position, layer
- **PCB_TRACK** — Copper trace segment. Has start/end points, width, layer, net
- **PCB_VIA** — Layer transition. Has position, drill size, layer pair, net
- **ZONE** — Copper pour (ground/power plane). Has outline, net, clearance, thermal settings
- **PCB_SHAPE** — Board outline, drawings on any layer
- **NETINFO_ITEM** — Net definition with name and net class assignment

### Workflow: Schematic → PCB
1. Create schematic: \`create_schematic\` → \`add_schematic_component\` → \`add_schematic_connection\` / \`connect_to_net\`
2. Generate netlist: \`generate_netlist\` (extracts all connections from schematic)
3. Sync to board: \`sync_schematic_to_board\` (creates footprints + nets on PCB)
4. Place components: \`move_component\` / \`align_components\`
5. Apply design rules: \`apply_manufacturing_preset\`
6. Route traces: \`route_pad_to_pad\` / \`autoroute\` (via Freerouting)
7. Add copper pours: \`add_copper_pour\` (GND plane)
8. Validate: \`run_drc\` + \`validate_for_manufacturing\`
9. Export: \`export_gerber\` (for fabrication)

### Layer Reference (2-layer board)
| Layer | Purpose | Notes |
|-------|---------|-------|
| F.Cu | Front copper | Signal routing + component pads |
| B.Cu | Back copper | Ground plane + additional routing |
| F.SilkS | Front silkscreen | Component labels, board markings |
| B.SilkS | Back silkscreen | Labels visible from bottom |
| F.Mask | Front solder mask | Openings for soldering (auto-generated) |
| B.Mask | Back solder mask | Same for bottom |
| Edge.Cuts | Board outline | MUST be a closed shape |
| F.CrtYd | Front courtyard | Component clearance zones (DRC only) |
| F.Fab | Front fabrication | Exact component body outline |
| Dwgs.User | User drawings | Notes, dimensions (not fabricated) |`
          }
        }
      ]
    })
  );

  logger.info('Design prompts registered');
}
