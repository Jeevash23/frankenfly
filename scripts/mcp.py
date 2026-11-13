"""DigitalFly's MCP server over stdio, for agents such as Claude Code (see docs/USAGE.md#agents-and-the-mcp-server).

    backend/.venv/bin/python scripts/mcp.py [--url http://127.0.0.1:8000] [--audit-log audit/mcp.jsonl]
    backend/.venv/bin/python scripts/mcp.py --list-tools

Needs the app running (./scripts/start.sh) and the MCP SDK (./scripts/setup.sh --with mcp). The installed
`digitalfly-mcp` command (backend/.venv/bin/digitalfly-mcp) does the same.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
# Python puts this script's folder first on the path, where this file would shadow the `mcp` package itself.
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != HERE]
sys.path.insert(0, str(ROOT / "backend/src"))

from digitalfly.mcp import main  # noqa: E402

if __name__ == "__main__":
    main()
