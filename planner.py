"""Plan a photocatalysis run on the robot: stock solutions, pipetting volumes and robot file.

The user states the concentration of photosensitizer, catalyst and sacrificial oxidant
and the pH of each experiment; buffer acid and base follow from the pH of an ideal
buffer. One stock solution per component is chosen so that every vial receives between
MIN_ADDITION_ML and MAX_ADDITION_ML of it; water fills up the rest. See docs/planning.md
for the reasoning behind each step.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


# --- Components -------------------------------------------------------------------
# Each role is one stock-solution position on the robot, filled with one chemical of the
# matching category in chemicals.CSV.
ROLE_CATEGORIES = {
    "photosensitizer": "PS",
    "catalyst": "cat",
    "sacrificial_oxidant": "sac reagent",
    "buffer_acid": "acid",
    "buffer_base": "base",
}
# Roles whose concentration is entered directly; buffer acid and base follow from the pH.
ENTERED_ROLES = ("photosensitizer", "catalyst", "sacrificial_oxidant")
# Henderson–Hasselbalch with the apparent pKa holds within about pKa ± 1, i.e. acid : base.
# Further out the buffer capacity vanishes and the measured pH flattens away from the calculation.
USABLE_PH_DISTANCE_FROM_PKA = 1.0

# --- Sample names -----------------------------------------------------------------
# A vial is named NAME_PREFIX + photosensitizer letter + catalyst letter + "-" + number,
# e.g. MRG-059-BC-01.
NAME_PREFIX = "MRG-059-"
NAME_LETTERS = {
    "photosensitizer": {"Ru(bpy)3Cl2·6H2O": "B", "PDI-SO3": "C", "Ru(dcepy)2(bpy)(PF6)2": "D"},
    "catalyst": {"Co-POM": "B", "Ru(bda)(isoq)2": "C", "Ru(dpp)(pic)2(PF6)2": "D"},
}
# Letter of a vial without photosensitizer or without catalyst (control experiment).
NO_COMPONENT_LETTER = "A"
# Running numbers are zero-padded to this many digits (MRG-059-BC-01); 100 stays 100.
NAME_NUMBER_DIGITS = 2

# --- Pipetting limits -------------------------------------------------------------
MIN_ADDITION_ML = 0.2
MAX_ADDITION_ML = 0.85
# Widest pH range of one run: centred on the pKa, acid and base each change by
# 10^(span / 2), and one stock covers at most MAX / MIN. Away from the pKa it is narrower.
MAX_PH_SPAN_PER_RUN = 2 * np.log10(MAX_ADDITION_ML / MIN_ADDITION_ML)
# The robot receives volumes in µL steps.
VOLUME_DECIMALS = 3
# Stock concentrations are rounded to what goes on the bottle label. Four digits keep the
# rounding error (at most 0.05 %) below half a µL of the largest addition, so rounding the
# stock never pushes a volume outside the pipetting limits.
STOCK_SIGNIFICANT_DIGITS = 4

# --- Stock preparation ------------------------------------------------------------
# Extra stock for the robot's dead volume and pipetting losses.
STOCK_SAFETY_FACTOR = 1.3
MIN_STOCK_VOLUME_ML = 5.0
# Smallest mass that can be weighed in reliably.
MIN_WEIGHED_MASS_MG = 0.5
PREPARATION_VOLUME_DECIMALS = 3
MASS_DECIMALS = 3

# --- Output files -----------------------------------------------------------------
# The concentrations in experiments_design.csv and the amount of each stock only document
# the run, so they are rounded to this many digits to stay readable; the calculation and
# the robot file keep full precision.
DOCUMENTED_SIGNIFICANT_DIGITS = 4

# --- Robot file -------------------------------------------------------------------
DEFAULT_TOTAL_VOLUME_ML = 8.5
# The LED driver only offers these currents; any other value stops the device script.
LED_CURRENTS_MA = (0, 350, 500, 700, 1000)
DEFAULT_ROBOT_SETTINGS = {
    "voltage": 0,
    "LED_driver_current_mA": 350,
    "Duty_Cycle": 100,
    "Frequency": 1,
    "degassing_time": 20,
    "measurement_time": 10,
    "pre_reaction_baseline_time": 15,
    "post_reaction_baseline_time": 5,
}
# Key order of one vial entry in experiment.yml, as the robot software expects it.
ROBOT_FILE_KEYS = (
    "name",
    "run",
    "voltage",
    "volume_water",
    "LED_driver_current_mA",
    "Duty_Cycle",
    "Frequency",
    "volume_sacrificial_oxidant",
    "volume_photosensitizer",
    "volume_catalyst",
    "volume_buffer_base",
    "volume_buffer_acid",
    "degassing_time",
    "measurement_time",
    "pre_reaction_baseline_time",
    "post_reaction_baseline_time",
)
ROBOT_FILE_UNITS = {
    "Duty_Cycle": "%",
    "Frequency": "Hz",
    "degassing_time": "min",
    "measurement_time": "min",
    "pre_reaction_baseline_time": "min",
    "post_reaction_baseline_time": "min",
}
# The robot stops at an entry with run "false"; it closes every experiment.yml.
STOP_ENTRY_NAME = NAME_PREFIX + "stop"


class PlanningError(ValueError):
    """Raised when a run cannot be prepared within the robot's pipetting limits."""


