from collections import OrderedDict
import json
import re
import subprocess
from subprocess import CalledProcessError
import tempfile
from typing import Any
from typing import Callable
from typing import List
from typing import Optional
from typing import Tuple

import numpy as np
from pandas import Timedelta
from pandas import Timestamp
import pytest
import yaml

import optuna
import optuna.cli
from optuna.exceptions import CLIUsageError
from optuna.storages import RDBStorage
from optuna.storages._base import DEFAULT_STUDY_NAME_PREFIX
from optuna.study import StudyDirection
from optuna.testing.storage import StorageSupplier
from optuna.trial import Trial
from optuna.trial import TrialState


# An example of objective functions
def objective_func(trial: Trial) -> float:

    x = trial.suggest_float("x", -10, 10)
    return (x + 5) ** 2


# An example of objective functions for branched search spaces
def objective_func_branched_search_space(trial: Trial) -> float:

    c = trial.suggest_categorical("c", ("A", "B"))
    if c == "A":
        x = trial.suggest_float("x", -10, 10)
        return (x + 5) ** 2
    else:
        y = trial.suggest_float("y", -10, 10)
        return (y + 5) ** 2


# An example of objective functions for multi-objective optimization
def objective_func_multi_objective(trial: Trial) -> Tuple[float, float]:

    x = trial.suggest_float("x", -10, 10)
    return (x + 5) ** 2, (x - 5) ** 2


def _parse_output(output: str, output_format: Optional[str]) -> Any:

    if output_format is None or output_format == "table":
        rows = output.split("\n")
        assert all(len(rows[0]) == len(row) for row in rows)
        assert rows[0] == rows[2] == rows[-1]

        keys = [r.strip() for r in rows[1].split("|")[1:-1]]
        ret = []
        for record in rows[3:-1]:
            attrs = OrderedDict()
            for key, attr in zip(keys, record.split("|")[1:-1]):
                attrs[key] = attr.strip()
            ret.append(attrs)
        return ret
    elif output_format == "json":
        return json.loads(output)
    elif output_format == "yaml":
        return yaml.safe_load(output)
    else:
        assert False


def test_create_study_command() -> None:

    with StorageSupplier("sqlite") as storage:
        assert isinstance(storage, RDBStorage)
        storage_url = str(storage.engine.url)

        # Create study.
        command = ["optuna", "create-study", "--storage", storage_url]
        subprocess.check_call(command)

        # Command output should be in name string format (no-name + UUID).
        study_name = str(subprocess.check_output(command).decode().strip())
        name_re = r"^no-name-[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$"
        assert re.match(name_re, study_name) is not None

        # study_name should be stored in storage.
        study_id = storage.get_study_id_from_name(study_name)
        assert study_id == 2


def test_create_study_command_with_study_name() -> None:

    with StorageSupplier("sqlite") as storage:
        assert isinstance(storage, RDBStorage)
        storage_url = str(storage.engine.url)
        study_name = "test_study"

        # Create study with name.
        command = ["optuna", "create-study", "--storage", storage_url, "--study-name", study_name]
        study_name = str(subprocess.check_output(command).decode().strip())

        # Check if study_name is stored in the storage.
        study_id = storage.get_study_id_from_name(study_name)
        assert storage.get_study_name_from_id(study_id) == study_name


def test_create_study_command_without_storage_url() -> None:

    with pytest.raises(subprocess.CalledProcessError) as err:
        subprocess.check_output(["optuna", "create-study"])
    usage = err.value.output.decode()
    assert usage.startswith("usage:")


def test_create_study_command_with_direction() -> None:

    with StorageSupplier("sqlite") as storage:
        assert isinstance(storage, RDBStorage)
        storage_url = str(storage.engine.url)

        command = ["optuna", "create-study", "--storage", storage_url, "--direction", "minimize"]
        study_name = str(subprocess.check_output(command).decode().strip())
        study_id = storage.get_study_id_from_name(study_name)
        assert storage.get_study_directions(study_id) == [StudyDirection.MINIMIZE]

        command = ["optuna", "create-study", "--storage", storage_url, "--direction", "maximize"]
        study_name = str(subprocess.check_output(command).decode().strip())
        study_id = storage.get_study_id_from_name(study_name)
        assert storage.get_study_directions(study_id) == [StudyDirection.MAXIMIZE]

        command = ["optuna", "create-study", "--storage", storage_url, "--direction", "test"]

        # --direction should be either 'minimize' or 'maximize'.
        with pytest.raises(subprocess.CalledProcessError):
            subprocess.check_call(command)


