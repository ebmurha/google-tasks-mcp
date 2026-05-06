# Contributing

## Development setup

```bash
git clone https://github.com/ebmurha/google-tasks-mcp.git
cd google-tasks-mcp
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]

## Run tests

```bash
pytest
```

## Code style

- Keep changes focused
- Add tests for behavior changes
- Update documentation where needed

## Pull requests

- Create a feature branch
- Open a PR against `main`
- Ensure CI passes
- Require at least one review