@dataclass
class RunPlan:
    """Everything needed to prepare and start one robot run.

    Attributes
    ----------
    vials : pd.DataFrame
        One row per vial: name, target concentrations (`<role>_M`), addition volumes in mL
        (`volume_<role>`, `volume_water`) and robot settings.
    stocks : pd.DataFrame
        One row per stock solution with its concentration and preparation instructions.
    chemical_by_role : dict
        The chemical used for each role.
    total_volume_ml : float
        Volume of the reaction mixture in every vial.
    """

    vials: pd.DataFrame
    stocks: pd.DataFrame
    chemical_by_role: dict
    total_volume_ml: float


def load_chemicals(path):
    """Read the chemicals database.

    Parameters
    ----------
    path : str or Path
        Semicolon-separated CSV with the columns `Name`, `category`, `M (g/mol)` and
        `max_solubility_M`.

    Returns
    -------
    pd.DataFrame
        The chemicals, indexed by name.
    """
    # Round-trip parsing reads "120e-6" as exactly 1.2e-4, so a stock at the solubility
    # limit is not rejected by a last-digit difference.
    return pd.read_csv(path, sep=";", index_col="Name", float_precision="round_trip")


def load_buffers(path):
    """Read the buffer systems.

    Parameters
    ----------
    path : str or Path
        Semicolon-separated CSV with the columns `Name`, `acid`, `base`, `pKa` and `comment`
        (where the pKa comes from); acid and base are chemical names from the chemicals
        database.

    Returns
    -------
    pd.DataFrame
        The buffer systems, indexed by name.
    """
    return pd.read_csv(path, sep=";", index_col="Name")


