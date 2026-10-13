import numpy as np
import pandas as pd
import pytest
import yaml

from planner import (
    DEFAULT_ROBOT_SETTINGS,
    MAX_ADDITION_ML,
    MIN_ADDITION_ML,
    MIN_STOCK_VOLUME_ML,
    MIN_WEIGHED_MASS_MG,
    ROBOT_FILE_KEYS,
    STOCK_SAFETY_FACTOR,
    STOP_ENTRY_NAME,
    VOLUME_DECIMALS,
    PlanningError,
    build_experiment_design,
    format_robot_file,
    load_buffers,
    load_chemicals,
    plan_run,
    split_buffer,
    write_run_files,
)


TOTAL_VOLUME_ML = 8.5
BUFFER_CONCENTRATION = 0.01
# A round pKa makes the buffer split easy to check by hand: equal parts at pH 7.
BUFFER_SYSTEM = pd.Series({"acid": "NaH2PO4", "base": "Na2HPO4", "pKa": 7.0})
# Rounding to µL shifts the smallest addition by at most half a µL.
HALF_MICROLITRE_ERROR = 0.5 * 10**-VOLUME_DECIMALS / MIN_ADDITION_ML

CHEMICAL_BY_ROLE = {
    "photosensitizer": "Ru(bpy)3Cl2·6H2O",
    "catalyst": "Ru(bda)(isoq)2",
    "sacrificial_oxidant": "Na2S2O8",
}


@pytest.fixture
def chemicals():
    """Synthetic chemicals database with round molar masses."""
    return pd.DataFrame(
        {
            "category": ["PS", "cat", "sac reagent", "acid", "base"],
            "M (g/mol)": [1000.0, 500.0, 200.0, 100.0, 100.0],
            "max_solubility_M": [0.05, 120e-6, 1.0, 4.0, 0.5],
        },
        index=pd.Index([*CHEMICAL_BY_ROLE.values(), "NaH2PO4", "Na2HPO4"], name="Name"),
    )


def build_experiments(photosensitizer, catalyst, ph=7.0):
    """Experiment table with the given photosensitizer and catalyst concentrations and pH."""
    return pd.DataFrame(
        {
            "photosensitizer_M": photosensitizer,
            "catalyst_M": catalyst,
            "sacrificial_oxidant_M": 0.01,
            "pH": ph,
            **DEFAULT_ROBOT_SETTINGS,
        }
    )


def plan(experiments, chemicals, replicates=1, total_volume_ml=TOTAL_VOLUME_ML, buffer_concentration=BUFFER_CONCENTRATION):
    """Plan a run with the test defaults."""
    return plan_run(
        experiments, replicates, CHEMICAL_BY_ROLE, chemicals, total_volume_ml, BUFFER_SYSTEM, buffer_concentration
    )


def stock_of(run_plan, role):
    """The stock solution row of one role."""
    return run_plan.stocks.set_index("Role").loc[role]


def test_volumes_reach_the_target_concentrations(chemicals):
    experiments = build_experiments([5e-5, 1e-4, 2e-4], [1e-5, 1e-5, 1e-5])
    run_plan = plan(experiments, chemicals)

    reached = run_plan.vials["volume_photosensitizer"] * stock_of(run_plan, "photosensitizer")["Concentration_M"] / TOTAL_VOLUME_ML
    np.testing.assert_allclose(reached, experiments["photosensitizer_M"], rtol=HALF_MICROLITRE_ERROR)


def test_highest_concentration_gets_the_largest_addition(chemicals):
    run_plan = plan(build_experiments([5e-5, 2e-4], [1e-5, 1e-5]), chemicals)

    assert run_plan.vials["volume_photosensitizer"].max() == MAX_ADDITION_ML
    assert stock_of(run_plan, "photosensitizer")["Concentration_M"] == 2e-3


def test_every_addition_is_within_the_pipetting_limits(chemicals):
    run_plan = plan(build_experiments([5e-5, 1e-4, 2e-4], [3e-6, 6e-6, 1.2e-5], ph=[6.8, 7.0, 7.2]), chemicals, replicates=2)

    volumes = run_plan.vials[[column for column in run_plan.vials if column.startswith("volume_") and column != "volume_water"]]
    assert ((volumes >= MIN_ADDITION_ML) & (volumes <= MAX_ADDITION_ML)).all().all()


