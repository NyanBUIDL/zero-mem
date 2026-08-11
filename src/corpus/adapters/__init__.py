"""M10.2 adapters package."""
from .base import FormatAdapter, FormatKind
from .registry import ADAPTER_REGISTRY, select_adapter
from .txt import TxtAdapter
from .pdf import PdfAdapter

__all__ = ["FormatAdapter", "FormatKind", "ADAPTER_REGISTRY", "select_adapter", "TxtAdapter", "PdfAdapter"]