def plan_run(
    experiments, replicates, chemical_by_role, chemicals, total_volume_ml, buffer_system, buffer_concentration, start_numbers=None
):
    """Choose the stock solutions and pipetting volumes for one run.

    Parameters
    ----------
    experiments : pd.DataFrame
        One row per experiment with a target concentration column `<role>_M` (in M) for
        every role in ENTERED_ROLES, a `pH` column and one column per robot setting.
    replicates : int
        Number of vials per experiment.
    chemical_by_role : dict
        Chemical name for every role in ENTERED_ROLES.
    chemicals : pd.DataFrame
        Chemicals database from `load_chemicals`.
    total_volume_ml : float
        Volume of the reaction mixture in every vial.
    buffer_system : pd.Series
        One row of the buffer table from `load_buffers`: `acid`, `base` and `pKa`.
    buffer_concentration : float
        Total buffer concentration (acid + base) in every vial, in M.
    start_numbers : dict, optional
        First running number of each letter pair, e.g. {"BC": 13, "BA": 5}; pairs not
        listed start at 1.

    Returns
    -------
    RunPlan

    Raises
    ------
    PlanningError
        If the input is incomplete or a component cannot be pipetted within the limits.
    """
    validate_experiments(experiments, buffer_concentration)
    chemical_by_role = {**chemical_by_role, "buffer_acid": buffer_system["acid"], "buffer_base": buffer_system["base"]}
    vials = experiments.loc[experiments.index.repeat(replicates)].reset_index(drop=True)
    vials.insert(0, "name", build_vial_names(vials, chemical_by_role, start_numbers or {}))
    vials["total_volume_ml"] = total_volume_ml
    vials["buffer_total_M"] = buffer_concentration
    vials["buffer_acid_M"], vials["buffer_base_M"] = split_buffer(vials["pH"], buffer_system["pKa"], buffer_concentration)

    stock_rows = []
    for role, chemical in chemical_by_role.items():
        target_concentrations = vials[f"{role}_M"].to_numpy(dtype=float)
        vials[f"volume_{role}"] = 0.0
        if not target_concentrations.any():
            continue

        stock_concentration = choose_stock_concentration(
            chemical, target_concentrations, total_volume_ml, chemicals.loc[chemical, "max_solubility_M"]
        )
        volumes = compute_addition_volumes(target_concentrations, total_volume_ml, stock_concentration)
        check_addition_volumes(role, chemical, target_concentrations, volumes)
        vials[f"volume_{role}"] = volumes
        stock_rows.append(
            describe_stock(role, chemical, stock_concentration, volumes.sum(), chemicals.loc[chemical, "M (g/mol)"])
        )

    vials["volume_water"] = compute_water_volumes(vials, total_volume_ml)
    return RunPlan(vials, pd.DataFrame(stock_rows), dict(chemical_by_role), total_volume_ml)


def validate_experiments(experiments, buffer_concentration):
    """Reject an empty table, empty cells and negative concentrations.

    Parameters
    ----------
    experiments : pd.DataFrame
        The experiment table passed to `plan_run`.
    buffer_concentration : float
        Total buffer concentration in M.

    Raises
    ------
    PlanningError
        If the table cannot be planned.
    """
    if experiments.empty:
        raise PlanningError("Add at least one experiment.")
    if experiments.isna().any().any():
        raise PlanningError("Some cells of the experiment table are empty.")

    concentration_columns = [f"{role}_M" for role in ENTERED_ROLES]
    if (experiments[concentration_columns] < 0).any().any() or buffer_concentration < 0:
        raise PlanningError("Concentrations must not be negative.")

    if not experiments["LED_driver_current_mA"].isin(LED_CURRENTS_MA).all():
        allowed = ", ".join(str(current) for current in LED_CURRENTS_MA)
        raise PlanningError(f"The LED current must be one of {allowed} mA.")


def split_buffer(ph_values, pka, buffer_concentration):
    """Acid and base concentrations of an ideal buffer at the given pH.

    Henderson–Hasselbalch: base / acid = 10^(pH − pKa), with acid + base = total.

    Parameters
    ----------
    ph_values : pd.Series
        pH of every vial.
    pka : float
        pKa of the buffer's acid.
    buffer_concentration : float
        Total buffer concentration in M.

    Returns
    -------
    tuple of pd.Series
        Acid and base concentration in M.
    """
    base_fraction = 1 / (1 + 10 ** (pka - ph_values))
    return buffer_concentration * (1 - base_fraction), buffer_concentration * base_fraction


def build_vial_names(vials, chemical_by_role, start_numbers):
    """Name every vial, counting up separately for each letter pair.

    Parameters
    ----------
    vials : pd.DataFrame
        One row per vial with the target concentration columns.
    chemical_by_role : dict
        Chemical name for every role.
    start_numbers : dict
        First number of each letter pair, e.g. {"BC": 13}; pairs not listed start at 1.

    Returns
    -------
    pd.Series
        Names such as MRG-059-BC-01.
    """
    letter_pairs = build_letter_pairs(vials, chemical_by_role)
    first_numbers = letter_pairs.map(start_numbers).fillna(1).astype(int)
    numbers = first_numbers + letter_pairs.groupby(letter_pairs).cumcount()
    return NAME_PREFIX + letter_pairs + "-" + numbers.astype(str).str.zfill(NAME_NUMBER_DIGITS)


