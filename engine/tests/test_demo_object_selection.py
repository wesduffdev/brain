"""Behaviors: the demo can put the being alone in a room with ONE chosen object
(default the hot lamp) so a user can quickly watch how the being treats any
single object — `make demo OBJ=ball`.

The selection capability lives on ConfigService, which owns the room and the
object catalog; the demo is a thin caller. Everything is asserted through public
interfaces: `ConfigService.room()` / `resolve_object()` / `with_room_contents()`,
`Simulation.state()`/`tick()`/`interactions()`, and `app.demo.main()`.
"""
from __future__ import annotations

import os

import pytest

from app import demo
from app.config_service import ConfigService
from app.simulation import Simulation

_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")


def _config() -> ConfigService:
    return ConfigService.from_files(_CONFIG_ROOT)


# --- ConfigService.with_room_contents: restrict the room to chosen objects ---

def test_focusing_the_room_on_one_object_leaves_only_that_object_in_it():
    focused = _config().with_room_contents(["obj_red_ball"])
    assert focused.room().contains == ("obj_red_ball",)


def test_a_being_alone_with_an_object_only_ever_interacts_with_that_object():
    sim = Simulation(_config().with_room_contents(["obj_red_ball"]))

    for _ in range(30):
        sim.tick()

    perceived = [o["objectId"] for o in sim.state()["perceived"]["objects"]]
    assert perceived == ["obj_red_ball"]
    assert sim.interactions()  # it did act
    assert {e["objectId"] for e in sim.interactions()} == {"obj_red_ball"}


def test_focusing_on_an_unknown_object_is_rejected():
    with pytest.raises(ValueError):
        _config().with_room_contents(["obj_does_not_exist"])


# --- ConfigService.resolve_object: friendly name -> catalog id ---

@pytest.mark.parametrize(
    "selector,expected",
    [
        ("ball", "obj_red_ball"),
        ("red_ball", "obj_red_ball"),
        ("obj_red_ball", "obj_red_ball"),
        ("Red Ball", "obj_red_ball"),
        ("lamp", "obj_hot_lamp"),
        ("blanket", "obj_soft_blanket"),
        ("block", "obj_wooden_block"),
    ],
)
def test_an_object_resolves_from_a_friendly_name(selector, expected):
    assert _config().resolve_object(selector) == expected


def test_an_unknown_selector_is_rejected_and_names_valid_choices():
    with pytest.raises(ValueError) as excinfo:
        _config().resolve_object("teapot")
    assert "ball" in str(excinfo.value).lower()  # the error lists real choices


def test_an_ambiguous_selector_is_rejected_rather_than_guessed():
    # 'o' appears in several object names -> refuse rather than pick one.
    with pytest.raises(ValueError):
        _config().resolve_object("o")


# --- the demo harness runs the being alone with the chosen (or default) object -

def test_the_demo_runs_the_being_alone_with_a_named_object(capsys):
    demo.main(["5", "ball"])

    out = capsys.readouterr().out
    assert "one object" in out
    assert "Red Ball" in out


def test_the_demo_defaults_to_the_hot_lamp_and_the_being_can_be_hurt_by_it(capsys):
    # The hot lamp is no longer hard-blocked (ADR 0013/0014): the being reaches
    # out, touches it, and is hurt — a recorded `causes_pain` outcome.
    demo.main(["5"])

    out = capsys.readouterr().out
    assert "Hot Lamp" in out
    assert "harmful contact" in out
    assert "causes_pain" in out
