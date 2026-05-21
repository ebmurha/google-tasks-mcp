# Step 17 Evidence: Tool discoverability metadata

Date: 2026-05-21

## SDK Capability Checked

The installed MCP Python SDK exposes these supported fields on `FastMCP.add_tool` and `mcp.types.Tool`:

- `title`
- `description`
- `annotations`
- `icons`
- `_meta`

`ToolAnnotations` supports:

- `title`
- `readOnlyHint`
- `destructiveHint`
- `idempotentHint`
- `openWorldHint`

No first-class grouping field is available, so the implementation uses only standard titles, descriptions, and annotations. Tool groups are documented in the spec and README without adding wrapper/category tools or custom wire fields.

## Commands Run

```powershell
pytest tests/test_tools.py::test_registered_mcp_tools_have_exact_names_and_metadata -q
pytest tests/test_tools.py tests/test_release_artifacts.py -x
pytest -x
git diff --check
```

## Results Observed

- Metadata registration test: 1 passed.
- Tool and release-artifact tests: 60 passed.
- Full suite: 133 passed.
- `git diff --check`: no whitespace errors.

## Implementation Notes

- All 19 tool names are unchanged.
- Every tool has a human-readable title and description in `list_tools`.
- Read-only tools set `readOnlyHint=true`.
- Destructive tools set `destructiveHint=true`.
- All tools set `openWorldHint=true` because they interact with Google Tasks outside the MCP host.
