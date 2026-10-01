"""M10.2 adapters package (T4: md, csv/tsv, json/jsonl chat logs, docx, xlsx, pptx, image/OCR)."""
from .base import FormatAdapter, FormatKind
from .registry import ADAPTER_REGISTRY, select_adapter
from .txt import TxtAdapter
from .pdf import PdfAdapter
from .markdown import MarkdownAdapter
from .tabular import CsvAdapter
from .json_chat import JsonAdapter
from .docx import DocxAdapter
from .xlsx import XlsxAdapter
from .pptx import PptxAdapter
from .image import ImageAdapter

__all__ = [
    "FormatAdapter", "FormatKind", "ADAPTER_REGISTRY", "select_adapter",
    "TxtAdapter", "PdfAdapter", "MarkdownAdapter", "CsvAdapter", "JsonAdapter",
    "DocxAdapter", "XlsxAdapter", "PptxAdapter", "ImageAdapter",
]
