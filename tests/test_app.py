from pathlib import Path

from streamlit.testing.v1 import AppTest


APP_FILE = str(Path(__file__).parent.parent / "app.py")


def find_number_input(app, label):
    """The number input whose label starts with `label`."""
    return next(widget for widget in app.number_input if widget.label.startswith(label))


def test_default_run_is_planned():
    app = AppTest.from_file(APP_FILE).run()

    assert not app.exception
    assert not app.error
    # The first table is the editable experiment table: 4 experiments, 2 vials each.
    assert [table.value.shape[0] for table in app.dataframe] == [4, 8, 5, 8]


def test_experiments_are_numbered_from_one():
    app = AppTest.from_file(APP_FILE).run()

    assert app.dataframe[0].value.index.tolist() == [1, 2, 3, 4]


def test_buffer_caption_states_the_usable_ph_range():
    app = AppTest.from_file(APP_FILE).run()

    # Phosphate, pKa 7.21.
    assert any("Usable pH range: 6.21–8.21" in caption.value for caption in app.caption)


def test_input_units_are_converted_to_molar():
    app = AppTest.from_file(APP_FILE).run()
    design = app.dataframe[3].value

    # Defaults: 50 µM photosensitizer, 10 mM persulfate, 10 mM buffer.
    assert design["Ru(bpy)3Cl2·6H2O_M"].iloc[0] == 5e-5
    assert design["Na2S2O8_M"].iloc[0] == 1e-2
    assert design["buffer_total_M"].iloc[0] == 1e-2


def test_start_number_renames_the_vials():
    app = AppTest.from_file(APP_FILE).run()
    find_number_input(app, "Start MRG-059-BC-").set_value(13).run()

    assert app.dataframe[1].value["name"].tolist()[:2] == ["MRG-059-BC-13", "MRG-059-BC-14"]


def test_impossible_run_shows_an_error():
    app = AppTest.from_file(APP_FILE).run()
    find_number_input(app, "Total volume").set_value(0.5).run()

    assert "The calculation is not possible" in app.error[0].value
