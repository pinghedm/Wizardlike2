import esper

from src.components import PlayerTag


def is_game_active() -> bool:
    """True when a run is in progress (a player entity exists).

    Used to decide between the title menu and the in-game pause menu.
    """
    return bool(esper.get_component(PlayerTag))


def step_toward(src: int, dst: int) -> int:
    """Unit step (-1, 0, or +1) along one axis, moving from `src` toward `dst`."""
    return (dst > src) - (dst < src)
