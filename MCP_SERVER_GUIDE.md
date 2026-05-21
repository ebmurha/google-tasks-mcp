# MCP Server Guide

This project is an MCP server because it exposes tools over the Model Context Protocol. The tools happen to call Google Tasks behind the scenes.

## What "Server" Means Here

An MCP server is not automatically a public SaaS product. It is a program that an MCP client can call to discover tools and invoke them.

This project can be used in three main ways:

- **Local MCP server:** the client starts the Python process on the same machine.
- **Remote MCP server:** the Python process runs somewhere else and exposes an HTTPS `/mcp` endpoint.
- **Packaged MCP server:** a registry or installer helps users install their own local or hosted copy.

All three are valid MCP distribution models. The difference is how the client reaches or installs the process.

## Private Single-Account Mode

The default design is private and single-account, with an optional multi-account bearer-token mode for trusted operators.

In legacy mode, one deployment stores one Google refresh token. Every MCP client with `MCP_BEARER_TOKEN` can act on that same Google Tasks account. That is appropriate for a personal assistant setup, private automation, or a trusted internal tool.

In multi-account bearer-token mode, the operator creates a separate bearer token for each `account_id`. The raw bearer token is shown once; only its hash is stored in SQLite. Each token selects one Google OAuth token row and one tasklist-title cache namespace. This supports several trusted accounts on one server without adding an MCP tool parameter for account selection.

`GOOGLE_OAUTH_KEYS_PATH` is different: it points to the Google Cloud OAuth client JSON, not to a Google Tasks user account. A familiar setup can use one OAuth client JSON for both `personal` and `work`; the operator runs `google-tasks-mcp-bootstrap --account-id personal` while logged into the personal Google account, then `google-tasks-mcp-bootstrap --account-id work` while logged into the work Google account. Those two refresh tokens are stored separately and selected later by their bearer tokens.

In this mode, a VPS is a normal place to host it. Your VPS is the remote machine running the MCP server, and your MCP clients connect to it over HTTPS.

This is not a service for arbitrary users unless you intentionally share the endpoint and bearer token. Anyone with the bearer token can read and modify the connected Google Tasks account.

## Public Project vs Public Service

A public GitHub repository means anyone can inspect, install, and run their own copy.

A public MCP service means other people can connect to your running server.

This repository should be public-facing in the first sense: reusable code and clear setup instructions. Your personal VPS deployment should remain private unless you build multi-user auth and account separation.

## Zero-Leakage Rule

The safe default is that credentials never leave the operator's control:

- Google OAuth client secrets stay in `.env`, a private environment store, or `gcp-oauth.keys.json`.
- `gcp-oauth.keys.json` is ignored by git and must not be published.
- The Google refresh token stays in the operator's SQLite database or private persistent store.
- Bearer tokens are shared only with trusted MCP clients.
- Multi-account bearer tokens are stored only as hashes; raw tokens are not recoverable from SQLite.
- A registry listing should distribute code and metadata, not your personal Google credentials or refresh token.

## Hosting Options

### VPS

A VPS is a good fit for a personal remote MCP server.

Use it when you want:

- a stable public HTTPS URL;
- direct control over systemd, Caddy, logs, and disk;
- persistent SQLite storage;
- a simple single-user deployment.

The server remains private if you keep `MCP_BEARER_TOKEN` secret.

When OAuth gateway mode is enabled for MCP clients that support OAuth, the gateway stores MCP OAuth refresh tokens by hash in SQLite. This is separate from Google OAuth refresh-token storage and lets OAuth-capable MCP clients refresh access after server restarts without re-authorizing.

### Local Machine

A local process is good when the MCP client runs on the same computer and supports command-based MCP servers.

Use it when you do not need a public HTTPS endpoint.

### Container or App Platform

Container and app platforms can work if they support:

- long-running HTTP services;
- environment variables for secrets;
- persistent storage for the SQLite database;
- HTTPS ingress.

They are less useful if the filesystem is ephemeral, because the OAuth refresh token must survive restarts.

### Serverless Platforms

Serverless can be awkward for this project. The MCP HTTP transport expects a reachable service, and the OAuth token store needs persistent state. It can work with an external database, but that is not the default design.

### Marketplaces and Registries

Marketplaces and registries should be treated as discovery and installation layers, not a reason to centralize everyone's Google credentials into one shared server.

There are three viable models:

- **Registry listing:** publish metadata that points users to the source package, install command, docs, and supported transports.
- **Local/package distribution:** publish an installable package or bundle so every user runs their own copy and connects their own Google account.
- **URL publishing:** publish a hosted Streamable HTTP endpoint. This is suitable for your own private deployment or a controlled team deployment. It is not suitable as a public service if the endpoint is wired to your personal Google account.

For public users, registry listing plus local/package distribution is the privacy-preserving default.

Use [DISTRIBUTION.md](./DISTRIBUTION.md) for the current target list and bundling steps.

## What Is Needed for Other People to Use It

If "other people can use it" means they install their own copy, the public README is enough.

If "other people can connect to your hosted MCP server as an open public service", the current design is still missing several things:

- self-service user onboarding;
- public user identity and lifecycle management;
- user-controlled Google OAuth consent per account;
- an onboarding flow for users to connect Google;
- operational controls such as revocation, audit logs, and rate limits.

The stored bearer-token account model is suitable for trusted operator-created accounts, not arbitrary public signup.

If the goal is public discovery without shared credentials, publish the project/package and require each user to configure one of:

- their own `.env`;
- their own `gcp-oauth.keys.json`;
- their own hosted URL and bearer token.

## Recommended Path

For your planned VPS deployment, treat this as a private remote MCP server:

1. Host the Python service on the VPS.
2. Put Caddy or another reverse proxy in front of it.
3. Serve `/mcp` over HTTPS.
4. Keep `/mcp` protected by `MCP_BEARER_TOKEN` or stored per-account bearer tokens.
5. Bootstrap OAuth once for your Google account.
6. Add the HTTPS URL and bearer token to your MCP client.

That is enough for any MCP-compatible client or app to call the MCP tools, as long as it supports remote HTTP MCP connections.

Do not advertise your personal endpoint as a public service unless you first add self-service onboarding, public-user controls, auditability, and rate limiting.
