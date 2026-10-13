"""Streamlit app for planning a robot run. Start it with `streamlit run app.py`."""

from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from planner import (
    DEFAULT_ROBOT_SETTINGS,
    DEFAULT_TOTAL_VOLUME_ML,
    ENTERED_ROLES,
    LED_CURRENTS_MA,
    MAX_PH_SPAN_PER_RUN,
    NAME_PREFIX,
    ROLE_CATEGORIES,
    USABLE_PH_DISTANCE_FROM_PKA,
    PlanningError,
    build_experiment_design,
    build_letter_pairs,
    load_buffers,
    load_chemicals,
    plan_run,
    write_run_files,
)


CHEMICALS_FILE = Path(__file__).parent / "chemicals.CSV"
BUFFERS_FILE = Path(__file__).parent / "buffers.CSV"
OUTPUT_DIRECTORY = Path(__file__).parent / "runs"

# --- Input units ------------------------------------------------------------------
# The table takes each concentration in the unit it is usually thought of in; the
# planner works in M. Converting by division keeps e.g. 50 µM at exactly 5e-05 M.
MICROMOLAR_PER_MOLAR = 1e6
MILLIMOLAR_PER_MOLAR = 1e3
INPUT_UNITS = {
    "photosensitizer": ("µM", MICROMOLAR_PER_MOLAR),
    "catalyst": ("µM", MICROMOLAR_PER_MOLAR),
    "sacrificial_oxidant": ("mM", MILLIMOLAR_PER_MOLAR),
}

# --- Starting point of a new run --------------------------------------------------
DEFAULT_EXPERIMENT_COUNT = 4
DEFAULT_REPLICATES = 2
DEFAULT_CHEMICALS = {
    "photosensitizer": "Ru(bpy)3Cl2·6H2O",
    "catalyst": "Ru(bda)(isoq)2",
    "sacrificial_oxidant": "Na2S2O8",
}
# In the units of INPUT_UNITS.
DEFAULT_CONCENTRATIONS = {
    "photosensitizer": 50.0,
    "catalyst": 9.0,
    "sacrificial_oxidant": 10.0,
}
DEFAULT_BUFFER = "Phosphate"
DEFAULT_BUFFER_CONCENTRATION_MM = 10.0
DEFAULT_PH = 7.0


def select_chemicals(chemicals):
    """Let the user pick one chemical per directly entered role.

    Parameters
    ----------
    chemicals : pd.DataFrame
        Chemicals database, indexed by name.

    Returns
    -------
    dict
        Chemical name for every role in ENTERED_ROLES.
    """
    chemical_by_role = {}
    for column, role in zip(st.columns(len(ENTERED_ROLES)), ENTERED_ROLES):
        options = chemicals.index[chemicals["category"] == ROLE_CATEGORIES[role]].tolist()
        chemical_by_role[role] = column.selectbox(
            role.replace("_", " "), options, index=options.index(DEFAULT_CHEMICALS[role])
        )
    return chemical_by_role


def select_buffer(buffers):
    """Let the user pick the buffer system and its total concentration.

    Parameters
    ----------
    buffers : pd.DataFrame
        Buffer systems, indexed by name.

    Returns
    -------
    tuple
        The chosen buffer system (one row of `buffers`) and its total concentration in M.
    """
    system_column, concentration_column = st.columns(2)
    name = system_column.selectbox("Buffer system", buffers.index, index=buffers.index.get_loc(DEFAULT_BUFFER))
    buffer_system = buffers.loc[name]
    lowest_ph = buffer_system["pKa"] - USABLE_PH_DISTANCE_FROM_PKA
    highest_ph = buffer_system["pKa"] + USABLE_PH_DISTANCE_FROM_PKA
    system_column.caption(
        f"{buffer_system['acid']} / {buffer_system['base']}, pKa {buffer_system['pKa']} ({buffer_system['comment']})  \n"
        f"Usable pH range: {lowest_ph:.2f}–{highest_ph:.2f}. Within one run the pH can span at most about "
        f"{MAX_PH_SPAN_PER_RUN:.1f} units, centred on the pKa."
    )
    concentration_mm = concentration_column.number_input(
        "Total buffer concentration [mM]", min_value=0.0, value=DEFAULT_BUFFER_CONCENTRATION_MM
    )
    return buffer_system, concentration_mm / MILLIMOLAR_PER_MOLAR


def build_default_experiments():
    """Experiment table the app starts with.

    Returns
    -------
    pd.DataFrame
        DEFAULT_EXPERIMENT_COUNT identical rows of default concentrations, pH and robot settings.
    """
    row = {**DEFAULT_CONCENTRATIONS, "pH": DEFAULT_PH, **DEFAULT_ROBOT_SETTINGS}
    # Index from 1 numbers the experiments in the table; added rows continue the count.
    return pd.DataFrame([row] * DEFAULT_EXPERIMENT_COUNT, index=pd.RangeIndex(1, DEFAULT_EXPERIMENT_COUNT + 1))


