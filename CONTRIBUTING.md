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


---

## `SECURITY.md`

```md
# Security Policy

## Reporting a Vulnerability

Do not open public issues for security vulnerabilities.

Report privately to: security@yourdomain.com

Include:

- description
- impact
- reproduction steps
- affected version

You will receive acknowledgement within 3 business days.