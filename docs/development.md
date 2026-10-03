# Development

## Prepare the environment

Use a different CPython environment for development and release checks.
The lock file fixes dependency versions.
The desktop tests need the desktop extra.

```powershell
uv python install 3.12
uv sync --locked --extra desktop --extra dev --extra package
```

## Automatic checks

```powershell
uv run ruff check terminx tests scripts packaging
uv run ruff format --check terminx tests scripts packaging
uv run python scripts/check_docs.py
uv run python -c "from PySide6.QtCore import qVersion; print(qVersion())"
uv run python -m coverage run -m unittest discover -s tests
uv run python -m coverage report
uv run python -m terminx --once
```

Use `QT_QPA_PLATFORM=offscreen` for automatic Qt tests.
Do not use that variable for a real desktop check.
The import check prevents a missing desktop library from hiding skipped tests.
The CI workflow checks Windows and Linux.
Windows checks include the desktop libraries.

## Review a change

1. Describe the observed problem.
2. Identify the module that owns the behavior.
3. Add a regression test for a change to identity, state, startup, or package behavior.
4. Make the smallest complete correction.
5. Run the applicable checks.
6. Review the diff for readability and unrelated edits.
7. Update the documentation and change record.

Use descriptive function names and explicit module boundaries.
Use one statement per line.
Keep source and package commands equivalent.
Do not infer state from silence or terminal identity from a folder.
Do not store prompt content in the journal.

## Native desktop checks

```powershell
uv run python tests/native_acceptance.py
uv run python tests/native_existing_acceptance.py
uv run python tests/sidebar_native_controls.py
uv run python tests/sidebar_visual.py _artifacts/sidebar.png
```

These commands use the current Windows desktop.
They open dedicated probe terminals.
They do not request provider model output.
Each probe records process identity before cleanup.

## Add a provider

1. Define its data home and native session ID.
2. Define its authoritative state events.
3. Implement its adapter.
4. Register the adapter in `agents/__init__.py`.
5. Add log and process fixtures.
6. Document its quota capabilities and limits.

Unknown capabilities must stay explicit.
For interface translations, preserve placeholders and Rich markup.
The catalog tests detect missing and unused literal keys.
