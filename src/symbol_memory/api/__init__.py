"""Public decorator and SymbolMemory facade."""

from symbol_memory.api.decorator import symbol
from symbol_memory.api.memory import SymbolMemory

__all__ = ["SymbolMemory", "symbol"]