def test_create_study_command_with_multiple_directions() -> None:

    with StorageSupplier("sqlite") as storage:
        assert isinstance(storage, RDBStorage)
        storage_url = str(storage.engine.url)
        command = [
            "optuna",
            "create-study",
            "--storage",
            storage_url,
            "--directions",
            "minimize",
            "maximize",
        ]

        study_name = str(subprocess.check_output(command).decode().strip())
        study_id = storage.get_study_id_from_name(study_name)
        expected_directions = [StudyDirection.MINIMIZE, StudyDirection.MAXIMIZE]
        assert storage.get_study_directions(study_id) == expected_directions

        command = [
            "optuna",
            "create-study",
            "--storage",
            storage_url,
            "--directions",
            "minimize",
            "maximize",
            "test",
        ]

        # Each direction in --directions should be either `minimize` or `maximize`.
        with pytest.raises(subprocess.CalledProcessError):
            subprocess.check_call(command)

        command = [
            "optuna",
            "create-study",
            "--storage",
            storage_url,
            "--direction",
            "minimize",
            "--directions",
            "minimize",
            "maximize",
            "test",
        ]

        # It can't specify both --direction and --directions
        with pytest.raises(subprocess.CalledProcessError):
            subprocess.check_call(command)


def test_delete_study_command() -> None:

    with StorageSupplier("sqlite") as storage:
        assert isinstance(storage, RDBStorage)
        storage_url = str(storage.engine.url)
        study_name = "delete-study-test"

        # Create study.
        command = ["optuna", "create-study", "--storage", storage_url, "--study-name", study_name]
        subprocess.check_call(command)
        assert study_name in {s.study_name: s for s in storage.get_all_study_summaries()}

        # Delete study.
        command = ["optuna", "delete-study", "--storage", storage_url, "--study-name", study_name]
        subprocess.check_call(command)
        assert study_name not in {s.study_name: s for s in storage.get_all_study_summaries()}


def test_delete_study_command_without_storage_url() -> None:

    with pytest.raises(subprocess.CalledProcessError):
        subprocess.check_output(["optuna", "delete-study", "--study-name", "dummy_study"])


def test_study_set_user_attr_command() -> None:

    with StorageSupplier("sqlite") as storage:
        assert isinstance(storage, RDBStorage)
        storage_url = str(storage.engine.url)

        # Create study.
        study_name = storage.get_study_name_from_id(storage.create_new_study())

        base_command = [
            "optuna",
            "study",
            "set-user-attr",
            "--study-name",
            study_name,
            "--storage",
            storage_url,
        ]

        example_attrs = {"architecture": "ResNet", "baselen_score": "0.002"}
        for key, value in example_attrs.items():
            subprocess.check_call(base_command + ["--key", key, "--value", value])

        # Attrs should be stored in storage.
        study_id = storage.get_study_id_from_name(study_name)
        study_user_attrs = storage.get_study_user_attrs(study_id)
        assert len(study_user_attrs) == 2
        assert all(study_user_attrs[k] == v for k, v in example_attrs.items())


