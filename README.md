# Robot run planner

Plans a photocatalysis run on the pipetting robot. You enter the concentrations you
want in the reaction mixture. The app works out the stock solutions to prepare and
the volumes to pipette, and writes the robot's `experiment.yml`.

## Setup

Once, in this folder:

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

## Planning a run

```powershell
.venv\Scripts\streamlit run app.py
```

The app opens in the browser.

1. **Choose the chemicals.** Pick the photosensitizer, catalyst and sacrificial oxidant.
   The lists come from `chemicals.CSV`.
2. **Choose the buffer.** Pick the buffer system (from `buffers.CSV`) and its total
   concentration in mM. Both apply to the whole run. Below the selection the app shows
   the pKa, where it comes from, and the pH range in which the calculation is usable.
3. **Set the total volume** per vial (default 8.5 mL) and the **vials per experiment**.
4. **Fill the experiment table.** Use one row per experiment, with the final
   concentrations (photosensitizer and catalyst in µM, sacrificial oxidant in mM), the
   pH and the robot settings for that experiment. The buffer acid and base amounts are
   calculated from the pH. Add rows at the bottom of the table and delete them by
   selecting the row. A concentration of 0 leaves that component out, e.g. a control
   without catalyst.

   | You want | Rows | Vials per experiment |
   |---|---|---|
   | 4 experiments in duplicate | 4 | 2 |
   | 8 different experiments | 8 | 1 |
   | 1 experiment 8 times | 1 | 8 |
   | 4 single experiments | 4 | 1 |

5. **Check the result.** The pipetting volumes, stock solutions and experiment design
   update as you type. If the run is impossible, a red message says why.
6. **Save files** writes everything into a new folder `runs/<date>_<time>/`.

## The files

| File | Content |
|---|---|
| `chemicals.CSV` | chemicals database: category, molar mass, solubility. Edit it when a chemical is added |
| `buffers.CSV` | buffer systems: acid, base, pKa and where it comes from. Edit it when a buffer system is added or a pKa is measured |
| `runs/…/experiments_design.csv` | one row per vial: name, total volume, water volume, target concentrations in M (4 significant digits), total buffer, pH |
| `runs/…/stock_solutions.csv` | per stock: concentration, volume to prepare, mass to weigh in, amount in mmol, instruction |
| `runs/…/experiment.yml` | robot input: one entry per vial plus the closing `MRG-059-stop` entry |

## Sample names

`MRG-059-` + photosensitizer letter + catalyst letter + `-` + two-digit number, e.g. `MRG-059-BC-01`.

| Letter | Photosensitizer (1st) | Catalyst (2nd) |
|---|---|---|
| A | none | none |
| B | Ru(bpy)3Cl2·6H2O | Co-POM |
| C | PDI-SO3 | Ru(bda)(isoq)2 |
| D | Ru(dcepy)2(bpy)(PF6)2 | Ru(dpp)(pic)2(PF6)2 |

The number counts separately for each letter pair. Below the experiment table you set
the start number of each letter pair in the run (default 1). With BC starting at 13 and
BA at 5 you get `BC-13, BC-14, BA-05, BA-06`.

## Rules the planner follows

- Each component comes from **one stock solution** for the whole run.
- Each vial gets **0.2–0.85 mL** of every stock it contains. The vial with the highest
  concentration gets 0.85 mL. Water fills up the rest.
- A stock is made up to the pipetted amount × 1.3, but at least 5 mL and at least
  0.5 mg of solid.
- Buffer acid and base follow from the pH for an ideal buffer (Henderson–Hasselbalch,
  pKa from `buffers.CSV`). Use a pKa measured at your buffer concentration where you
  have one (carbonate: 9.91 at 100 mM). Measuring the pH of a 1 : 1 acid/base mixture
  gives it directly (see [docs/planning.md](docs/planning.md) section 2.3.1). Acid
  and base have separate stocks and are mixed only in the vial.
  Since each is one stock, the pH of one run can span about pKa ± 0.6, e.g. pH 6.6–7.8
  for phosphate.

[docs/planning.md](docs/planning.md) explains every step in detail.

## When the calculation is not possible

| Message | Cause | Fix |
|---|---|---|
| `…differ by a factor of …, but one stock solution covers at most a factor of 4.25` | the highest and lowest concentration of one chemical are too far apart for one stock | narrow the range, or split the run |
| `…Narrow the pH range of the run.` | the same, for buffer acid or base: the pH values of the run are too far apart | narrow the pH range, or split the run |
| `…needs a stock of … M, above its solubility…` | the chemical does not dissolve at the strength needed | lower the concentration to the value given in the message |
| `…exceed the total volume…` | the additions alone are larger than the vial volume | raise the total volume |
| `Some cells of the experiment table are empty.` | a cell was cleared | fill it in, or enter 0 |
| `The LED current must be one of 0, 350, 500, 700, 1000 mA.` | a current the LED driver cannot set | choose one of these values |
| `No name letter is defined for …` | a new photosensitizer or catalyst in `chemicals.CSV` | add its letter to `NAME_LETTERS` in `planner.py` |

## Tests

```powershell
.venv\Scripts\python -m pytest
```

The tests use synthetic data with hand-checkable results and do not depend on any
measured files.
