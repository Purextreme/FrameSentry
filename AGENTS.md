# Repository Guidelines

## Project Structure & Module Organization

FrameSentry is a Python package with a Streamlit UI and a modular, decoupled analyzer design. The main app entry point is `app.py`. Core code lives in `framesentry/`: `scanner.py` coordinates analysis and report writing, `analysis.py` defines the analyzer contract, `analyzers/` contains high-level modules, `detectors/` contains frame issue detection logic, and `utils/` contains shared helpers. Tests and smoke checks are in `tests/`. Documentation assets are in `docs/images/`, sample notes are in `samples/`, and generated reports should stay under `output/`.

## Build, Test, and Development Commands

Create and install the recommended Windows virtual environment:

```bat
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Run the Streamlit UI:

```bat
.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

Run the unit test suite:

```bat
.venv\Scripts\python.exe -m unittest discover -s tests
```

Run synthetic video end-to-end checks after detector or scanner changes:

```bat
.venv\Scripts\python.exe tests\synthetic_video_check.py
```

## Coding Style & Naming Conventions

Use Python 3.10+ syntax and 4-space indentation. Prefer `pathlib.Path` for filesystem paths and keep JSON report data serializable. Use `snake_case` for functions, variables, modules, and test files; use `PascalCase` for classes such as analyzers and dataclasses. Keep UI display labels in `app.py` or `framesentry/presentation.py`; keep scanning and detection behavior out of the Streamlit layer.

## Testing Guidelines

Tests use the standard `unittest` framework. Name files `test_*.py` and place focused tests beside related behavior in `tests/`. For narrow logic changes, run the relevant test file first. For report schema, cache, analyzer registration, or scanner behavior, run the full discovery command. For detection threshold changes, also run `tests\synthetic_video_check.py`.

## Commit & Pull Request Guidelines

Existing commits use short imperative summaries, for example `Add color analysis module` and `Decouple report-level cache`. Follow that style: one clear sentence, no trailing period. Pull requests should describe the user-visible change, list verification commands, note report schema or cache impacts, and include screenshots when Streamlit UI behavior changes.

## Architecture Notes

The architecture intentionally separates UI, scan orchestration, analyzer modules, and low-level detectors. New analysis modules should return `ModuleResult` and be registered through `AnalyzerRegistry`. The report schema is module-first under top-level `modules`; do not reintroduce legacy top-level `events`, `thresholds`, `source_file`, or `analysis_options`.
