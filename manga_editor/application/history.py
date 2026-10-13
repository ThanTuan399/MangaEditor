from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from manga_editor.domain.models import MangaProject


@dataclass(slots=True)
class Snapshot:
    project: MangaProject
    assets: dict[str, bytes]
    label: str


class History:
    def __init__(self, limit: int = 50):
        self.limit = limit
        self.undo_stack: list[Snapshot] = []
        self.redo_stack: list[Snapshot] = []

    @staticmethod
    def capture(project: MangaProject, assets: dict[str, bytes], label: str) -> Snapshot:
        return Snapshot(deepcopy(project), dict(assets), label)

    def push_before(self, project: MangaProject, assets: dict[str, bytes], label: str) -> None:
        self.undo_stack.append(self.capture(project, assets, label))
        self.undo_stack = self.undo_stack[-self.limit :]
        self.redo_stack.clear()

    def undo(self, project: MangaProject, assets: dict[str, bytes]) -> Snapshot | None:
        if not self.undo_stack:
            return None
        previous = self.undo_stack.pop()
        self.redo_stack.append(self.capture(project, assets, previous.label))
        return previous

    def redo(self, project: MangaProject, assets: dict[str, bytes]) -> Snapshot | None:
        if not self.redo_stack:
            return None
        next_state = self.redo_stack.pop()
        self.undo_stack.append(self.capture(project, assets, next_state.label))
        return next_state
