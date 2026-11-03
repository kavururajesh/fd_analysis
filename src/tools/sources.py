"""Source configuration (which pages to read) loaded from config/sources.<mode>.yaml."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from src.config import settings as S


@dataclass
class SourceConfig:
    id: str
    bank: str
    product: str
    status: str                       # current | proxy | default_table | stale
    kind: str                         # html | browser | pdf
    url: str
    effective: str = ""
    actions: List[Dict[str, Any]] = field(default_factory=list)      # browser steps, e.g. [{"click": "text=Show rates"}]
    layout: Optional[Dict[str, Any]] = None                          # known layout spec (None = calibrate with the agent)
    expect: Dict[str, Any] = field(default_factory=dict)             # min_rows, slabs, rate_range
    note: str = ""

    def meta(self, effective=None):
        return dict(id=self.id, bank=self.bank, product=self.product, status=self.status, effective=effective or self.effective)


def load_sources(path=None) -> List[SourceConfig]:
    path = Path(path or S.SOURCES_FILE)
    text = path.read_text(encoding="utf-8").replace("{FIXTURE_BASE}", f"http://127.0.0.1:{S.FIXTURE_PORT}")
    data = yaml.safe_load(text)["sources"]
    return [SourceConfig(**{k: v for k, v in d.items() if k in SourceConfig.__dataclass_fields__}) for d in data]
