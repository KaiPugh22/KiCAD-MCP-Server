import os
import sys

# Ensure the plugin package directory is on sys.path for imports
plugin_dir = os.path.dirname(os.path.abspath(__file__))
if plugin_dir not in sys.path:
    sys.path.insert(0, plugin_dir)

from .plugin import MCP_BRIDGE_ACTION

def register():
    MCP_BRIDGE_ACTION().register()