@pytest.mark.parametrize("output_format", ("table", "json", "yaml"))
@pytest.mark.parametrize("flatten", (True, False))
def test_studies_command(output_format: str, flatten: bool) -> None:

    with StorageSupplier("sqlite") as storage:
        assert isinstance(storage, RDBStorage)
        storage_url = str(storage.engine.url)

        # First study.
        study_1 = optuna.create_study(storage)

        # Second study.
        study_2 = optuna.create_study(
            storage, study_name="study_2", directions=["minimize", "maximize"]
        )
        study_2.optimize(objective_func_multi_objective, n_trials=10)

        # Run command.
        command = ["optuna", "studies", "--storage", storage_url, "--format", output_format]
        if flatten:
            command.append("--flatten")

        output = str(subprocess.check_output(command).decode().strip())
        studies = _parse_output(output, output_format)

        if flatten:
            if output_format == "table":
                expected_keys_1 = [
                    "name",
                    "direction_0",
                    "direction_1",
                    "n_trials",
                    "datetime_start",
                ]
                expected_keys_2 = [
                    "name",
                    "direction_0",
                    "direction_1",
                    "n_trials",
                    "datetime_start",
                ]
            else:
                expected_keys_1 = ["name", "direction_0", "n_trials", "datetime_start"]
                expected_keys_2 = [
                    "name",
                    "direction_0",
                    "direction_1",
                    "n_trials",
                    "datetime_start",
                ]
        else:
            expected_keys_1 = ["name", "direction", "n_trials", "datetime_start"]
            expected_keys_2 = ["name", "direction", "n_trials", "datetime_start"]

        assert len(studies) == 2
        if output_format == "table":
            assert list(studies[0].keys()) == expected_keys_1
            assert list(studies[1].keys()) == expected_keys_2
        else:
            assert set(studies[0].keys()) == set(expected_keys_1)
            assert set(studies[1].keys()) == set(expected_keys_2)

        # Check study_name, direction, and n_trials for the first study.
        assert studies[0]["name"] == study_1.study_name
        if output_format == "table":
            assert studies[0]["n_trials"] == "0"
            if flatten:
                assert studies[0]["direction_0"] == "MINIMIZE"
            else:
                assert eval(studies[0]["direction"]) == ("MINIMIZE",)
        else:
            assert studies[0]["n_trials"] == 0
            if flatten:
                assert studies[0]["direction_0"] == "MINIMIZE"
            else:
                assert studies[0]["direction"] == [
                    "MINIMIZE",
                ]

        # Check study_name, direction, and n_trials for the second study.
        assert studies[1]["name"] == study_2.study_name
        if output_format == "table":
            assert studies[1]["n_trials"] == "10"
            if flatten:
                assert studies[1]["direction_0"] == "MINIMIZE"
                assert studies[1]["direction_1"] == "MAXIMIZE"
            else:
                assert eval(studies[1]["direction"]) == ("MINIMIZE", "MAXIMIZE")
        else:
            assert studies[1]["n_trials"] == 10
            if flatten:
                assert studies[1]["direction_0"] == "MINIMIZE"
                assert studies[1]["direction_1"] == "MAXIMIZE"
            else:
                assert studies[1]["direction"] == ["MINIMIZE", "MAXIMIZE"]


@pytest.mark.parametrize("objective", (objective_func, objective_func_branched_search_space))
@pytest.mark.parametrize("output_format", ("table", "json", "yaml"))
@pytest.mark.parametrize("flatten", (True, False))
def test_trials_command(
    objective: Callable[[Trial], float], output_format: str, flatten: bool
) -> None:

    with StorageSupplier("sqlite") as storage:
        assert isinstance(storage, RDBStorage)
        storage_url = str(storage.engine.url)
        study_name = "test_study"
        n_trials = 10

        study = optuna.create_study(storage, study_name=study_name)
        study.optimize(objective, n_trials=n_trials)
        attrs = (
            "number",
            "value",
            "datetime_start",
            "datetime_complete",
            "duration",
            "params",
            "user_attrs",
            "state",
        )

        # Run command.
        command = [
            "optuna",
            "trials",
            "--storage",
            storage_url,
            "--study-name",
            study_name,
            "--format",
            output_format,
        ]

        if flatten:
            command.append("--flatten")

        output = str(subprocess.check_output(command).decode().strip())
        trials = _parse_output(output, output_format)

        assert len(trials) == n_trials

        if flatten:
            df = study.trials_dataframe(attrs)

            for i, trial in enumerate(trials):
                assert set(trial.keys()) <= set(df.columns)
                for key in df.columns:
                    expected_value = df.loc[i][key]
                    if (
                        key.startswith("params_")
                        and isinstance(expected_value, float)
                        and np.isnan(expected_value)
                    ):
                        if output_format == "table":
                            assert trial[key] == ""
                        else:
                            assert key not in trial
                        continue

                    value = trial[key]

                    if isinstance(value, (int, float)):
                        if np.isnan(expected_value):
                            assert np.isnan(value)
                        else:
                            assert value == expected_value
                    elif isinstance(expected_value, Timestamp):
                        assert value == expected_value.strftime("%Y-%m-%d %H:%M:%S")
                    elif isinstance(expected_value, Timedelta):
                        assert value == str(expected_value.to_pytimedelta())
                    else:
                        assert value == str(expected_value)
        else:
            df = study.trials_dataframe(attrs, multi_index=True)

            for i, trial in enumerate(trials):
                for key in df.columns:
                    expected_value = df.loc[i][key]
                    if (
                        key[0] == "params"
                        and isinstance(expected_value, float)
                        and np.isnan(expected_value)
                    ):
                        if output_format == "table":
                            assert key[1] not in eval(trial["params"])
                        else:
                            assert key[1] not in trial["params"]
                        continue

                    if key[1] == "":
                        value = trial[key[0]]
                    else:
                        if output_format == "table":
                            value = eval(trial[key[0]])[key[1]]
                        else:
                            value = trial[key[0]][key[1]]

                    if isinstance(value, (int, float)):
                        if np.isnan(expected_value):
                            assert np.isnan(value)
                        else:
                            assert value == expected_value
                    elif isinstance(expected_value, Timestamp):
                        assert value == expected_value.strftime("%Y-%m-%d %H:%M:%S")
                    elif isinstance(expected_value, Timedelta):
                        assert value == str(expected_value.to_pytimedelta())
                    else:
                        assert value == str(expected_value)


