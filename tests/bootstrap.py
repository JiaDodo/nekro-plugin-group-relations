"""Import pure plugin modules without initializing the Nekro runtime."""
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if "group_relations" not in sys.modules:
    package = types.ModuleType("group_relations")
    package.__path__ = [str(ROOT)]
    sys.modules["group_relations"] = package
