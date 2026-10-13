# How a robot run is planned

This document explains what [planner.py](../planner.py) calculates and why. It is
written for anyone preparing a run, not only for programmers.

## 1. The problem

A run consists of several vials. Each vial holds the same total volume of reaction
mixture (8.5 mL by default) made from five components plus water:

| Role | Category in `chemicals.CSV` | Example |
|---|---|---|
| photosensitizer | `PS` | Ru(bpy)3Cl2·6H2O |
| catalyst | `cat` | Ru(bda)(isoq)2 |
| sacrificial oxidant | `sac reagent` | Na2S2O8 |
| buffer acid | `acid` | NaH2PO4 |
| buffer base | `base` | Na2HPO4 |

The robot has **one stock-solution position per role**. All vials of a run therefore
use the same five chemicals, each from a single stock solution, and they differ only in
how much of each stock is added. The robot can add between **0.2 and 0.85 mL** of a
stock to a vial. The rest of the volume is water.

You state what you want in the finished mixture. That is the final concentration of
photosensitizer and catalyst (in µM) and of the sacrificial oxidant (in mM) per
experiment, plus the buffer system and its total concentration (in mM) for the run and
the pH of each experiment. The planner works backwards from that to the stock
concentrations, the volumes to pipette and the amount of each stock to prepare.
Internally, and in the output files, everything is in M.

## 2. Steps

### 2.1 Experiments become vials

Every experiment (one row of the table in the app) is repeated as often as
*Vials per experiment* says. With four experiments and two vials each you get eight
vials, in the order experiment 1, experiment 1, experiment 2, experiment 2, …

### 2.2 Names

Each vial gets a name like `MRG-059-BC-01`:

- `MRG-059-` is fixed.
- The first letter stands for the photosensitizer: `B` Ru(bpy)3Cl2·6H2O, `C` PDI-SO3,
  `D` Ru(dcepy)2(bpy)(PF6)2.
- The second letter stands for the catalyst: `B` Co-POM, `C` Ru(bda)(isoq)2,
  `D` Ru(dpp)(pic)2(PF6)2.
- `A` replaces a letter when that component is left out (concentration 0), so a
  control without catalyst is called e.g. `MRG-059-BA-01`.
- The number counts up **separately for each letter pair**. Below the experiment table
  the app shows one start field per letter pair in the run, so every series can continue
  where the last run stopped. With BC starting at 13 and BA at 5 this gives
  `BC-13, BC-14, BA-05, BA-06`. Each field starts at 1, and its value is kept for as
  long as the letter pair stays in the table.
- The number has at least two digits (`NAME_NUMBER_DIGITS`): `01` … `99`, then `100`.

The letters live in `NAME_LETTERS` in `planner.py`. A new photosensitizer or catalyst
must be added there as well as to `chemicals.CSV`. Until then the app reports that no
letter is defined.

### 2.3 Buffer acid and base from the pH

A buffer system is a pair of an acid and its conjugate base, e.g. NaH2PO4 / Na2HPO4,
defined in `buffers.CSV` together with the pKa:

| Buffer | Acid | Base | pKa | Source |
|---|---|---|---|---|
| Phosphate | NaH2PO4 | Na2HPO4 | 7.21 | literature value at 25 °C, not yet measured |
| Carbonate | NaHCO3 | Na2CO3 | 9.91 | measured (AE-413), 100 mM total |

The `comment` column of `buffers.CSV` records where each pKa comes from, and the app
shows it next to the buffer system. Section 2.3.1 explains why a measured value is
preferred.

For an ideal buffer, where activities are taken as concentrations, the
Henderson–Hasselbalch equation links the ratio of base to acid to the pH:

    base / acid = 10^(pH − pKa)        acid + base = total buffer concentration

Solving both together gives

    base = total / (1 + 10^(pKa − pH))        acid = total − base

For example, 10 mM phosphate at pH 7.0 is 6.19 mM NaH2PO4 and 3.81 mM Na2HPO4. At
pH = pKa both are 5 mM, and one pH unit above the pKa there is ten times more base than
acid.

Acid and base have **separate stock solutions** and are only mixed in the vial, so
they may differ from each other by any factor. The pipetting limits of section 2.4
apply to each of them separately, across the vials of the run. Changing the pH from
vial to vial changes the acid and base amounts, and one stock can only cover a factor of
4.25 (see 2.4). For a pH range centred on the pKa this allows about pKa ± 0.6, e.g.
pH 6.6–7.8 for phosphate. A wider range in one run is rejected with the hint to narrow
it. A total buffer concentration of 0 runs without buffer.

