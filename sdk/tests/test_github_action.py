"""The customer GitHub Action is valid and never pastes inputs into shell commands."""

from pathlib import Path

import yaml

ACTION = Path(__file__).resolve().parents[1] / "github-action" / "action.yml"


def test_action_is_a_valid_composite_action():
    action = yaml.safe_load(ACTION.read_text())
    assert action["runs"]["using"] == "composite"
    assert {"entry", "agent"} <= set(action["inputs"])
    assert all(step["shell"] == "bash" for step in action["runs"]["steps"])


def test_inputs_only_reach_the_shell_through_environment_variables():
    action = yaml.safe_load(ACTION.read_text())
    for step in action["runs"]["steps"]:
        assert "${{" not in step["run"], step["name"]
