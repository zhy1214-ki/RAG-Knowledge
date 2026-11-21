from pathlib import Path
from zipfile import ZipFile
import re
from app.core.errors import AppError


def parse(path: str, kind: str):
    try:
        if kind == "pdf":
            import pymupdf
            with pymupdf.open(path) as pdf:
                units = [(page.get_text(), {"format": "pdf", "page": n + 1}) for n, page in enumerate(pdf)]
        elif kind == "docx":
            from docx import Document
            with ZipFile(path) as archive:
                if sum(i.file_size for i in archive.infolist()) > 100 * 1024 * 1024:
                    raise ValueError()
            doc = Document(path)
            text = "\n".join([p.text for p in doc.paragraphs] + [" | ".join(c.text for c in r.cells) for t in doc.tables for r in t.rows])
            units = [(text, {"format": "docx", "section": "正文"})]
        else:
            units = [(Path(path).read_text(encoding="utf-8-sig"), {"format": kind})]
        cleaned = [(re.sub(r"[ \t]+", " ", text.replace("\x00", "")).strip(), location) for text, location in units]
        cleaned = [(text, loc) for text, loc in cleaned if text]
        if not cleaned or sum(len(t) for t, _ in cleaned) > 2_000_000:
            raise ValueError()
        return cleaned
    except Exception:
        raise AppError("PARSE_ERROR", "文件无法解析或没有可提取的文本", 422) from None


def split(units, size, overlap):
    from llama_index.core.node_parser import SentenceSplitter
    splitter = SentenceSplitter(chunk_size=size, chunk_overlap=overlap)
    return [(text, loc) for content, loc in units for text in splitter.split_text(content) if text.strip()]