#### 2.3.1 Measured instead of literature pKa

Real buffers are not ideal. Charged ions in solution lower the activities, so a pH
meter reads a different pH than the literature pKa predicts. The effect grows with
ionic strength and with the charge of the base: doubly charged CO3²⁻ and HPO4²⁻ are
affected more strongly than singly charged ions.

The calculation is kept ideal and only the pKa is replaced by the **apparent pKa**,
i.e. the pKa measured under the real conditions. Measurement AE-413 shows that this is
enough. 100 mM carbonate was titrated from NaHCO3 : Na2CO3 = 100 : 1 to pure Na2CO3:

| NaHCO3 : Na2CO3 | measured pH | literature pKa 10.33 | apparent pKa 9.91 |
|---|---|---|---|
| 3 : 1 | 9.50 | 9.85 | 9.43 |
| 1 : 1 | 9.91 | 10.33 | 9.91 |
| 1 : 3 | 10.31 | 10.81 | 10.39 |

- With the literature value, the calculated pH is about 0.4 too high.
- Between acid : base ratios of 4 : 1 and 1 : 4, the range one run can cover, the measured
  points lie on the ideal curve with pKa 9.91. The typical deviation is 0.05 pH units
  and the largest 0.14.
- Further out the curve flattens, because pure NaHCO3 or Na2CO3 cannot be buffered
  further. Those ratios lie outside what the pipetting limits allow in one run anyway.

The app therefore gives **pKa ± 1** as the usable pH range below the buffer selection
(`USABLE_PH_DISTANCE_FROM_PKA`), together with the widest pH span possible in one run.
That span is 2 × log10(0.85 / 0.2) ≈ 1.26 units centred on the pKa
(`MAX_PH_SPAN_PER_RUN`), and narrower away from it.

An apparent pKa holds for the conditions it was measured at, above all the total buffer
concentration. Note them in the `comment` column, and measure again when the
conditions change much.

**Measuring the apparent pKa with one point.** At acid : base = 1 : 1, pH = pKa. Mix
the acid and base in equal amounts at the intended total concentration, ideally in
the reaction mixture without photosensitizer and catalyst, and measure the pH. The
phosphate value (7.21) is still the literature value. For 10 mM phosphate the
apparent pKa is expected to be around 6.9–7.0, so the calculated pH is probably
about 0.2–0.3 too high until it is measured.

### 2.4 Stock concentration

The concentration in the vial is

    target concentration = stock concentration × added volume / total volume

so for one stock, the added volume is proportional to the target concentration. The
vial with the **highest** target gets the **largest** addition, 0.85 mL:

    stock concentration = highest target × total volume / 0.85 mL

This is the lowest stock concentration that can work at all. It gives the largest,
most precise additions and uses the least material. The value is rounded to four
significant digits, which is what you would write on the bottle.

Two things can make the run impossible. The app then shows "The calculation is not
possible" and says why:

- **Solubility.** If the stock concentration above is higher than `max_solubility_M`
  in `chemicals.CSV`, the chemical cannot be dissolved at that strength. The message
  states the highest concentration that can be reached:
  solubility × 0.85 mL / total volume.
- **Spread.** The vial with the lowest non-zero target gets the smallest addition. If
  that is below 0.2 mL, one stock cannot serve all vials. Since all volumes scale
  together, this happens exactly when the highest and lowest target of one chemical
  differ by more than a factor of 0.85 / 0.2 = 4.25.

Vials with concentration 0 get no addition of that stock and are exempt from the
0.2 mL minimum. A component that is 0 in every vial gets no stock solution at all.

### 2.5 Volumes

Every addition is rounded to whole µL, the resolution the robot receives. Water fills
each vial up to the total volume. If the additions alone exceed the total volume, which
only happens with a very small total volume, the run is rejected.

Because of the rounding, the concentration actually reached can differ from the
target by up to 0.25 % (half a µL of a 0.2 mL addition). Rounding the stock to four
digits adds at most 0.05 %.

### 2.6 How much stock to prepare

For each stock the planner adds up what the robot takes over the whole run and then
prepares the largest of:

