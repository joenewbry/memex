#!/bin/bash
# Bridge for Claude Desktop → remote Memex MCP via mcp-remote
# Forces Node 22 to avoid ReadableStream errors with Node 16
export PATH="/Users/joe/.nvm/versions/node/v22.17.0/bin:$PATH"
exec npx mcp-remote "$@"