def build_column_config():
    """Labels, units and new-row defaults of the experiment table.

    The labels name the role, not the chosen chemical: changing a label resets the edits of
    a table with addable rows.

    Returns
    -------
    dict
    """
    concentration_columns = {
        role: st.column_config.NumberColumn(
            f"{role.replace('_', ' ')} [{unit}]", min_value=0.0, default=DEFAULT_CONCENTRATIONS[role]
        )
        for role, (unit, _) in INPUT_UNITS.items()
    }
    ph_column = {"pH": st.column_config.NumberColumn("pH", default=DEFAULT_PH)}
    setting_columns = {key: st.column_config.NumberColumn(key, default=value) for key, value in DEFAULT_ROBOT_SETTINGS.items()}
    setting_columns["LED_driver_current_mA"] = st.column_config.SelectboxColumn(
        "LED_driver_current_mA",
        options=LED_CURRENTS_MA,
        required=True,
        default=DEFAULT_ROBOT_SETTINGS["LED_driver_current_mA"],
    )
    number_column = {"_index": st.column_config.NumberColumn("#")}
    return number_column | concentration_columns | ph_column | setting_columns


def convert_to_molar(experiments):
    """Replace the concentration columns in input units by `<role>_M` columns in M.

    Parameters
    ----------
    experiments : pd.DataFrame
        The experiment table as edited in the app.

    Returns
    -------
    pd.DataFrame
        The table in the form `plan_run` expects.
    """
    molar = experiments.drop(columns=list(INPUT_UNITS))
    for role, (_, units_per_molar) in INPUT_UNITS.items():
        molar[f"{role}_M"] = experiments[role] / units_per_molar
    return molar


def select_start_numbers(experiments, chemical_by_role):
    """Let the user set the first running number of every letter pair in the run.

    The inputs are keyed by letter pair, so a value survives as long as its pair stays in
    the table.

    Parameters
    ----------
    experiments : pd.DataFrame
        The experiment table in M.
    chemical_by_role : dict
        Chemical name for every role in ENTERED_ROLES.

    Returns
    -------
    dict
        First number of each letter pair, e.g. {"BC": 13}.
    """
    letter_pairs = build_letter_pairs(experiments, chemical_by_role).unique()
    if len(letter_pairs) == 0:
        return {}

    st.subheader("Numbering")
    st.caption("First number of each name series in this run.")
    return {
        pair: column.number_input(f"Start {NAME_PREFIX}{pair}-", min_value=1, value=1, key=f"start_number_{pair}")
        for column, pair in zip(st.columns(len(letter_pairs)), letter_pairs)
    }


def show_plan(plan):
    """Display the pipetting volumes and the stock solutions.

    Parameters
    ----------
    plan : RunPlan
    """
    volume_columns = ["name", "pH"] + [f"volume_{role}" for role in ROLE_CATEGORIES] + ["volume_water"]
    st.subheader("Pipetting volumes [mL]")
    st.dataframe(plan.vials[volume_columns], hide_index=True)

    st.subheader("Stock solutions")
    st.dataframe(plan.stocks, hide_index=True)

    st.subheader("Experiment design")
    st.dataframe(build_experiment_design(plan), hide_index=True)


def save_plan(plan):
    """Write the run files into a new, timestamped folder and report where.

    Parameters
    ----------
    plan : RunPlan
    """
    directory = OUTPUT_DIRECTORY / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    write_run_files(plan, directory)
    st.success(f"Saved experiments_design.csv, stock_solutions.csv and experiment.yml to {directory}")


def main():
    """Lay out the page and plan the run on every change."""
    st.set_page_config(page_title="Robot run planner", layout="wide")
    st.title("Robot run planner")

    chemicals = load_chemicals(CHEMICALS_FILE)
    chemical_by_role = select_chemicals(chemicals)
    buffer_system, buffer_concentration = select_buffer(load_buffers(BUFFERS_FILE))

    volume_column, replicates_column = st.columns(2)
    total_volume_ml = volume_column.number_input("Total volume per vial [mL]", min_value=0.1, value=DEFAULT_TOTAL_VOLUME_ML)
    replicates = replicates_column.number_input("Vials per experiment", min_value=1, value=DEFAULT_REPLICATES)

    st.subheader("Experiments")
    st.caption(
        "One row per experiment. Concentrations are those in the final reaction mixture; 0 leaves a component out. "
        "Buffer acid and base follow from the pH."
    )
    experiments = convert_to_molar(
        st.data_editor(
            build_default_experiments(),
            column_config=build_column_config(),
            num_rows="dynamic",
            key="experiments",
        )
    )

    try:
        start_numbers = select_start_numbers(experiments, chemical_by_role)
        plan = plan_run(
            experiments,
            replicates,
            chemical_by_role,
            chemicals,
            total_volume_ml,
            buffer_system,
            buffer_concentration,
            start_numbers,
        )
    except PlanningError as error:
        st.error(f"The calculation is not possible. {error}")
        return

    show_plan(plan)
    if st.button("Save files", type="primary"):
        save_plan(plan)


if __name__ == "__main__":
    main()
