---
paths:
  - "**/*.py"
  - "**/*.pyi"
---
# Python Coding Style

> This file extends [common/coding-style.md](../common/coding-style.md) with Python specific content.

## Standards

- Follow **PEP 8** conventions
- Use **type annotations** on all function signatures

## Immutability

Prefer immutable data structures:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class User:
    name: str
    email: str

from typing import NamedTuple

class Point(NamedTuple):
    x: float
    y: float
```

## Formatting

This repo has no black/isort/ruff configuration — match the existing style of the file you are editing instead of reformatting it. For new standalone code, defaults:

- **black** for code formatting
- **isort** for import sorting
- **ruff** for linting

## Project conventions (vnstock-dashboard)

- User-facing output (brief, UI) is in **Vietnamese**; numbers use EN format (`{:,.2f}` — comma thousands, dot decimals).
- Important constraints go into **deterministic guards in code + tests**, never only into LLM prompts.
- Auto-refresh features are best-effort and need an env kill-switch (`VNSTOCK_BRIEF_AUTO_*`, `VNSTOCK_MACRO_*`).

## Reference

See skill: `python-patterns` for comprehensive Python idioms and patterns.
