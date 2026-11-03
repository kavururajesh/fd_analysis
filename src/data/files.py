"""File-level dataset management: staging -> validation -> atomic promotion -> clean-up of superseded files.

Layout (all local, relative to data/ so the folder can be moved to another environment unchanged):
  data/staging/<run_id>/   rates.csv, manifest.json, evidence/   <- a refresh writes here first
  data/current/            rates.csv, manifest.json, evidence/   <- the ONE live dataset the app reads
Rule: the old dataset is deleted only after the new one is written, read back, checksum-verified, validated and swapped in."""
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

from src.config import settings as S
from src.config.logging_config import get_logger
from src.domain.schema import COLUMNS
from src.domain.validation import validate_dataset
from src.utils.helpers import now_iso

log = get_logger(__name__)


class PromotionError(RuntimeError):
    pass


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DatasetFiles:
    def __init__(self, current: Path = None, staging: Path = None):
        self.current = Path(current or S.CURRENT_DIR)
        self.staging = Path(staging or S.STAGING_DIR)
        self.staging.mkdir(parents=True, exist_ok=True)

    # ---------- staging ----------
    def staging_dir(self, run_id: str) -> Path:
        return self.staging / run_id

    def stage(self, run_id: str, df: pd.DataFrame, meta: dict) -> Path:
        d = self.staging_dir(run_id)
        d.mkdir(parents=True, exist_ok=True)
        csv = d / "rates.csv"
        df[COLUMNS].to_csv(csv, index=False, encoding="utf-8")
        manifest = dict(run_id=run_id, created=now_iso(), rows=int(len(df)), sha256=_sha(csv), columns=COLUMNS, **meta)
        (d / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
        return d

    # ---------- promotion ----------
    def verify(self, run_id: str) -> pd.DataFrame:
        """Read the staged files back and check them. Raises PromotionError if anything is off."""
        d = self.staging_dir(run_id)
        try:
            manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
            csv = d / "rates.csv"
            if _sha(csv) != manifest["sha256"]:
                raise PromotionError("staged rates file changed after it was written (checksum mismatch)")
            df = pd.read_csv(csv)
        except PromotionError:
            raise
        except Exception as e:
            raise PromotionError(f"staged files are missing or unreadable: {e}")
        if len(df) != manifest["rows"] or list(df.columns) != COLUMNS:
            raise PromotionError("staged file does not match its manifest (row count / columns)")
        errors, _ = validate_dataset(df)
        if errors:
            raise PromotionError("staged data failed validation: " + "; ".join(errors))
        return df

    def promote(self, run_id: str) -> dict:
        """Swap the staged dataset in as the live one. The previous live files are removed only after the swap succeeded."""
        self.verify(run_id)
        new, old = self.staging_dir(run_id), self.current.with_name(self.current.name + ".old")
        if old.exists():                                   # leftover from a crashed earlier swap
            shutil.rmtree(old, ignore_errors=True)
        had_current = self.current.exists()
        try:
            if had_current:
                os.replace(self.current, old)              # step 1: move the live dataset aside (nothing deleted yet)
            os.replace(new, self.current)                  # step 2: new dataset becomes live
        except Exception as e:
            if had_current and old.exists() and not self.current.exists():
                os.replace(old, self.current)              # roll back: the previous data stays live
            raise PromotionError(f"could not switch to the new dataset, previous data kept: {e}")
        removed = []
        if old.exists():                                   # step 3: only now delete the superseded files
            removed = [str(p.relative_to(old)) for p in old.rglob("*") if p.is_file()]
            shutil.rmtree(old, ignore_errors=True)
        self.clean_staging(keep=())
        log.info("Dataset promoted: run %s (%d superseded files removed)", run_id, len(removed))
        return dict(run_id=run_id, removed_files=len(removed))

    def clean_staging(self, keep=()):
        """Remove staged runs that were rejected, blocked or superseded (never the ones in `keep`)."""
        for d in self.staging.iterdir():
            if d.is_dir() and d.name not in keep:
                shutil.rmtree(d, ignore_errors=True)

    # ---------- reading ----------
    def manifest(self) -> Optional[dict]:
        m = self.current / "manifest.json"
        return json.loads(m.read_text(encoding="utf-8")) if m.exists() else None

    def load_current(self) -> Tuple[Optional[str], Optional[pd.DataFrame]]:
        m = self.manifest()
        if not m or not (self.current / "rates.csv").exists():
            return None, None
        return m["run_id"], pd.read_csv(self.current / "rates.csv")

    def find_evidence(self, run_id: str, filename: str) -> Optional[Path]:
        """Evidence moves from staging to current on promotion - look in both."""
        for base in (self.staging_dir(run_id), self.current):
            p = base / "evidence" / filename
            if p.exists() and (base != self.current or (self.manifest() or {}).get("run_id") == run_id):
                return p
        return None