@pytest.mark.parametrize("objective", (objective_func, objective_func_branched_search_space))
@pytest.mark.parametrize("output_format", ("table", "json", "yaml"))
@pytest.mark.parametrize("flatten", (True, False))
def test_best_trial_command(
    objective: Callable[[Trial], float], output_format: str, flatten: bool
) -> None:

    with StorageSupplier("sqlite") as storage:
        assert isinstance(storage, RDBStorage)
        storage_url = str(storage.engine.url)
        study_name = "test_study"
        n_trials = 10

        study = optuna.create_study(storage, study_name=study_name)
        study.optimize(objective, n_trials=n_trials)
        attrs = (
            "number",
            "value",
            "datetime_start",
            "datetime_complete",
            "duration",
            "params",
            "user_attrs",
            "state",
        )

        # Run command.
        command = [
            "optuna",
            "best-trial",
            "--storage",
            storage_url,
            "--study-name",
            study_name,
            "--format",
            output_format,
        ]

        if flatten:
            command.append("--flatten")

        output = str(subprocess.check_output(command).decode().strip())
        best_trial = _parse_output(output, output_format)

        if output_format == "table":
            assert len(best_trial) == 1
            best_trial = best_trial[0]

        if flatten:
            df = study.trials_dataframe(attrs)

            assert set(best_trial.keys()) <= set(df.columns)
            for key in df.columns:
                expected_value = df.loc[study.best_trial.number][key]
                if (
                    key.startswith("params_")
                    and isinstance(expected_value, float)
                    and np.isnan(expected_value)
                ):
                    if output_format == "table":
                        assert best_trial[key] == ""
                    else:
                        assert key not in best_trial
                    continue
                value = best_trial[key]
                if isinstance(value, (int, float)):
                    if np.isnan(expected_value):
                        assert np.isnan(value)
                    else:
                        assert value == expected_value
                elif isinstance(expected_value, Timestamp):
                    assert value == expected_value.strftime("%Y-%m-%d %H:%M:%S")
                elif isinstance(expected_value, Timedelta):
                    assert value == str(expected_value.to_pytimedelta())
                else:
                    assert value == str(expected_value)
        else:
            df = study.trials_dataframe(attrs, multi_index=True)

            for key in df.columns:
                expected_value = df.loc[study.best_trial.number][key]
                if (
                    key[0] == "params"
                    and isinstance(expected_value, float)
                    and np.isnan(expected_value)
                ):
                    if output_format == "table":
                        assert key[1] not in eval(best_trial["params"])
                    else:
                        assert key[1] not in best_trial["params"]
                    continue

                if key[1] == "":
                    value = best_trial[key[0]]
                else:
                    if output_format == "table":
                        value = eval(best_trial[key[0]])[key[1]]
                    else:
                        value = best_trial[key[0]][key[1]]

                if isinstance(value, (int, float)):
                    if np.isnan(expected_value):
                        assert np.isnan(value)
                    else:
                        assert value == expected_value
                elif isinstance(expected_value, Timestamp):
                    assert value == expected_value.strftime("%Y-%m-%d %H:%M:%S")
                elif isinstance(expected_value, Timedelta):
                    assert value == str(expected_value.to_pytimedelta())
                else:
                    assert value == str(expected_value)