def build_letter_pairs(experiments, chemical_by_role):
    """Photosensitizer and catalyst letter of every row, e.g. "BC", or "BA" without catalyst.

    Parameters
    ----------
    experiments : pd.DataFrame
        One row per experiment or vial with the target concentration columns.
    chemical_by_role : dict
        Chemical name for at least the photosensitizer and catalyst roles.

    Returns
    -------
    pd.Series
        One letter pair per row.
    """
    return name_letters(experiments, chemical_by_role, "photosensitizer") + name_letters(
        experiments, chemical_by_role, "catalyst"
    )


def name_letters(vials, chemical_by_role, role):
    """Name letter of one role for every vial: the chemical's letter, or the 'none' letter.

    Parameters
    ----------
    vials : pd.DataFrame
        One row per vial with the target concentration columns.
    chemical_by_role : dict
        Chemical name for every role.
    role : str
        "photosensitizer" or "catalyst".

    Returns
    -------
    pd.Series
        One letter per vial.
    """
    chemical = chemical_by_role[role]
    if chemical not in NAME_LETTERS[role]:
        raise PlanningError(f"No name letter is defined for {chemical}; add it to NAME_LETTERS in planner.py.")

    letters = np.where(vials[f"{role}_M"] > 0, NAME_LETTERS[role][chemical], NO_COMPONENT_LETTER)
    return pd.Series(letters, index=vials.index)


def choose_stock_concentration(chemical, target_concentrations, total_volume_ml, max_solubility):
    """Lowest stock concentration that reaches the highest target with the largest addition.

    The lowest possible concentration gives the largest, most precise additions and uses the
    least material.

    Parameters
    ----------
    chemical : str
        Name used in error messages.
    target_concentrations : np.ndarray
        Target concentration in every vial, in M.
    total_volume_ml : float
        Volume of the reaction mixture.
    max_solubility : float
        Highest concentration of the chemical that dissolves, in M.

    Returns
    -------
    float
        Stock concentration in M, rounded to STOCK_SIGNIFICANT_DIGITS.

    Raises
    ------
    PlanningError
        If that concentration exceeds the solubility.
    """
    highest_target = target_concentrations.max()
    lowest_concentration = highest_target * total_volume_ml / MAX_ADDITION_ML
    stock_concentration = round_to_significant_digits(lowest_concentration, STOCK_SIGNIFICANT_DIGITS)

    if stock_concentration > max_solubility:
        reachable_target = max_solubility * MAX_ADDITION_ML / total_volume_ml
        raise PlanningError(
            f"{chemical}: {highest_target:.3g} M needs a stock of {stock_concentration:.4g} M, above its "
            f"solubility of {max_solubility:.3g} M. The highest reachable concentration is {reachable_target:.3g} M."
        )
    return stock_concentration


def round_to_significant_digits(value, digits):
    """Round a number to a given count of significant digits, e.g. 0.0061858 to 0.006186.

    Parameters
    ----------
    value : float
    digits : int

    Returns
    -------
    float
    """
    return float(f"{value:.{digits}g}")


def compute_addition_volumes(target_concentrations, total_volume_ml, stock_concentration):
    """Volume of stock solution to add to each vial.

    Parameters
    ----------
    target_concentrations : np.ndarray
        Target concentration in every vial, in M.
    total_volume_ml : float
        Volume of the reaction mixture.
    stock_concentration : float
        Concentration of the stock solution, in M.

    Returns
    -------
    np.ndarray
        Volumes in mL, rounded to µL.
    """
    return np.round(target_concentrations * total_volume_ml / stock_concentration, VOLUME_DECIMALS)


