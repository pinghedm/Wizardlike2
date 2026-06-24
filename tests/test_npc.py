import esper
import pytest
import tcod.event

from src.components import NPC, InputAction, Modal, Position
from src.ecs_helpers import adjacent_component
from src.input_handlers import handle_modal_input
from src.states import DisplayMode
from tests.headless_runner import HeadlessRunner


def test_adjacent_npc_returns_the_neighbor_and_none_when_distant():
    runner = HeadlessRunner()
    px, py = runner.player_pos
    far = esper.create_entity(Position(px + 5, py), NPC(name='Hermit', dialogue=['...']))
    assert adjacent_component(Position(px, py), NPC) is None

    esper.delete_entity(far, immediate=True)
    esper.create_entity(Position(px + 1, py), NPC(name='Old Wizard', dialogue=['Hello']))
    npc = adjacent_component(Position(px, py), NPC)
    assert npc is not None and npc.name == 'Old Wizard'


def test_confirm_next_to_an_npc_opens_a_dialogue_modal():
    runner = HeadlessRunner()
    px, py = runner.player_pos
    pages = ['Welcome, apprentice.', 'Beware the depths.']
    esper.create_entity(Position(px + 1, py), NPC(name='Old Wizard', dialogue=pages))

    runner.simulate_key(tcod.event.KeySym.RETURN)

    modals = esper.get_component(Modal)
    assert len(modals) == 1
    _ent, modal = modals[0]
    assert modal.title == 'Old Wizard'
    assert modal.pages == pages
    assert modal.page == 0
    assert runner.display_mode == DisplayMode.EXPLORING


@pytest.mark.parametrize('page_count', [1, 3])
def test_confirm_pages_through_dialogue_then_closes(page_count):
    runner = HeadlessRunner()
    pages = [f'page {i}' for i in range(page_count)]
    ent = esper.create_entity(Modal(pages=pages))

    # Each Confirm before the last page advances without closing.
    for expected_next in range(1, page_count):
        handle_modal_input(InputAction.CONFIRM)
        assert esper.component_for_entity(ent, Modal).page == expected_next

    # Confirm on the final page dismisses the modal (delete is deferred to the next tick).
    handle_modal_input(InputAction.CONFIRM)
    runner.tick()
    assert not esper.get_component(Modal)


def test_modal_on_close_runs_only_after_the_last_page():
    HeadlessRunner()
    closed: list[bool] = []
    esper.create_entity(Modal(pages=['one', 'two'], on_close=lambda: closed.append(True)))

    handle_modal_input(InputAction.CONFIRM)
    assert closed == []  # still on page two

    handle_modal_input(InputAction.CONFIRM)
    assert closed == [True]
