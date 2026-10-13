# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project

**robot_planning** plans photocatalysis runs on a pipetting robot. In a small Streamlit
app the user states the final concentration of photosensitizer, catalyst and sacrificial
oxidant, the pH and the robot settings per experiment, plus the buffer system, total
buffer concentration and number of vials per experiment for the run. Buffer acid and
base follow from the pH. The planner chooses one stock solution
per component so that every vial receives 0.2–0.85 mL of it, fills up with water, and
writes the run files: `experiments_design.csv`, `stock_solutions.csv` and the robot
input `experiment.yml`. If a run is impossible within these limits, it says why.

Keep it simple: this is a small lab tool used by one person, not a library.

Set up with:

```bash
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

## Repository layout

- [planner.py](planner.py) — all calculation and file writing; no Streamlit.
- [app.py](app.py) — Streamlit UI; only input widgets and display, calls `planner`.
- [chemicals.CSV](chemicals.CSV) — chemicals database (name, category, molar mass, solubility). Changes rarely.
- [buffers.CSV](buffers.CSV) — buffer systems (acid, base, pKa); acid and base refer to `chemicals.CSV`.
- [docs/planning.md](docs/planning.md) — how and why the planner calculates what it does.
- [tests/](tests/) — pytest suite.
- `runs/` — output folders, one per saved run, created by the app.

## Domain conventions

- **One stock solution per role and run.** The robot has one position per role, so all vials of a run share the five chemicals and differ only in volumes. Never introduce several stocks of one chemical without asking.
- **Stock concentration** is the lowest that reaches the highest target with `MAX_ADDITION_ML`; a run is impossible if that exceeds the solubility, or if any non-zero target then needs less than `MIN_ADDITION_ML`.
- **Concentration 0 means the component is left out** of that vial: no addition, name letter `A`, exempt from the minimum volume.
- **Names** are `MRG-059-<photosensitizer letter><catalyst letter>-<nn>`, with `nn` zero-padded to two digits and counting separately per letter pair from a start number the user sets per pair (`start_numbers` in `plan_run`, default 1). Letters live in `NAME_LETTERS`.
- **Units:** the app takes photosensitizer and catalyst in µM, sacrificial oxidant and buffer in mM, and converts to M (by division, to keep decimal values exact) in `convert_to_molar`. `planner.py` and all output files work in M.
- **Buffer:** system and total concentration are per run, pH per experiment. `split_buffer` applies Henderson–Hasselbalch for an ideal buffer. Acid and base are separate stocks (mixed only in the vial), each subject to the usual pipetting limits across the run.
- **Robot settings are per experiment** (columns of the experiment table), not per run.
- **`experiment.yml` is formatted by hand** to match the robot's existing files (key order `ROBOT_FILE_KEYS`, unit comments, `run: "true"`, closing `MRG-059-stop` entry). Tests parse it with PyYAML.
- **Impossible runs raise `PlanningError`**; the app catches only that and shows it as an error. Everything else propagates.

## Coding principles

When editing or adding code in this repo, follow these rules. [planner.py](planner.py) is the style benchmark.

1. **Reduce nesting.** Break logic into small, self-contained functions instead of deep `if` / `with` / `try` ladders. The function's name should make its job obvious. But avoid excessive fragmentation: a helper must have one clear, nameable job.
2. **NumPy-style docstrings on every function.** Brief `Parameters` / `Returns` blocks. Skip `Examples` unless they materially clarify usage. Don't repeat type hints in prose.
3. **Meaningful comments only.** Explain the *why* — hidden constraints, invariants, surprising decisions. Don't restate what well-named code already shows. Separate logical blocks within a function with blank lines.
4. **Fail-fast.** Avoid broad `try/except` and silent fallbacks. Let exceptions propagate; in Streamlit they surface to the user as a traceback. Validate inputs at the boundary (`plan_run`) and trust internal invariants thereafter. `try/finally` for resource cleanup is fine; `try/except: pass` is not.
5. **Be short.** Prefer concise, self-explanatory code over defensive scaffolding. Three clear lines beat ten lines of speculative robustness.
6. **Full-word names.** No single-letter or abbreviated variable names, even for physical quantities: `stock_concentration`, not `c_s`; `total_volume_ml`, not `V`. Function names are verbs describing the job (`choose_stock_concentration`, `build_vial_names`).
7. **No magic numbers.** Limits, factors and defaults become named module-level constants with a short explanatory comment, grouped into commented sections at the top of the module.
8. **No nested function definitions.** Keep every function at module level; pass extra data through parameters instead of closures.
9. **Avoid `while` loops.** Prefer vectorized NumPy/pandas operations or bounded `for` loops.

## Documentation, tests, changelog

- Non-trivial modules get a companion document in [docs/](docs/) (e.g. [docs/planning.md](docs/planning.md)): explain how the code works in detail, readable also for non-specialists — motivation, steps, parameter guidance, validation. Update it together with the code.
- Tests live in [tests/](tests/). Test the calculation against synthetic data with known, hand-checkable results (never against files that only exist locally). The app gets a headless smoke test via `streamlit.testing.v1.AppTest`.
- Every change gets an entry under `[Unreleased]` in [CHANGELOG.md](CHANGELOG.md) (Keep a Changelog format).
- Include a small `test_function()` demo with `if __name__ == "__main__":` at the bottom of runnable calculation modules, mirroring `planner.py`.
- User-facing text (app, output files) is in English.

## Running

- App: `.venv\Scripts\streamlit run app.py`
- Demo of the calculation: `.venv\Scripts\python planner.py`
- Tests: `.venv\Scripts\python -m pytest`