def test_too_wide_spread_is_rejected(chemicals):
    with pytest.raises(PlanningError, match="differ by a factor of 5.00"):
        plan(build_experiments([1e-5, 5e-5], [1e-5, 1e-5]), chemicals)


def test_concentration_above_solubility_is_rejected(chemicals):
    # 1.3e-5 M needs a 1.3e-4 M stock; the catalyst dissolves only up to 1.2e-4 M.
    with pytest.raises(PlanningError, match="solubility"):
        plan(build_experiments([1e-4], [1.3e-5]), chemicals)


def test_stock_exactly_at_solubility_is_accepted(chemicals):
    run_plan = plan(build_experiments([1e-4], [1.2e-5]), chemicals)

    assert stock_of(run_plan, "catalyst")["Concentration_M"] == 120e-6


def test_buffer_is_split_equally_at_the_pka():
    acid, base = split_buffer(pd.Series([7.0]), 7.0, 0.01)

    assert acid.iloc[0] == pytest.approx(0.005)
    assert base.iloc[0] == pytest.approx(0.005)


def test_one_ph_unit_above_the_pka_gives_ten_times_more_base():
    acid, base = split_buffer(pd.Series([8.0]), 7.0, 0.011)

    assert acid.iloc[0] == pytest.approx(0.001)
    assert base.iloc[0] == pytest.approx(0.01)


def test_buffer_volumes_reach_the_ph_and_total_concentration(chemicals):
    run_plan = plan(build_experiments([5e-5] * 3, [1e-5] * 3, ph=[6.7, 7.0, 7.3]), chemicals)

    acid = run_plan.vials["volume_buffer_acid"] * stock_of(run_plan, "buffer_acid")["Concentration_M"] / TOTAL_VOLUME_ML
    base = run_plan.vials["volume_buffer_base"] * stock_of(run_plan, "buffer_base")["Concentration_M"] / TOTAL_VOLUME_ML
    np.testing.assert_allclose(acid + base, BUFFER_CONCENTRATION, rtol=HALF_MICROLITRE_ERROR)
    np.testing.assert_allclose(BUFFER_SYSTEM["pKa"] + np.log10(base / acid), [6.7, 7.0, 7.3], atol=2e-3)


def test_too_wide_ph_range_is_rejected(chemicals):
    with pytest.raises(PlanningError, match="Narrow the pH range"):
        plan(build_experiments([5e-5] * 2, [1e-5] * 2, ph=[6.0, 8.0]), chemicals)


def test_run_without_buffer_gets_no_buffer_stocks(chemicals):
    run_plan = plan(build_experiments([5e-5], [1e-5]), chemicals, buffer_concentration=0.0)

    assert not {"buffer_acid", "buffer_base"} & set(run_plan.stocks["Role"])
    assert run_plan.vials[["volume_buffer_acid", "volume_buffer_base"]].eq(0).all().all()


def test_negative_buffer_concentration_is_rejected(chemicals):
    with pytest.raises(PlanningError, match="negative"):
        plan(build_experiments([5e-5], [1e-5]), chemicals, buffer_concentration=-0.01)


def test_water_fills_up_to_the_total_volume(chemicals):
    run_plan = plan(build_experiments([5e-5, 2e-4], [0.0, 1e-5]), chemicals)

    volume_columns = [column for column in run_plan.vials if column.startswith("volume_")]
    np.testing.assert_allclose(run_plan.vials[volume_columns].sum(axis=1), TOTAL_VOLUME_ML)


def test_overfilled_vial_is_rejected(chemicals):
    with pytest.raises(PlanningError, match="exceed the total volume"):
        plan(build_experiments([5e-5], [1e-6]), chemicals, total_volume_ml=1.0)


def test_led_current_the_driver_cannot_set_is_rejected(chemicals):
    experiments = build_experiments([5e-5, 5e-5], [1e-5, 1e-5]).assign(LED_driver_current_mA=[350, 400])

    with pytest.raises(PlanningError, match="LED current must be one of 0, 350, 500, 700, 1000 mA"):
        plan(experiments, chemicals)


def test_every_selectable_led_current_is_accepted(chemicals):
    experiments = build_experiments([5e-5] * 5, [1e-5] * 5).assign(LED_driver_current_mA=[0, 350, 500, 700, 1000])

    assert plan(experiments, chemicals).vials["LED_driver_current_mA"].tolist() == [0, 350, 500, 700, 1000]


