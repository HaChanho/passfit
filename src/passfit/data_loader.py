import copy
from functools import lru_cache
from pathlib import Path
import yaml

DATA_DIR = Path(__file__).parent / "data"

@lru_cache(maxsize=None)
def _load(name: str) -> dict:
    with open(DATA_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_passes() -> dict: return copy.deepcopy(_load("passes.yaml"))
def load_regions() -> dict: return copy.deepcopy(_load("regions.yaml"))
def load_fares() -> dict: return copy.deepcopy(_load("fares.yaml"))