@pytest.mark.parametrize("output_format", ("table", "json", "yaml"))
@pytest.mark.parametrize("flatten", (True, False))
def test_best_trials_command(output_format: str, flatten: bool) -> None:

    with StorageSupplier("sqlite") as storage:
        assert isinstance(storage, RDBStorage)
        storage_url = str(storage.engine.url)
        study_name = "test_study"
        n_trials = 10

        study = optuna.create_study(
            storage, study_name=study_name, directions=("minimize", "minimize")
        )
        study.optimize(objective_func_multi_objective, n_trials=n_trials)
        attrs = (
            "number",
            "values",
            "datetime_start",
            "datetime_complete",
            "duration",
            "params",
            "user_attrs",
            "state",
        )

        # Run command.
        command = [
            "optuna",
            "best-trials",
            "--storage",
            storage_url,
            "--study-name",
            study_name,
            "--format",
            output_format,
        ]

        if flatten:
            command.append("--flatten")

        output = str(subprocess.check_output(command).decode().strip())
        trials = _parse_output(output, output_format)
        best_trials = [trial.number for trial in study.best_trials]

        assert len(trials) == len(best_trials)

        if flatten:
            df = study.trials_dataframe(attrs)

            for trial in trials:
                assert set(trial.keys()) <= set(df.columns)
                if output_format == "table":
                    assert int(trial["number"]) in best_trials
                else:
                    assert trial["number"] in best_trials
                for key in df.columns:
                    if output_format == "table":
                        expected_value = df.loc[int(trial["number"])][key]
                    else:
                        expected_value = df.loc[trial["number"]][key]
                    if (
                        key.startswith("params_")
                        and isinstance(expected_value, float)
                        and np.isnan(expected_value)
                    ):
                        if output_format == "table":
                            assert trial[key] == ""
                        else:
                            assert key not in trial
                        continue
                    value = trial[key]
                    if isinstance(value, (int, float)):
                        if np.isnan(expected_value):
                            assert np.isnan(value)
                        else:
                            assert value == expected_value
                    elif isinstance(expected_value, Timestamp):
                        assert value == expected_value.strftime("%Y-%m-%d %H:%M:%S")
                    elif isinstance(expected_value, Timedelta):
                        assert value == str(expected_value.to_pytimedelta())
                    else:
                        assert value == str(expected_value)
        else:
            df = study.trials_dataframe(attrs, multi_index=True)

            for trial in trials:
                if output_format == "table":
                    assert int(trial["number"]) in best_trials
                else:
                    assert trial["number"] in best_trials
                for key in df.columns:
                    if output_format == "table":
                        expected_value = df.loc[int(trial["number"])][key]
                    else:
                        expected_value = df.loc[trial["number"]][key]
                    if (
                        key[0] == "params"
                        and isinstance(expected_value, float)
                        and np.isnan(expected_value)
                    ):
                        if output_format == "table":
                            assert key[1] not in eval(trial["params"])
                        else:
                            assert key[1] not in trial["params"]
                        continue

                    if key[1] == "":
                        value = trial[key[0]]
                    else:
                        if output_format == "table":
                            value = eval(trial[key[0]])[key[1]]
                        else:
                            value = trial[key[0]][key[1]]

                    if isinstance(value, (int, float)):
                        if np.isnan(expected_value):
                            assert np.isnan(value)
                        else:
                            assert value == expected_value
                    elif isinstance(expected_value, Timestamp):
                        assert value == expected_value.strftime("%Y-%m-%d %H:%M:%S")
                    elif isinstance(expected_value, Timedelta):
                        assert value == str(expected_value.to_pytimedelta())
                    else:
                        assert value == str(expected_value)


def test_create_study_command_with_skip_if_exists() -> None:

    with StorageSupplier("sqlite") as storage:
        assert isinstance(storage, RDBStorage)
        storage_url = str(storage.engine.url)
        study_name = "test_study"

        # Create study with name.
        command = ["optuna", "create-study", "--storage", storage_url, "--study-name", study_name]
        study_name = str(subprocess.check_output(command).decode().strip())

        # Check if study_name is stored in the storage.
        study_id = storage.get_study_id_from_name(study_name)
        assert storage.get_study_name_from_id(study_id) == study_name

        # Try to create the same name study without `--skip-if-exists` flag (error).
        command = ["optuna", "create-study", "--storage", storage_url, "--study-name", study_name]
        with pytest.raises(subprocess.CalledProcessError):
            subprocess.check_output(command)

        # Try to create the same name study with `--skip-if-exists` flag (OK).
        command = [
            "optuna",
            "create-study",
            "--storage",
            storage_url,
            "--study-name",
            study_name,
            "--skip-if-exists",
        ]
        study_name = str(subprocess.check_output(command).decode().strip())
        new_study_id = storage.get_study_id_from_name(study_name)
        assert study_id == new_study_id  # The existing study instance is reused.


