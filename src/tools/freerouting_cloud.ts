/**
 * Freerouting Cloud API Tools
 * Provides cloud-based autorouting via the Freerouting REST API
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerFreeroutingCloudTools(
  server: McpServer,
  callKicadScript: (cmd: string, args: Record<string, unknown>) => Promise<string>
) {
  server.tool(
    "cloud_autoroute",
    `Route the PCB using Freerouting's cloud API (no local Java needed).
Exports board to DSN, sends to api.freerouting.app, and imports routed SES result.
Requires FREEROUTING_API_KEY env var or api_key parameter. Supports local server too.`,
    {
      board_path: z.string().optional().describe("Path to .kicad_pcb (uses current board if omitted)"),
      max_passes: z.number().optional().describe("Maximum routing passes (default 20)"),
      timeout: z.number().optional().describe("Routing timeout in seconds (default 300)"),
      api_key: z.string().optional().describe("Freerouting API key (or set FREEROUTING_API_KEY env)"),
      use_local: z.boolean().optional().describe("Use local Freerouting server at localhost:37864"),
    },
    async (args) => {
      const result = await callKicadScript("cloud_autoroute", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "cloud_route_job",
    `Start a multi-step cloud routing job with progress tracking.
Use for complex boards that need longer routing times or custom monitoring.`,
    {
      board_path: z.string().optional().describe("Path to .kicad_pcb"),
      job_name: z.string().optional().describe("Name for the routing job"),
      max_passes: z.number().optional().describe("Maximum routing passes (default 20)"),
      timeout: z.number().optional().describe("Total timeout in seconds (default 600)"),
      poll_interval: z.number().optional().describe("Status check interval in seconds (default 5)"),
      api_key: z.string().optional().describe("Freerouting API key"),
      use_local: z.boolean().optional().describe("Use local Freerouting server"),
    },
    async (args) => {
      const result = await callKicadScript("cloud_route_job", args);
      return { content: [{ type: "text", text: result }] };
    }
  );

  server.tool(
    "check_cloud_routing",
    "Check Freerouting cloud API connectivity and authentication status",
    {
      use_local: z.boolean().optional().describe("Check local server instead of cloud"),
    },
    async (args) => {
      const result = await callKicadScript("check_cloud_status", args);
      return { content: [{ type: "text", text: result }] };
    }
  );
}