def test_empty_cell_is_rejected(chemicals):
    with pytest.raises(PlanningError, match="empty"):
        plan(build_experiments([5e-5, None], [1e-5, 1e-5]), chemicals)


def test_names_count_up_per_letter_pair(chemicals):
    run_plan = plan(build_experiments([5e-5, 5e-5, 0.0], [1e-5, 0.0, 1e-5]), chemicals, replicates=2)

    assert run_plan.vials["name"].tolist() == [
        "MRG-059-BC-01",
        "MRG-059-BC-02",
        "MRG-059-BA-01",
        "MRG-059-BA-02",
        "MRG-059-AC-01",
        "MRG-059-AC-02",
    ]


def test_each_letter_pair_starts_at_its_own_number(chemicals):
    experiments = build_experiments([5e-5, 5e-5, 0.0], [1e-5, 0.0, 1e-5])
    run_plan = plan_run(
        experiments, 2, CHEMICAL_BY_ROLE, chemicals, TOTAL_VOLUME_ML, BUFFER_SYSTEM, BUFFER_CONCENTRATION, {"BC": 13, "BA": 5}
    )

    # AC is not listed and starts at 1.
    assert run_plan.vials["name"].tolist() == [
        "MRG-059-BC-13",
        "MRG-059-BC-14",
        "MRG-059-BA-05",
        "MRG-059-BA-06",
        "MRG-059-AC-01",
        "MRG-059-AC-02",
    ]


def test_numbers_beyond_two_digits_are_not_cut(chemicals):
    run_plan = plan_run(
        build_experiments([5e-5], [1e-5]), 2, CHEMICAL_BY_ROLE, chemicals, TOTAL_VOLUME_ML, BUFFER_SYSTEM, BUFFER_CONCENTRATION, {"BC": 99}
    )

    assert run_plan.vials["name"].tolist() == ["MRG-059-BC-99", "MRG-059-BC-100"]


def test_component_left_out_gets_no_volume(chemicals):
    run_plan = plan(build_experiments([5e-5, 5e-5], [1e-5, 0.0]), chemicals)

    assert run_plan.vials["volume_catalyst"].tolist() == [MAX_ADDITION_ML, 0.0]


def test_unused_component_gets_no_stock(chemicals):
    run_plan = plan(build_experiments([5e-5], [0.0]), chemicals)

    assert "catalyst" not in run_plan.stocks["Role"].tolist()


def test_stock_volume_covers_the_run_with_safety_margin(chemicals):
    # Eight vials of 0.85 mL persulfate: 6.8 mL pipetted, 8.84 mL with the margin.
    run_plan = plan(build_experiments([5e-5] * 4, [1e-5] * 4), chemicals, replicates=2)

    stock = stock_of(run_plan, "sacrificial_oxidant")
    assert stock["Volume_mL"] == pytest.approx(8 * MAX_ADDITION_ML * STOCK_SAFETY_FACTOR)
    assert stock["Mass_mg"] == pytest.approx(stock["Concentration_M"] * stock["Volume_mL"] * 200.0, abs=1e-3)


def test_small_stock_is_made_up_to_the_minimum_volume(chemicals):
    run_plan = plan(build_experiments([5e-5], [1e-5]), chemicals)

    assert stock_of(run_plan, "sacrificial_oxidant")["Volume_mL"] == MIN_STOCK_VOLUME_ML


def test_dilute_stock_is_enlarged_to_the_minimum_mass(chemicals):
    # 1e-4 M at 500 g/mol is 0.05 mg/mL, so 0.5 mg needs 10 mL.
    stock = stock_of(plan(build_experiments([5e-5], [1e-5]), chemicals), "catalyst")

    assert stock["Volume_mL"] == pytest.approx(10.0)
    assert stock["Mass_mg"] == MIN_WEIGHED_MASS_MG


def test_stock_lists_the_amount_weighed_in(chemicals):
    # 1e-4 M × 10 mL = 1e-3 mmol, which at 500 g/mol is the 0.5 mg weighed in.
    stock = stock_of(plan(build_experiments([5e-5], [1e-5]), chemicals), "catalyst")

    assert stock["Amount_mmol"] == pytest.approx(1e-3)