def check_addition_volumes(role, chemical, target_concentrations, volumes):
    """Ensure no vial needs less than the smallest addition.

    The largest addition never exceeds MAX_ADDITION_ML, because the stock concentration is
    chosen from the highest target. Vials without the chemical are skipped.

    Parameters
    ----------
    role : str
        Role of the chemical; buffer roles get a hint about the pH range.
    chemical : str
        Name used in error messages.
    target_concentrations : np.ndarray
        Target concentration in every vial, in M.
    volumes : np.ndarray
        Addition volumes in mL.

    Raises
    ------
    PlanningError
        If the targets are spread too far apart for one stock solution.
    """
    present = target_concentrations > 0
    smallest_addition = volumes[present].min()
    if smallest_addition >= MIN_ADDITION_ML:
        return

    spread = target_concentrations[present].max() / target_concentrations[present].min()
    hint = "" if role in ENTERED_ROLES else " Narrow the pH range of the run."
    raise PlanningError(
        f"{chemical}: the concentrations differ by a factor of {spread:.2f}, but one stock solution covers at "
        f"most a factor of {MAX_ADDITION_ML / MIN_ADDITION_ML:.2f} ({MIN_ADDITION_ML}–{MAX_ADDITION_ML} mL per "
        f"vial). The smallest addition would be {smallest_addition} mL.{hint}"
    )


def describe_stock(role, chemical, stock_concentration, pipetted_volume_ml, molar_mass):
    """How much of a stock solution to prepare, and how.

    Parameters
    ----------
    role : str
        Robot position the stock is placed in.
    chemical : str
        Dissolved chemical.
    stock_concentration : float
        Concentration in M.
    pipetted_volume_ml : float
        Volume the robot takes from the stock over the whole run.
    molar_mass : float
        Molar mass in g/mol.

    Returns
    -------
    dict
        One row of the stock solution table.
    """
    volume_for_minimum_mass = MIN_WEIGHED_MASS_MG / (stock_concentration * molar_mass)
    volume_ml = max(pipetted_volume_ml * STOCK_SAFETY_FACTOR, MIN_STOCK_VOLUME_ML, volume_for_minimum_mass)
    # Round up, so the weighed mass never drops below MIN_WEIGHED_MASS_MG.
    volume_ml = np.ceil(volume_ml * 10**PREPARATION_VOLUME_DECIMALS) / 10**PREPARATION_VOLUME_DECIMALS

    # mol/L × mL = mmol, and mmol × g/mol = mg.
    amount_mmol = stock_concentration * volume_ml
    mass_mg = round(amount_mmol * molar_mass, MASS_DECIMALS)
    return {
        "Stock solution": f"{chemical}_Stock",
        "Chemical": chemical,
        "Role": role,
        "Concentration_M": stock_concentration,
        "Volume_mL": volume_ml,
        "Mass_mg": mass_mg,
        "Amount_mmol": round_to_significant_digits(amount_mmol, DOCUMENTED_SIGNIFICANT_DIGITS),
        "Instruction": f"Dissolve {mass_mg} mg in water and fill up to {volume_ml} mL",
    }


def compute_water_volumes(vials, total_volume_ml):
    """Water that fills each vial up to the total volume.

    Parameters
    ----------
    vials : pd.DataFrame
        One row per vial with the `volume_<role>` columns and `name`.
    total_volume_ml : float
        Volume of the reaction mixture.

    Returns
    -------
    pd.Series
        Water volume in mL.

    Raises
    ------
    PlanningError
        If the stock additions alone exceed the total volume.
    """
    volume_columns = [f"volume_{role}" for role in ROLE_CATEGORIES]
    water_volumes = (total_volume_ml - vials[volume_columns].sum(axis=1)).round(VOLUME_DECIMALS)

    overfilled = vials.loc[water_volumes < 0, "name"]
    if not overfilled.empty:
        raise PlanningError(f"The additions to {', '.join(overfilled)} exceed the total volume of {total_volume_ml} mL.")
    return water_volumes


