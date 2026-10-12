from pathlib import Path


TOOL_ROOT = Path(__file__).resolve().parent
DATA_ROOT = TOOL_ROOT / "data"
LEGACY_DATA_ROOT = TOOL_ROOT.parents[1] / "local" / "light_linearity"