def test_dashboard_command() -> None:

    with StorageSupplier("sqlite") as storage, tempfile.NamedTemporaryFile("r") as tf_report:
        assert isinstance(storage, RDBStorage)
        storage_url = str(storage.engine.url)

        study_name = storage.get_study_name_from_id(storage.create_new_study())

        command = [
            "optuna",
            "dashboard",
            "--study-name",
            study_name,
            "--out",
            tf_report.name,
            "--storage",
            storage_url,
        ]
        subprocess.check_call(command)

        html = tf_report.read()
        assert "<body>" in html
        assert "bokeh" in html


@pytest.mark.parametrize(
    "origins", [["192.168.111.1:5006"], ["192.168.111.1:5006", "192.168.111.2:5006"]]
)
def test_dashboard_command_with_allow_websocket_origin(origins: List[str]) -> None:

    with StorageSupplier("sqlite") as storage, tempfile.NamedTemporaryFile("r") as tf_report:
        assert isinstance(storage, RDBStorage)
        storage_url = str(storage.engine.url)

        study_name = storage.get_study_name_from_id(storage.create_new_study())
        command = [
            "optuna",
            "dashboard",
            "--study-name",
            study_name,
            "--out",
            tf_report.name,
            "--storage",
            storage_url,
        ]
        for origin in origins:
            command.extend(["--allow-websocket-origin", origin])
        subprocess.check_call(command)

        html = tf_report.read()
        assert "<body>" in html
        assert "bokeh" in html


def test_study_optimize_command() -> None:

    with StorageSupplier("sqlite") as storage:
        assert isinstance(storage, RDBStorage)
        storage_url = str(storage.engine.url)

        study_name = storage.get_study_name_from_id(storage.create_new_study())
        command = [
            "optuna",
            "study",
            "optimize",
            "--study-name",
            study_name,
            "--n-trials",
            "10",
            __file__,
            "objective_func",
            "--storage",
            storage_url,
        ]
        subprocess.check_call(command)

        study = optuna.load_study(storage=storage_url, study_name=study_name)
        assert len(study.trials) == 10
        assert "x" in study.best_params

        # Check if a default value of study_name is stored in the storage.
        assert storage.get_study_name_from_id(study._study_id).startswith(
            DEFAULT_STUDY_NAME_PREFIX
        )


def test_study_optimize_command_inconsistent_args() -> None:

    with tempfile.NamedTemporaryFile() as tf:
        db_url = "sqlite:///{}".format(tf.name)

        # --study-name argument is missing.
        with pytest.raises(subprocess.CalledProcessError):
            subprocess.check_call(
                [
                    "optuna",
                    "study",
                    "optimize",
                    "--storage",
                    db_url,
                    "--n-trials",
                    "10",
                    __file__,
                    "objective_func",
                ]
            )


def test_empty_argv() -> None:

    command_empty = ["optuna"]
    command_empty_output = str(subprocess.check_output(command_empty))

    command_help = ["optuna", "help"]
    command_help_output = str(subprocess.check_output(command_help))

    assert command_empty_output == command_help_output


def test_check_storage_url() -> None:

    storage_in_args = "sqlite:///args.db"
    assert storage_in_args == optuna.cli._check_storage_url(storage_in_args)

    with pytest.raises(CLIUsageError):
        optuna.cli._check_storage_url(None)


def test_storage_upgrade_command() -> None:

    with StorageSupplier("sqlite") as storage:
        assert isinstance(storage, RDBStorage)
        storage_url = str(storage.engine.url)

        command = ["optuna", "storage", "upgrade"]
        with pytest.raises(CalledProcessError):
            subprocess.check_call(command)

        command.extend(["--storage", storage_url])
        subprocess.check_call(command)


