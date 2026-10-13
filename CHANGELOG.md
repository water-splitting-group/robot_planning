# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Buffer from pH. The run now takes a buffer system and a total buffer concentration,
  and each experiment a pH. Buffer acid and base concentrations follow from
  Henderson–Hasselbalch for an ideal buffer (`split_buffer` in `planner.py`). They keep
  separate stocks, each within the usual pipetting limits; a pH range too wide for one
  stock is rejected with the hint to narrow it.
  - `buffers.CSV` defines the buffer systems: phosphate (NaH2PO4 / Na2HPO4, literature
    pKa 7.21) and carbonate (NaHCO3 / Na2CO3, pKa 9.91 measured in AE-413 at 100 mM).
    A `comment` column records where each pKa comes from, and the app shows it next to
    the buffer system. It is read by `load_buffers`.
  - Section 2.3.1 of `docs/planning.md`: why a measured (apparent) pKa replaces the
    literature value, the comparison with AE-413, and how to measure the pKa with one
    point.
  - `experiments_design.csv` gains the columns `buffer_total_M` and `pH`.
  - Section 2.3 of `docs/planning.md` explains the calculation and the feasible pH range.

- Start number per letter pair. Below the experiment table the app shows one field per
  letter pair in the run (e.g. BC, BA), so every name series can continue from the last
  run. `plan_run` takes them as `start_numbers`, and pairs not given start at 1.
  `build_letter_pairs` is split out of `build_vial_names` for this.
- The experiment table numbers its rows from 1, and added rows continue the count.
- The LED current is limited to the values the driver accepts: 0, 350, 500, 700 and
  1000 mA (`LED_CURRENTS_MA`). The experiment table offers them as a dropdown, and
  `plan_run` rejects any other value, since the device script stops on it.
- The buffer selection shows the usable pH range (pKa ± 1,
  `USABLE_PH_DISTANCE_FROM_PKA`) and the widest pH span of one run (about 1.26 units,
  `MAX_PH_SPAN_PER_RUN`).

- `stock_solutions.csv` gains the column `Amount_mmol`: the amount of substance weighed in
  for each stock (concentration × volume).
- `experiments_design.csv` gains the column `water_volume_mL`: the water added to each
  vial.

### Changed

- The concentrations in `experiments_design.csv` are rounded to four significant digits
  (`DOCUMENTED_SIGNIFICANT_DIGITS`) to keep the file readable. The calculation and
  `experiment.yml` still use the exact values. `round_to_significant_digits` in
  `planner.py` does the rounding, also for the stock concentration.
- Running numbers in sample names have at least two digits: `MRG-059-BC-01` instead
  of `MRG-059-BC-1` (`NAME_NUMBER_DIGITS`).

- New default robot settings for experiment rows: voltage 0, LED current 350 mA, duty
  cycle 100 %, frequency 1 Hz, degassing 20 min, measurement 10 min, baseline 15 min
  before and 5 min after the reaction.

- The app takes photosensitizer and catalyst concentrations in µM, and the sacrificial
  oxidant and the buffer in mM, instead of M. The output files stay in M.
- `plan_run` takes `buffer_system` and `buffer_concentration`; `chemical_by_role` now
  covers only photosensitizer, catalyst and sacrificial oxidant, and the experiment
  table has a `pH` column instead of `buffer_acid_M` and `buffer_base_M`.

### Removed

- The old `stock_solution_calculator_new.py` and its example files `experiment.yml`,
  `experiments_design.csv` and `stock_solutions.csv` in the project root; the app writes
  these files into `runs/` instead.
