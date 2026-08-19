---
paths:
  - "**/*.py"
  - "**/*.pyi"
---
# Python Testing

> This file extends [common/testing.md](../common/testing.md) with Python specific content.

## Framework

Use **pytest** as the testing framework. In this repo, always run it through the orchestrator:

```bash
python run.py test --fast   # ~1,683 tests, ~31s — after any core-module change
python run.py test          # full suite, ~2,203 tests, ~40s — before any PR to main
```

Results are written to `data_warehouse/_meta/test_status.json` (sidebar badge). Red badge = no merge/deploy.

## Coverage

No coverage threshold is enforced in this repo (`pytest-cov` is not configured). Generic projects:

```bash
pytest --cov=src --cov-report=term-missing
```

## Test Organization

Use `pytest.mark` for test categorization:

```python
import pytest

@pytest.mark.unit
def test_calculate_total():
    ...

@pytest.mark.integration
def test_database_connection():
    ...
```

## Reference

See skill: `python-testing` for detailed pytest patterns and fixtures.
