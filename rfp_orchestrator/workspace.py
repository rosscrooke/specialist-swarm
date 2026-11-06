"""Shared workspace for one run.

Layout (per run, under outputs/<run_id>/):
    inputs/   copies of the RFP + reference docs (read-only for agents)
    work/     shared scratch area (all agents read/write)
    final/    deliverables (only the orchestrator writes here)
    events.jsonl
"""

from __future__ import annotations

import shutil
from pathlib import Path


class WorkspaceError(Exception):
    pass


class Workspace:
    AREAS = ("inputs", "work", "final")
    MAX_READ_CHARS = 200_000

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        for area in self.AREAS:
            (self.root / area).mkdir(parents=True, exist_ok=True)

    @classmethod
    def create(cls, root: Path, input_files: list[Path]) -> "Workspace":
        ws = cls(root)
        for src in input_files:
            if not src.exists():
                raise WorkspaceError(f"Input file not found: {src}")
            shutil.copy2(src, ws.root / "inputs" / src.name)
        return ws

    # -- path safety ------------------------------------------------------- #
    def _resolve(self, rel: str, allowed_areas: tuple[str, ...]) -> Path:
        rel = rel.strip().lstrip("/")
        path = (self.root / rel).resolve()
        if not path.is_relative_to(self.root):
            raise WorkspaceError(f"Path escapes the workspace: {rel}")
        area = path.relative_to(self.root).parts[0] if path != self.root else ""
        if area not in allowed_areas:
            raise WorkspaceError(f"Path must be under {' or '.join(a + '/' for a in allowed_areas)}: {rel}")
        return path

    # -- operations used by tools ------------------------------------------ #
    def list_files(self) -> str:
        lines = []
        for area in self.AREAS:
            files = sorted(p for p in (self.root / area).rglob("*") if p.is_file())
            lines.append(f"{area}/" + ("" if files else "  (empty)"))
            for p in files:
                lines.append(f"  {p.relative_to(self.root)}  ({p.stat().st_size} bytes)")
        return "\n".join(lines)

    def read_file(self, rel: str) -> str:
        path = self._resolve(rel, self.AREAS)
        if not path.is_file():
            raise WorkspaceError(f"No such file: {rel}. Use list_files to see what exists.")
        text = path.read_text(encoding="utf-8", errors="replace")
        if len(text) > self.MAX_READ_CHARS:
            raise WorkspaceError(
                f"{rel} has {len(text)} characters (limit {self.MAX_READ_CHARS}). "
                "Delegate reading it in parts to a Document Analyst."
            )
        return text

    def write_work_file(self, rel: str, content: str) -> Path:
        path = self._resolve(rel, ("work",))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def final_path(self, name: str) -> Path:
        return self.root / "final" / name