@pytest.mark.parametrize(
    "direction,directions,sampler,sampler_kwargs,output_format",
    [
        (None, None, None, None, None),
        ("minimize", None, None, None, None),
        (None, "minimize maximize", None, None, None),
        (None, None, "RandomSampler", None, None),
        (None, None, "TPESampler", '{"multivariate": true}', None),
        (None, None, None, None, "json"),
        (None, None, None, None, "yaml"),
    ],
)
@pytest.mark.parametrize("flatten", (True, False))
def test_ask(
    direction: Optional[str],
    directions: Optional[str],
    sampler: Optional[str],
    sampler_kwargs: Optional[str],
    output_format: Optional[str],
    flatten: bool,
) -> None:

    study_name = "test_study"
    search_space = (
        '{"x": {"name": "UniformDistribution", "attributes": {"low": 0.0, "high": 1.0}}, '
        '"y": {"name": "CategoricalDistribution", "attributes": {"choices": ["foo"]}}}'
    )

    with tempfile.NamedTemporaryFile() as tf:
        db_url = "sqlite:///{}".format(tf.name)

        args = [
            "optuna",
            "ask",
            "--storage",
            db_url,
            "--study-name",
            study_name,
            "--search-space",
            search_space,
        ]

        if direction is not None:
            args += ["--direction", direction]
        if directions is not None:
            args += ["--directions"] + directions.split()
        if sampler is not None:
            args += ["--sampler", sampler]
        if sampler_kwargs is not None:
            args += ["--sampler-kwargs", sampler_kwargs]
        if output_format is not None:
            args += ["--format", output_format]
        if flatten:
            args.append("--flatten")

        output = str(subprocess.check_output(args).decode().strip())
        trial = _parse_output(output, output_format)

        if flatten:
            if output_format is None or output_format == "table":
                assert len(trial) == 1
                trial = trial[0]
                assert trial["number"] == "0"
                assert 0 <= float(trial["params_x"]) <= 1
                assert trial["params_y"] == "foo"
            else:
                assert trial["number"] == 0
                assert 0 <= trial["params_x"] <= 1
                assert trial["params_y"] == "foo"
        else:
            if output_format is None or output_format == "table":
                assert len(trial) == 1
                trial = trial[0]
                assert trial["number"] == "0"
                params = eval(trial["params"])
                assert len(params) == 2
                assert 0 <= params["x"] <= 1
                assert params["y"] == "foo"
            else:
                assert trial["number"] == 0
                assert 0 <= trial["params"]["x"] <= 1
                assert trial["params"]["y"] == "foo"


@pytest.mark.parametrize("output_format", ("table", "json", "yaml"))
@pytest.mark.parametrize("flatten", (True, False))
def test_ask_empty_search_space(output_format: str, flatten: bool) -> None:
    study_name = "test_study"

    with tempfile.NamedTemporaryFile() as tf:
        db_url = "sqlite:///{}".format(tf.name)

        args = [
            "optuna",
            "ask",
            "--storage",
            db_url,
            "--study-name",
            study_name,
            "--format",
            output_format,
        ]

        if flatten:
            args.append("--flatten")

        output = str(subprocess.check_output(args).decode().strip())
        trial = _parse_output(output, output_format)

        if flatten:
            if output_format == "table":
                assert len(trial) == 1
                trial = trial[0]
                assert trial["number"] == "0"
                assert "params" not in trial
            else:
                assert trial["number"] == 0
                assert "params" not in trial
        else:
            if output_format == "table":
                assert len(trial) == 1
                trial = trial[0]
                assert trial["number"] == "0"
                assert trial["params"] == "{}"
            else:
                assert trial["number"] == 0
                assert trial["params"] == {}


def test_tell() -> None:
    study_name = "test_study"

    with tempfile.NamedTemporaryFile() as tf:
        db_url = "sqlite:///{}".format(tf.name)

        output: Any = subprocess.check_output(
            [
                "optuna",
                "ask",
                "--storage",
                db_url,
                "--study-name",
                study_name,
                "--format",
                "json",
            ]
        )
        output = output.decode("utf-8")
        output = json.loads(output)
        trial_number = output["number"]

        output = subprocess.check_output(
            [
                "optuna",
                "tell",
                "--storage",
                db_url,
                "--trial-number",
                str(trial_number),
                "--values",
                "1.2",
            ]
        )

        study = optuna.load_study(storage=db_url, study_name=study_name)
        assert len(study.trials) == 1
        assert study.trials[0].state == TrialState.COMPLETE
        assert study.trials[0].values == [1.2]
