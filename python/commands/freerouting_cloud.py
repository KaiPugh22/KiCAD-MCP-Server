"""
Freerouting Cloud API integration for KiCAD MCP Server.

Provides autorouting via the Freerouting REST API (api.freerouting.app)
as an alternative to the local JAR-based approach. Supports both the
simple single-turn autoroute and the multi-step job workflow.

Requires: requests (pip install requests)
API key: set FREEROUTING_API_KEY environment variable, or pass api_key param.
"""

import os
import json
import time
import logging
import tempfile
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger("kicad_interface")

DEFAULT_API_URL = "https://api.freerouting.app/v1"
LOCAL_API_URL = "http://127.0.0.1:37864"


class FreeroutingCloudCommands:
    def __init__(self, board=None):
        self.board = board

    def _get_api_key(self, params: Dict[str, Any]) -> Optional[str]:
        return params.get("api_key") or os.environ.get("FREEROUTING_API_KEY")

    def _get_base_url(self, params: Dict[str, Any]) -> str:
        if params.get("use_local"):
            return LOCAL_API_URL
        return params.get("api_url", DEFAULT_API_URL)

    def _export_dsn(self, board_path: Optional[str] = None) -> str:
        """Export current board to DSN using kicad-cli."""
        if not board_path and self.board:
            board_path = self.board.GetFileName()
        if not board_path:
            raise ValueError("No board path available")

        dsn_path = str(Path(board_path).with_suffix(".dsn"))

        result = subprocess.run(
            ["kicad-cli", "pcb", "export", "specctra", board_path, "-o", dsn_path],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            raise RuntimeError(f"DSN export failed: {result.stderr}")

        return dsn_path

    def _import_ses(self, ses_path: str, board_path: Optional[str] = None) -> Dict[str, Any]:
        """Import SES file back into board using kicad-cli."""
        if not board_path and self.board:
            board_path = self.board.GetFileName()
        if not board_path:
            raise ValueError("No board path available")

        result = subprocess.run(
            ["kicad-cli", "pcb", "import", "specctra", board_path, "-i", ses_path],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            raise RuntimeError(f"SES import failed: {result.stderr}")

        return {"success": True, "ses_path": ses_path, "board_path": board_path}

    def cloud_autoroute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Single-turn cloud autoroute via Freerouting REST API."""
        try:
            import requests
        except ImportError:
            return {
                "success": False,
                "error": "requests library not installed. Run: pip install requests"
            }

        api_key = self._get_api_key(params)
        base_url = self._get_base_url(params)
        board_path = params.get("board_path")
        max_passes = params.get("max_passes", 20)
        timeout_seconds = params.get("timeout", 300)

        try:
            dsn_path = self._export_dsn(board_path)
            with open(dsn_path, "r") as f:
                dsn_content = f.read()

            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            payload = {
                "input": {"dsn": dsn_content},
                "router_settings": {"autorouter": {"max_passes": max_passes}},
                "output_formats": ["SES", "DRC_SUMMARY"],
                "timeout_seconds": timeout_seconds,
            }

            logger.info(f"Sending board to Freerouting cloud ({base_url})...")
            resp = requests.post(
                f"{base_url}/autoroute",
                json=payload,
                headers=headers,
                timeout=timeout_seconds + 30,
            )

            if resp.status_code == 401:
                return {
                    "success": False,
                    "error": "Authentication failed. Set FREEROUTING_API_KEY or pass api_key parameter."
                }
            resp.raise_for_status()
            result = resp.json()

            ses_content = result.get("outputs", {}).get("SES", "")
            if not ses_content:
                return {
                    "success": False,
                    "error": "No SES output received from Freerouting",
                    "result": result
                }

            ses_path = str(Path(dsn_path).with_suffix(".ses"))
            with open(ses_path, "w") as f:
                f.write(ses_content)

            import_result = self._import_ses(ses_path, board_path)

            drc_summary = result.get("outputs", {}).get("DRC_SUMMARY", "")
            unrouted = result.get("unrouted_connections", [])

            return {
                "success": True,
                "method": "cloud_api",
                "ses_path": ses_path,
                "board_path": import_result["board_path"],
                "drc_summary": drc_summary,
                "unrouted_count": len(unrouted),
                "unrouted_connections": unrouted[:20],
                "routing_time_seconds": result.get("routing_time_seconds"),
            }

        except Exception as e:
            logger.error(f"Cloud autoroute failed: {e}")
            return {"success": False, "error": str(e)}

    def cloud_route_job(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Multi-step cloud routing job with status tracking."""
        try:
            import requests
        except ImportError:
            return {
                "success": False,
                "error": "requests library not installed. Run: pip install requests"
            }

        api_key = self._get_api_key(params)
        base_url = self._get_base_url(params)
        board_path = params.get("board_path")
        job_name = params.get("job_name", "MCP Routing Job")
        max_passes = params.get("max_passes", 20)
        timeout = params.get("timeout", 600)
        poll_interval = params.get("poll_interval", 5)

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            dsn_path = self._export_dsn(board_path)
            with open(dsn_path, "r") as f:
                dsn_content = f.read()

            import base64
            dsn_b64 = base64.b64encode(dsn_content.encode()).decode()

            session_resp = requests.post(
                f"{base_url}/sessions/create", headers=headers, json={}, timeout=30
            )
            session_resp.raise_for_status()
            session_id = session_resp.json().get("id")

            job_resp = requests.post(
                f"{base_url}/jobs/enqueue",
                headers=headers,
                json={"session_id": session_id, "name": job_name, "priority": "NORMAL"},
                timeout=30
            )
            job_resp.raise_for_status()
            job_id = job_resp.json().get("id")

            requests.post(
                f"{base_url}/jobs/{job_id}/input",
                headers=headers,
                json={"filename": "board.dsn", "data": dsn_b64},
                timeout=60
            ).raise_for_status()

            requests.post(
                f"{base_url}/jobs/{job_id}/settings",
                headers=headers,
                json={"max_passes": max_passes},
                timeout=30
            ).raise_for_status()

            requests.put(
                f"{base_url}/jobs/{job_id}/start",
                headers=headers,
                timeout=30
            ).raise_for_status()

            start_time = time.time()
            terminal_states = {"COMPLETED", "CANCELLED", "FAILED", "TERMINATED", "TIMED_OUT", "INVALID"}

            while time.time() - start_time < timeout:
                status_resp = requests.get(
                    f"{base_url}/jobs/{job_id}",
                    headers=headers,
                    timeout=30
                )
                status_resp.raise_for_status()
                job_info = status_resp.json()
                state = job_info.get("state", "UNKNOWN")

                if state in terminal_states:
                    break
                time.sleep(poll_interval)
            else:
                return {
                    "success": False,
                    "error": f"Routing job timed out after {timeout}s",
                    "job_id": job_id,
                    "last_state": state,
                }

            if state != "COMPLETED":
                return {
                    "success": False,
                    "error": f"Routing job ended with state: {state}",
                    "job_id": job_id,
                }

            output_resp = requests.get(
                f"{base_url}/jobs/{job_id}/output",
                headers=headers,
                timeout=60
            )
            output_resp.raise_for_status()
            output_data = output_resp.json()
            ses_b64 = output_data.get("data", "")
            ses_content = base64.b64decode(ses_b64).decode()

            ses_path = str(Path(dsn_path).with_suffix(".ses"))
            with open(ses_path, "w") as f:
                f.write(ses_content)

            import_result = self._import_ses(ses_path, board_path)

            drc_resp = requests.get(
                f"{base_url}/jobs/{job_id}/drc/summary",
                headers=headers,
                timeout=30
            )
            drc_summary = drc_resp.json() if drc_resp.ok else {}

            return {
                "success": True,
                "method": "cloud_job",
                "job_id": job_id,
                "session_id": session_id,
                "ses_path": ses_path,
                "board_path": import_result["board_path"],
                "drc_summary": drc_summary,
                "routing_time_seconds": time.time() - start_time,
            }

        except Exception as e:
            logger.error(f"Cloud routing job failed: {e}")
            return {"success": False, "error": str(e)}

    def check_cloud_status(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Check Freerouting cloud API status and connectivity."""
        try:
            import requests
        except ImportError:
            return {
                "success": False,
                "requests_installed": False,
                "error": "requests library not installed. Run: pip install requests"
            }

        api_key = self._get_api_key(params)
        base_url = self._get_base_url(params)

        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        result = {
            "success": True,
            "requests_installed": True,
            "api_url": base_url,
            "api_key_set": bool(api_key),
        }

        try:
            resp = requests.get(f"{base_url}/system/status", headers=headers, timeout=10)
            result["api_reachable"] = True
            result["api_status"] = resp.json() if resp.ok else {"status_code": resp.status_code}
        except requests.exceptions.ConnectionError:
            result["api_reachable"] = False
            result["error"] = f"Cannot reach {base_url}"
            result["success"] = False
        except Exception as e:
            result["api_reachable"] = False
            result["error"] = str(e)
            result["success"] = False

        if not api_key and base_url == DEFAULT_API_URL:
            result["note"] = "No API key set. Set FREEROUTING_API_KEY env var for cloud routing."

        return result
