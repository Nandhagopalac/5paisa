"""Reads Rulebased_trading/entry_rules.md: ticked boxes switch rules on, 'name = value' lines set numbers."""
import re
from dataclasses import dataclass
from pathlib import Path

RULES_PATH = Path(__file__).with_name("entry_rules.md")
_TICK = re.compile(r"^\s*[-*]\s*\[( |x|X)\]\s*([a-z_0-9]+)\s*:", re.M)
_VALUE = re.compile(r"^\s*([a-z_0-9]+)\s*=\s*(\S+)\s*$", re.M)


@dataclass(frozen=True)
class Settings:
    allow_ce: bool = True
    allow_pe: bool = True
    use_top_stocks: bool = True
    use_impact: bool = True
    use_breadth: bool = True
    use_itm: bool = True
    intraday: bool = False
    buy_streak: int = 3
    top_stocks: int = 3
    breadth_up_min: int = 15
    itm_steps: int = 1
    lots: int = 1
    lot_size: int = 65
    last_entry: str = "15:15"
    max_orders: int = 3


_BOOLS = {"allow_ce", "allow_pe", "use_top_stocks", "use_impact", "use_breadth", "use_itm", "intraday"}
_INTS = {"buy_streak": 1, "top_stocks": 1, "breadth_up_min": 0, "itm_steps": 1, "lots": 1, "lot_size": 1,
         "max_orders": 1}


def parse(text):
    """Settings from the file text. A wrong line raises ValueError instead of silently using a default."""
    values = {}
    for mark, name in _TICK.findall(text):
        if name not in _BOOLS:
            raise ValueError(f"entry_rules.md: unknown rule '{name}'")
        values[name] = mark.lower() == "x"
    for name, raw in _VALUE.findall(text):
        if name in _INTS:
            try:
                number = int(raw)
            except ValueError:
                raise ValueError(f"entry_rules.md: {name} must be a whole number, got '{raw}'") from None
            if number < _INTS[name]:
                raise ValueError(f"entry_rules.md: {name} must be at least {_INTS[name]}, got {number}")
            values[name] = number
        elif name == "last_entry":
            if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", raw):
                raise ValueError(f"entry_rules.md: last_entry must look like 15:15, got '{raw}'")
            values[name] = raw
        else:
            raise ValueError(f"entry_rules.md: unknown setting '{name}'")
    return Settings(**values)


def load_settings(path=RULES_PATH):
    return parse(Path(path).read_text(encoding="utf-8"))