def build_experiment_design(plan):
    """Table of vial names, water volumes and target concentrations, as written to experiments_design.csv.

    Concentrations are rounded to DOCUMENTED_SIGNIFICANT_DIGITS; `plan` keeps the exact values.

    Parameters
    ----------
    plan : RunPlan

    Returns
    -------
    pd.DataFrame
    """
    design = pd.DataFrame(
        {
            "Experiment": plan.vials["name"],
            "total_volume_µL": plan.total_volume_ml * 1000,
            "water_volume_mL": plan.vials["volume_water"],
        }
    )
    for role, chemical in plan.chemical_by_role.items():
        design[f"{chemical}_M"] = plan.vials[f"{role}_M"]
    design["buffer_total_M"] = plan.vials["buffer_total_M"]

    concentration_columns = [f"{chemical}_M" for chemical in plan.chemical_by_role.values()] + ["buffer_total_M"]
    design[concentration_columns] = design[concentration_columns].map(
        round_to_significant_digits, digits=DOCUMENTED_SIGNIFICANT_DIGITS
    )
    design["pH"] = plan.vials["pH"]
    return design


def format_robot_file(plan):
    """Text of experiment.yml: one entry per vial, closed by the stop entry.

    Written by hand rather than with a YAML library to keep the layout and unit comments
    the robot's existing files use.

    Parameters
    ----------
    plan : RunPlan

    Returns
    -------
    str
    """
    entries = plan.vials.assign(run="true").to_dict("records")
    stop_entry = {**entries[-1], "name": STOP_ENTRY_NAME, "run": "false"}
    return "".join(format_robot_entry(entry) for entry in entries + [stop_entry])


def format_robot_entry(entry):
    """One list entry of experiment.yml.

    Parameters
    ----------
    entry : dict
        Values for every key in ROBOT_FILE_KEYS.

    Returns
    -------
    str
    """
    lines = ["-"]
    for key in ROBOT_FILE_KEYS:
        value = entry[key]
        if key == "run":
            text = f'"{value}"'
        elif isinstance(value, str):
            text = value
        else:
            text = f"{value:g}"
        unit = f" # {ROBOT_FILE_UNITS[key]}" if key in ROBOT_FILE_UNITS else ""
        lines.append(f"  {key}: {text}{unit}")
    return "\n".join(lines) + "\n"


def write_run_files(plan, directory):
    """Write experiments_design.csv, stock_solutions.csv and experiment.yml.

    Parameters
    ----------
    plan : RunPlan
    directory : Path
        New folder for the run; it must not exist yet, so no earlier run is overwritten.
    """
    directory = Path(directory)
    directory.mkdir(parents=True)
    build_experiment_design(plan).to_csv(directory / "experiments_design.csv", sep=";", index=False)
    plan.stocks.to_csv(directory / "stock_solutions.csv", sep=";", index=False)
    (directory / "experiment.yml").write_text(format_robot_file(plan), encoding="utf-8")


def test_function():
    """Plan four Ru(bpy)3 / Ru(bda) experiments in 10 mM phosphate in duplicate and print the results."""
    project_directory = Path(__file__).parent
    chemicals = load_chemicals(project_directory / "chemicals.CSV")
    buffer_system = load_buffers(project_directory / "buffers.CSV").loc["Phosphate"]
    chemical_by_role = {
        "photosensitizer": "Ru(bpy)3Cl2·6H2O",
        "catalyst": "Ru(bda)(isoq)2",
        "sacrificial_oxidant": "Na2S2O8",
    }
    experiments = pd.DataFrame(
        {
            "photosensitizer_M": [5e-5, 5e-5, 1.5e-4, 5e-5],
            "catalyst_M": [9e-6, 6e-6, 9e-6, 0.0],
            "sacrificial_oxidant_M": 0.01,
            "pH": [7.0, 7.0, 7.0, 7.5],
            **DEFAULT_ROBOT_SETTINGS,
        }
    )
    plan = plan_run(experiments, 2, chemical_by_role, chemicals, DEFAULT_TOTAL_VOLUME_ML, buffer_system, 0.01)

    volume_columns = ["name", "pH"] + [f"volume_{role}" for role in ROLE_CATEGORIES] + ["volume_water"]
    print(plan.vials[volume_columns].to_string(index=False), end="\n\n")
    print(plan.stocks.drop(columns="Instruction").to_string(index=False), end="\n\n")
    print(format_robot_file(plan))


if __name__ == "__main__":
    test_function()