1. the pipetted volume × 1.3, a margin for dead volume and losses,
2. 5 mL, so the bottle can be handled at all,
3. the volume that needs at least 0.5 mg of solid, the smallest mass that can be
   weighed reliably. This matters for the very dilute catalyst stocks.

The volume is rounded up to 0.01 mL, and the mass to weigh in follows from

    mass [mg] = concentration [mol/L] × volume [mL] × molar mass [g/mol]

## 3. Output files

Pressing *Save files* writes three files into a new folder `runs/<date>_<time>/`. An
existing folder is never overwritten.

**`experiments_design.csv`**: one row per vial with its name, the total volume in µL,
the water added in mL, the target concentration of each chemical in M (buffer acid and
base as calculated), the total buffer concentration in M and the pH. The concentrations
are rounded to four significant digits (`DOCUMENTED_SIGNIFICANT_DIGITS`) to keep the file
readable, e.g. 0.006186 M instead of 0.006185841220890307 M. The file only documents the
run; the volumes in `experiment.yml` are calculated from the exact values.

**`stock_solutions.csv`**: one row per stock solution: name, chemical, robot position
(`Role`), concentration, volume to prepare, mass to weigh in, the amount of substance
this mass contains (`Amount_mmol` = concentration × volume, four significant digits) and
a one-line instruction.

**`experiment.yml`**: the robot's input. It has one entry per vial with its name,
`run: "true"`, the pipetting volumes in mL and the robot settings of its experiment
(voltage, LED current, duty cycle, frequency, degassing, measurement and baseline
times). The last entry, `MRG-059-stop` with `run: "false"`, tells the robot to stop.
It repeats the settings of the last vial. The file is written by hand rather than
with a YAML library, to keep the layout and unit comments of the robot's existing files.

## 4. Settings

The fixed numbers are module-level constants at the top of `planner.py`:

| Constant | Value | Meaning |
|---|---|---|
| `MIN_ADDITION_ML`, `MAX_ADDITION_ML` | 0.2, 0.85 | pipetting limits per stock and vial |
| `VOLUME_DECIMALS` | 3 | volumes in mL rounded to µL |
| `STOCK_SIGNIFICANT_DIGITS` | 4 | digits of the stock concentration |
| `STOCK_SAFETY_FACTOR` | 1.3 | extra stock prepared |
| `MIN_STOCK_VOLUME_ML` | 5.0 | smallest stock prepared |
| `MIN_WEIGHED_MASS_MG` | 0.5 | smallest mass weighed in |
| `DOCUMENTED_SIGNIFICANT_DIGITS` | 4 | digits of the concentrations in `experiments_design.csv` and of the stock amount in mmol |
| `DEFAULT_TOTAL_VOLUME_ML` | 8.5 | total volume suggested by the app |
| `DEFAULT_ROBOT_SETTINGS` | see file | robot settings of a new experiment row |
| `LED_CURRENTS_MA` | 0, 350, 500, 700, 1000 | the only LED currents the driver accepts; the table offers them as a dropdown, and the planner rejects any other value, because the device script stops on it |

The buffer systems and their pKa values are in `buffers.CSV`, not in the code. Add a
row there to use a new buffer; its acid and base must exist in `chemicals.CSV`.

## 5. Validation

[tests/test_planner.py](../tests/test_planner.py) checks the calculation on a synthetic
chemicals table with round molar masses, where the expected numbers can be worked out
by hand:

- the volumes reproduce the target concentrations within the µL rounding,
- every addition lies within 0.2–0.85 mL, and the highest target gets exactly 0.85 mL,
- a spread above 4.25 and a stock above the solubility are rejected, and a stock exactly
  at the solubility is accepted,
- the buffer is split equally at pH = pKa and 1 : 10 one unit above,
- the pipetted acid and base reproduce the pH and the total buffer concentration,
  and a too wide pH range is rejected,
- water fills every vial to the total volume,
- the stock volume follows the 1.3 margin, the 5 mL minimum and the 0.5 mg minimum,
  and the amount in mmol matches the mass weighed in,
- `experiments_design.csv` lists the water volume and rounds the concentrations to four
  significant digits, while the plan keeps the exact values,
- names count up per letter pair, with `A` for a missing component,
- `experiment.yml` parses as YAML, has the robot's key order and ends with the stop
  entry.

[tests/test_app.py](../tests/test_app.py) runs the app headless and checks that the
default run is planned, that the µM/mM inputs arrive in M, and that an impossible run
shows the error.
