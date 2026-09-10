"""Where a project's files live. Everything is relative to one root folder."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Project:
    root: Path

    @classmethod
    def at(cls, root: str | Path | None = None) -> "Project":
        return cls(Path(root or ".").resolve())

    @property
    def prompts_dir(self) -> Path:
        return self.root / "prompts"

    @property
    def stations_file(self) -> Path:
        return self.prompts_dir / "stations.json"

    @property
    def chunks_dir(self) -> Path:
        return self.root / "chunks"

    @property
    def manifest(self) -> Path:
        return self.chunks_dir / "manifest.json"

    @property
    def annotations_dir(self) -> Path:
        return self.root / "annotations"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    def resolve(self, path: str | Path) -> Path:
        """Relative paths are taken from the project root; absolute ones as given."""
        p = Path(path)
        return p if p.is_absolute() else self.root / p
