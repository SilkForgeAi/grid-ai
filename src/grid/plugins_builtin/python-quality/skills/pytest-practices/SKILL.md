---
name: pytest-practices
description: How to write good pytest tests - use when adding, fixing or reviewing Python tests.
---
# Pytest practices

- One behavior per test; name tests after the behavior (`test_rejects_empty_password`).
- Arrange / act / assert, with the assertion about the observable result, not internals.
- Use `tmp_path` for files, `monkeypatch` for env vars and attributes, `pytest.raises(..., match=...)` for errors.
- Parametrize instead of copy-pasting near-identical tests.
- A bug fix starts with a test that fails without the fix.
- Never mark a failing test skip/xfail to get green, and never weaken an assertion to make it pass.
- Run the narrowest test first (`pytest tests/test_x.py::test_y -q`), then the whole suite before finishing.
