from dataclasses import dataclass
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    model_path: Path = ROOT / "artifacts" / "model.joblib"
    database_path: Path = ROOT / "data" / "hatelens.sqlite3"
    web_path: Path = Path(__file__).resolve().parent / "web"

    @classmethod
    def from_environment(cls):
        return cls(
            model_path=Path(os.environ.get("HATELENS_MODEL", cls.model_path)),
            database_path=Path(os.environ.get("HATELENS_DATABASE", cls.database_path)),
        )
