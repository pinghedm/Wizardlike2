"""Grid Dijkstra pathfinding
`set_goal` builds a distance field toward a goal over the walkable grid (8-connected,
diagonals cost `diagonal`), and `get_path` returns the route from a start tile ordered goal-side
first and *excluding the goal* — the start tile is the last element, so `path[-2]`
is the next step toward the goal and `path[0]` is the tile adjacent to it. An
unreachable start, or a start already on the goal, yields an empty list.
"""

import heapq

import numpy as np
from numpy.typing import NDArray

# The eight grid neighbors; orthogonal steps cost 1, diagonal steps cost `diagonal`.
_NEIGHBORS: tuple[tuple[int, int], ...] = (
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1), (0, 1),
    (1, -1), (1, 0), (1, 1),
)  # fmt: skip


class Dijkstra:
    def __init__(self, walkable: NDArray[np.bool_], diagonal: float = 1.41) -> None:
        self.walkable = walkable
        self.diagonal = diagonal
        self.width = int(walkable.shape[0])
        self.height = int(walkable.shape[1])
        self._dist: NDArray[np.float64] | None = None
        self._goal: tuple[int, int] | None = None

    def set_goal(self, x: int, y: int, max_dist: float | None = None) -> None:
        """Compute the shortest-distance field to (x, y) over the walkable cells. When `max_dist`
        is set, the flood stops there — cells further than that stay unreachable — so a chase path
        near the goal stays cheap even on a big map (a start beyond it simply gets no path)."""
        dist = np.full((self.width, self.height), np.inf, dtype=np.float64)
        dist[x, y] = 0.0
        heap: list[tuple[float, int, int]] = [(0.0, x, y)]
        while heap:
            d, cx, cy = heapq.heappop(heap)
            if d > dist[cx, cy]:
                continue
            for dx, dy in _NEIGHBORS:
                nx, ny = cx + dx, cy + dy
                if not (0 <= nx < self.width and 0 <= ny < self.height) or not self.walkable[nx, ny]:
                    continue
                step = self.diagonal if dx and dy else 1.0
                nd = d + step
                if max_dist is not None and nd > max_dist:
                    continue
                if nd < dist[nx, ny]:
                    dist[nx, ny] = nd
                    heapq.heappush(heap, (nd, nx, ny))
        self._dist = dist
        self._goal = (x, y)

    def get_path(self, x: int, y: int) -> list[tuple[int, int]]:
        """The path from (x, y) to the goal: goal-side first, goal excluded, start last."""
        if self._dist is None or self._goal is None or not np.isfinite(self._dist[x, y]):
            return []
        walk: list[tuple[int, int]] = []
        cx, cy = x, y
        while (cx, cy) != self._goal:
            walk.append((cx, cy))
            step = self._descend(cx, cy)
            if step is None:  # gradient dead-ends before the goal (shouldn't happen when finite)
                break
            cx, cy = step
        walk.reverse()
        return walk

    def _descend(self, x: int, y: int) -> tuple[int, int] | None:
        """The neighbor with the strictly lowest distance-to-goal, or None at a local min."""
        assert self._dist is not None
        best: tuple[int, int] | None = None
        best_d = float(self._dist[x, y])
        for dx, dy in _NEIGHBORS:
            nx, ny = x + dx, y + dy
            if not (0 <= nx < self.width and 0 <= ny < self.height):
                continue
            d = float(self._dist[nx, ny])
            if d < best_d:
                best_d = d
                best = (nx, ny)
        return best
