# Distribution Plan

This project should be easy to discover and install without routing user credentials through the maintainer's server.

The distribution strategy is:

1. Package the Python project cleanly.
2. Produce a local install path.
3. Produce client-specific bundle metadata where supported.
4. Publish neutral registry metadata.
5. List in the best MCP directories for discovery.
6. Keep hosted URL publishing optional and private-by-default.

## Chosen Distribution Stack

### Primary Artifact: Python Package

The Python package is the source of truth. It should support:

- `pip install`;
- editable local installs for development;
- command entrypoint for local MCP clients;
- Streamable HTTP server mode for VPS/app-platform hosting.

This keeps the project usable by technical users and by any registry that reads package metadata.

### Optional Bundle: MCPB

Use MCPB only as a client-specific one-click local install artifact when the target client supports MCPB.

Why:

- MCPB is an open bundle format for local MCP servers.
- It is designed for single-click desktop installation.
- It keeps credentials on the user's machine.
- It avoids turning the maintainer's server into a shared credential broker.

Why it is not universal:

- MCPB is not the MCP protocol.
- Many MCP clients use direct config files, command entries, URLs, or their own registries instead.
- The neutral implementation must work through stdio and Streamable HTTP without MCPB.

Bundling step:

```bash
npm install -g @anthropic-ai/mcpb
mcpb init
mcpb pack
```

The bundle manifest must require users to provide their own Google OAuth credentials or point to their own `gcp-oauth.keys.json`. Do not include real `.env`, database files, refresh tokens, or OAuth key files in the bundle.

This repository includes:

- `manifest.json` for MCPB bundling.
- `.mcpbignore` for bundle secret exclusions.
- `server.json` as the official MCP Registry metadata template.
- `metadata/glama.json` as a directory metadata template.

Before publishing, verify registry ownership according to the current registry docs. For PyPI publication, the official registry requires the package README to include an `mcp-name: ...` marker matching `server.json`.

### Primary Discovery: Official MCP Registry and MCP Find

Use the official MCP Registry for vendor-neutral metadata, then submit the project to MCP Find for open-source discovery and copy-paste client configuration.

Why:

- The official registry is the neutral metadata target.
- MCP Find is an open-source directory focused on discoverability and install snippets.
- Neither requires sharing the maintainer's Google credentials.

### Secondary Discovery and Testing: Glama

Use Glama as a secondary distribution/discovery target because it indexes tools, schemas, quality signals, and supports browser inspection.

Use only the parts that preserve the credential model:

- listing;
- metadata indexing;
- inspector/testing with user-provided auth;
- optional hosting only for users who choose to host their own instance.

Do not use managed hosting for a public shared endpoint connected to the maintainer's Google account.

### Optional: Smithery

Smithery is optional, not the default.

Use it if it provides the easiest install route for a specific audience or client. Prefer local/package distribution over a shared hosted endpoint.

## Release Checklist

Before publishing a release:

- Confirm `.env`, `gcp-oauth.keys.json`, `*.db`, and token stores are ignored.
- Confirm the package installs from a clean environment.
- Confirm local MCP startup works.
- Confirm remote `/mcp` startup works.
- Confirm OAuth bootstrap works from environment variables.
- Confirm OAuth bootstrap works from `gcp-oauth.keys.json`.
- Confirm tests pass.
- Generate or update MCPB manifest metadata.
- Build the `.mcpb` artifact.
- Inspect the bundle contents for secret leakage.
- Publish source release.
- Submit or update registry metadata.
- Submit or update directory listings.

## Marketplace Choice

Use this order:

1. **Python package plus stdio/Streamable HTTP instructions** for the universal install path.
2. **Official MCP Registry** for canonical metadata.
3. **MCP Find** for open-source discovery and install snippets.
4. **Glama** for richer inspection, scoring, and optional user-controlled deployment.
5. **MCPB** only for compatible clients.
6. **Smithery** only if it offers the smoothest install path for a target client.

This order keeps the project portable and avoids lock-in while still meeting the user's goal: easy installation for people who run their own server with their own credentials.

## Client Compatibility

MCPB is not universal. The project must remain usable through standard MCP transports without any marketplace or bundle.

### Claude Desktop Spotlight

Claude Desktop should be treated as a first-class distribution target.

For remote HTTP mode, Claude Desktop uses a local stdio bridge. Install `mcp-remote` on the machine running Claude Desktop:

```bash
npm install -g mcp-remote
```

Working local HTTP config:

```json
{
  "mcpServers": {
    "google-tasks": {
      "command": "mcp-remote",
      "args": [
        "http://127.0.0.1:8787/mcp",
        "--header",
        "Authorization: Bearer <MCP_BEARER_TOKEN>"
      ]
    }
  }
}
```

For a VPS deployment, replace the URL with `https://your-domain.example/mcp`.

Do not publish real bearer tokens in docs, bundles, examples, screenshots, or registry metadata. For user-facing docs, prefer `<MCP_BEARER_TOKEN>` placeholders. For configs meant to avoid inline secrets, pass the header value through an environment variable instead.

| Client or runtime | Best-supported setup for this project |
| --- | --- |
| Claude Desktop | `mcp-remote` bridge to local or VPS Streamable HTTP `/mcp`; MCPB may be offered as an optional local-install artifact where supported. |
| Codex | Remote Streamable HTTP URL or local stdio command configured in Codex MCP settings. |
| OpenAI Agents SDK | `MCPServerStreamableHttp` for VPS/hosted use; `MCPServerStdio` for local subprocess use. |
| ChatGPT Apps/API integrations | Remote MCP server over HTTPS. |
| Ollama-based workflows | Ollama is the model runtime, not the MCP client. Use an MCP-capable host or bridge around Ollama, then configure this server through stdio or Streamable HTTP. Do not assume MCPB. |
| OpenClaw | Stdio-oriented MCP server/client registry flows; provide command-based config. |
| VS Code/Cursor-style clients | JSON MCP config with either HTTP URL or local command. |

Universal support target:

1. Python package install.
2. Local stdio command mode.
3. Remote Streamable HTTP `/mcp`.
4. Neutral registry metadata.
5. Optional client-specific bundles.

Do not let MCPB, Smithery, Glama, or any marketplace define the server architecture.

## References

- MCPB repository: <https://github.com/modelcontextprotocol/mcpb>
- OpenAI Docs MCP quickstart: <https://developers.openai.com/learn/docs-mcp>
- OpenAI MCP server guide: <https://developers.openai.com/api/docs/mcp>
- OpenAI Agents SDK MCP docs: <https://openai.github.io/openai-agents-python/mcp/>
- OpenClaw MCP docs: <https://docs.openclaw.ai/cli/mcp>
- Glama: <https://glama.ai/>
- MCP Find: <https://mcpfind.org/>
- Smithery publishing: <https://smithery.ai/docs/build/publish>