def test_experiment_design_lists_chemicals_by_name_with_water_buffer_and_ph(chemicals):
    run_plan = plan(build_experiments([5e-5], [1e-5], ph=7.3), chemicals, replicates=2)
    design = build_experiment_design(run_plan)

    chemical_columns = [f"{chemical}_M" for chemical in [*CHEMICAL_BY_ROLE.values(), "NaH2PO4", "Na2HPO4"]]
    assert design.columns.tolist() == [
        "Experiment",
        "total_volume_µL",
        "water_volume_mL",
        *chemical_columns,
        "buffer_total_M",
        "pH",
    ]
    assert design["total_volume_µL"].tolist() == [8500.0, 8500.0]
    assert design["water_volume_mL"].tolist() == run_plan.vials["volume_water"].tolist()
    assert design["pH"].tolist() == [7.3, 7.3]


def test_experiment_design_rounds_concentrations_but_the_plan_keeps_them_exact(chemicals):
    # 0.3 pH units above the pKa: acid = 0.01 M / (1 + 10^0.3) = 0.0033386 M.
    run_plan = plan(build_experiments([5e-5], [1e-5], ph=7.3), chemicals)
    design = build_experiment_design(run_plan)

    assert design["NaH2PO4_M"].iloc[0] == 0.003339
    assert design["Na2HPO4_M"].iloc[0] == 0.006661
    assert run_plan.vials["buffer_acid_M"].iloc[0] == pytest.approx(0.01 / (1 + 10**0.3), rel=1e-12)


def test_robot_file_has_one_entry_per_vial_and_a_stop_entry(chemicals):
    experiments = build_experiments([5e-5, 1e-4], [1e-5, 1e-5]).assign(voltage=[0.18, 0.2])
    run_plan = plan(experiments, chemicals, replicates=2)
    entries = yaml.safe_load(format_robot_file(run_plan))

    assert [entry["name"] for entry in entries] == run_plan.vials["name"].tolist() + [STOP_ENTRY_NAME]
    assert [entry["run"] for entry in entries] == ["true"] * 4 + ["false"]
    assert [entry["voltage"] for entry in entries] == [0.18, 0.18, 0.2, 0.2, 0.2]
    assert all(list(entry) == list(ROBOT_FILE_KEYS) for entry in entries)
    assert entries[0]["volume_buffer_base"] == run_plan.vials.loc[0, "volume_buffer_base"]


def test_written_files_read_back(chemicals, tmp_path):
    run_plan = plan(build_experiments([5e-5], [1e-5]), chemicals, replicates=2)
    write_run_files(run_plan, tmp_path / "run")

    design = pd.read_csv(tmp_path / "run" / "experiments_design.csv", sep=";")
    stocks = pd.read_csv(tmp_path / "run" / "stock_solutions.csv", sep=";")
    assert design["Experiment"].tolist() == ["MRG-059-BC-01", "MRG-059-BC-02"]
    assert stocks["Chemical"].tolist() == [*CHEMICAL_BY_ROLE.values(), "NaH2PO4", "Na2HPO4"]


def test_existing_run_folder_is_not_overwritten(chemicals, tmp_path):
    run_plan = plan(build_experiments([5e-5], [1e-5]), chemicals)
    write_run_files(run_plan, tmp_path / "run")

    with pytest.raises(FileExistsError):
        write_run_files(run_plan, tmp_path / "run")


def test_load_chemicals_reads_solubility_exactly(tmp_path):
    path = tmp_path / "chemicals.csv"
    path.write_text("Name;category;M (g/mol);max_solubility_M\nRu(bda)(isoq)2;cat;601.58;120e-6\n", encoding="utf-8")

    assert load_chemicals(path).loc["Ru(bda)(isoq)2", "max_solubility_M"] == 1.2e-4


def test_load_buffers_reads_the_pairs(tmp_path):
    path = tmp_path / "buffers.csv"
    path.write_text("Name;acid;base;pKa;comment\nPhosphate;NaH2PO4;Na2HPO4;7.21;literature\n", encoding="utf-8")

    assert load_buffers(path).loc["Phosphate"].to_dict() == {
        "acid": "NaH2PO4",
        "base": "Na2HPO4",
        "pKa": 7.21,
        "comment": "literature",
    }
