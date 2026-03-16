#!/usr/bin/env python3
"""
MCP server that bridges AI agents to the UnrealAgentBridge C++ TCP plugin.

Three tools: exec_python, describe_object, generate_catalog.
Each tool opens a TCP connection to the C++ plugin, sends a JSON command,
and returns the JSON response.
"""

import json
import os
import socket
from mcp.server.fastmcp import FastMCP

HOST = os.environ.get("AGENT_BRIDGE_HOST", "127.0.0.1")
PORT = int(os.environ.get("AGENT_BRIDGE_PORT", "13090"))

mcp = FastMCP("unreal-agent-bridge")


def _send(command: str, params: dict) -> dict:
    """Send a command to UnrealAgentBridge and return the parsed response."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(120)
    try:
        sock.connect((HOST, PORT))
        payload = json.dumps({"command": command, "params": params}).encode("utf-8") + b"\n"
        sock.sendall(payload)

        # Receive until newline
        chunks: list[bytes] = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
            if b"\n" in b"".join(chunks):
                break

        raw = b"".join(chunks).split(b"\n")[0]
        return json.loads(raw)
    except ConnectionRefusedError:
        return {
            "success": False,
            "error": (
                f"Cannot connect to UnrealAgentBridge on {HOST}:{PORT}. "
                "Ensure the Unreal Editor is running with the UnrealAgentBridge plugin enabled."
            ),
        }
    except socket.timeout:
        return {"success": False, "error": "Request timed out (120s)"}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        sock.close()


@mcp.tool()
def exec_python(code: str) -> dict:
    """Execute Python code in the running Unreal Editor's Python environment.

    Single expressions are auto-detected and evaluated for a return value.
    Multi-line scripts, imports, and control flow use file-execution mode.

    Args:
        code: Python code to execute. Can be a single expression or multi-line script.

    Returns:
        dict with 'success', 'result' (expression value), and 'log_output' (print/warnings).
    """
    return _send("exec_python", {"code": code})


@mcp.tool()
def describe_object(class_name: str) -> dict:
    """Get live UHT reflection data for a UClass: all BlueprintCallable functions and properties.

    Accepts a class name (e.g. "Actor", "EditorAssetLibrary") or a full object path.
    Automatically tries U- and A- prefixes if the exact name is not found.

    Args:
        class_name: The UClass name or object path to introspect.

    Returns:
        dict with class_name, parent_class, functions (with params/return types), properties.
    """
    return _send("describe_object", {"object_path": class_name})


@mcp.tool()
def generate_catalog(output_dir: str = "") -> dict:
    """Generate or refresh the callable function catalog JSON files.

    Scans all loaded UClasses via UHT reflection, filters to BlueprintCallable functions,
    and writes:
      - catalog_index.json  (category index + class index)
      - classes/*.json      (per-class function signatures)

    Args:
        output_dir: Optional output directory. Defaults to Engine/.claude/knowledge/callable_catalog/

    Returns:
        dict with success, output_dir, total_classes, total_functions.
    """
    return _send("generate_catalog", {"output_dir": output_dir})


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
