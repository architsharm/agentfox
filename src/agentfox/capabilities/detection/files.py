"""Files, split into the layers a model reads and a person does not.

The attack this exists for is concrete and old: a résumé PDF carrying
white-on-white text telling the screening agent to rank the candidate first. A
contract whose document properties hold an instruction. An SVG whose `<title>`
says something the picture does not. The market survey files it as `a4`,
unsolved-but-buildable, and its prescription is the design here — *normalise
every file to its layers and run the same checks on each, with provenance
attached.*

Two ideas carry the module.

**A layer nobody proofreads is worse than the body.** The same sentence in the
visible text of a document is a sentence somebody wrote; in `docProps`, in an
XML comment, in alt text, it is a sentence nobody was meant to read. So layers
are tagged `visible` or `hidden`, the caller can weight them differently, and
the hidden ones are where this actually earns its place — exactly the
asymmetry `guard_reasoning` applies to the model's own words.

**A layer we cannot read is reported unread, never treated as clean.** An
image with no text layer needs OCR, which is a model we do not bundle; a PDF
needs a parser that may not be installed. Either way the honest output is "we
did not read this", which the caller can act on. Silently returning no
findings for a file nobody looked inside is the failure this whole product
argues against, and it is the easy thing to do here.

Stdlib only, by design. Office formats are zip archives of XML and SVG/HTML
are XML-ish, so most of the value needs no dependency at all. PDF is the
exception and degrades to "unread" without `pypdf`.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from io import BytesIO

#: Read directly. Anything whose bytes are already the text a model will see.
_PLAIN_SUFFIXES = {
    ".txt",
    ".md",
    ".markdown",
    ".rst",
    ".json",
    ".jsonl",
    ".csv",
    ".tsv",
    ".yaml",
    ".yml",
    ".log",
    ".ini",
    ".toml",
    ".env",
}

#: Zip-of-XML. The parts worth reading, and whether a person would see them.
#: `docProps/*` is the metadata pane nobody opens; `word/comments.xml` is a
#: review comment that may be resolved and invisible in the rendered document.
_OOXML_PARTS: tuple[tuple[str, str], ...] = (
    ("word/document.xml", "visible"),
    ("xl/sharedStrings.xml", "visible"),
    ("ppt/slides/", "visible"),
    ("word/comments.xml", "hidden"),
    ("word/footnotes.xml", "hidden"),
    ("word/endnotes.xml", "hidden"),
    ("docProps/core.xml", "hidden"),
    ("docProps/app.xml", "hidden"),
    ("docProps/custom.xml", "hidden"),
)

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t ]+")
#: XML/HTML comments. A comment is never rendered, so anything in one is by
#: definition text the reader did not see.
_COMMENT = re.compile(r"<!--(.*?)-->", re.S)


@dataclass
class Layer:
    """One readable piece of a file, and whether a person would see it."""

    name: str
    text: str
    #: "visible" | "hidden". Hidden means a reader proofreading the document
    #: would not encounter it: metadata, comments, alt text, notes.
    visibility: str = "visible"

    @property
    def hidden(self) -> bool:
        return self.visibility == "hidden"


@dataclass
class FileScan:
    filename: str
    layers: list[Layer] = field(default_factory=list)
    #: Why a part of this file was not read. Each entry is a gap the caller
    #: must surface — never an empty result dressed up as a clean one.
    unread: list[dict[str, str]] = field(default_factory=list)

    @property
    def hidden_text(self) -> str:
        return "\n".join(layer.text for layer in self.layers if layer.hidden)

    @property
    def visible_text(self) -> str:
        return "\n".join(layer.text for layer in self.layers if not layer.hidden)

    def to_json(self) -> dict[str, object]:
        return {
            "filename": self.filename,
            "layers": [
                {"name": layer.name, "visibility": layer.visibility, "chars": len(layer.text)}
                for layer in self.layers
            ],
            "unread": self.unread,
        }


def _clean(raw: str) -> str:
    return _WS.sub(" ", _TAG.sub(" ", raw)).strip()


def normalise(filename: str, data: bytes) -> FileScan:
    """Split a file into readable layers. Never raises on a bad file.

    A malformed document is the interesting case, not a reason to give up:
    truncating the zip central directory is a way to make a scanner skip a
    file while the model's own parser still reads it. So every failure becomes
    an `unread` entry rather than an exception.
    """
    scan = FileScan(filename=filename)
    suffix = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""

    if suffix in _PLAIN_SUFFIXES:
        _add_text(scan, filename, _decode(data))
        return scan
    if suffix in {".svg", ".html", ".htm", ".xml", ".xhtml"}:
        _markup(scan, _decode(data))
        return scan
    if suffix in {".docx", ".xlsx", ".pptx", ".odt"}:
        _ooxml(scan, data)
        return scan
    if suffix == ".pdf":
        _pdf(scan, data)
        return scan
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".heic"}:
        scan.unread.append(
            {
                "part": filename,
                "reason": (
                    "an image has no text layer; reading one needs OCR, which is a model "
                    "this does not bundle. Nothing in this file has been checked."
                ),
            }
        )
        return scan

    # Unknown. Try it as text — a great many things are — and say so if the
    # bytes do not look like text rather than scanning mojibake.
    text = _decode(data)
    if (
        text
        and sum(ch.isprintable() or ch.isspace() for ch in text[:2000]) > len(text[:2000]) * 0.9
    ):
        _add_text(scan, filename, text)
    else:
        scan.unread.append(
            {"part": filename, "reason": f"no reader for '{suffix or 'no extension'}'"}
        )
    return scan


def _decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _add_text(scan: FileScan, name: str, text: str, visibility: str = "visible") -> None:
    if text.strip():
        scan.layers.append(Layer(name=name, text=text, visibility=visibility))


def _markup(scan: FileScan, raw: str) -> None:
    """XML-ish: the rendered text, plus the parts that never render."""
    comments = _COMMENT.findall(raw)
    body = _COMMENT.sub(" ", raw)
    _add_text(scan, "text", _clean(body))
    for index, comment in enumerate(comments):
        _add_text(scan, f"comment[{index}]", _clean(comment), "hidden")

    # Attributes a screen reader speaks and an eye never reads. `title` and
    # `alt` are where an instruction hides in plain sight.
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return
    for element in root.iter():
        for attribute in ("alt", "title", "aria-label", "content"):
            value = element.get(attribute)
            if value and value.strip():
                _add_text(scan, f"@{attribute}", value, "hidden")
        tag = element.tag.rsplit("}", 1)[-1].lower()
        if tag in {"title", "desc", "metadata"} and (element.text or "").strip():
            _add_text(scan, f"<{tag}>", element.text or "", "hidden")


def _ooxml(scan: FileScan, data: bytes) -> None:
    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except (zipfile.BadZipFile, OSError) as exc:
        scan.unread.append({"part": "archive", "reason": f"not a readable archive: {exc}"})
        return

    names = archive.namelist()
    matched: set[str] = set()
    for prefix, visibility in _OOXML_PARTS:
        for name in names:
            if not name.startswith(prefix):
                continue
            matched.add(name)
            try:
                raw = archive.read(name).decode("utf-8", errors="replace")
            except (KeyError, OSError) as exc:
                scan.unread.append({"part": name, "reason": str(exc)})
                continue
            _add_text(scan, name, _clean(raw), visibility)

    # An OOXML part nobody claimed may still be read by the consuming
    # application. Reporting it is cheaper than pretending the list above is
    # exhaustive, and the list above is not.
    unclaimed = [
        n for n in names if n.endswith(".xml") and n not in matched and not n.startswith("_rels")
    ]
    if unclaimed:
        scan.unread.append(
            {
                "part": ", ".join(sorted(unclaimed)[:6]),
                "reason": (
                    f"{len(unclaimed)} XML part(s) in this archive were not read; the "
                    "reader covers the parts a document puts text in, not every part a "
                    "consumer might"
                ),
            }
        )


def _pdf(scan: FileScan, data: bytes) -> None:
    try:
        from pypdf import PdfReader
    except ImportError:
        scan.unread.append(
            {
                "part": "pdf",
                "reason": (
                    "PDF text extraction needs `pypdf`, which is not installed. Nothing "
                    "in this file has been checked — `pip install pypdf`."
                ),
            }
        )
        return

    try:
        reader = PdfReader(BytesIO(data))
    except Exception as exc:  # pragma: no cover - depends on the file
        scan.unread.append({"part": "pdf", "reason": f"could not be parsed: {exc}"})
        return

    for index, page in enumerate(reader.pages):
        try:
            _add_text(scan, f"page[{index}]", page.extract_text() or "")
        except Exception as exc:  # pragma: no cover
            scan.unread.append({"part": f"page[{index}]", "reason": str(exc)})

    metadata = getattr(reader, "metadata", None) or {}
    for key, value in dict(metadata).items():
        if isinstance(value, str) and value.strip():
            # `/Subject` and `/Keywords` are free text nobody opens the
            # properties pane to read, and they travel with the document.
            _add_text(scan, f"metadata{key}", value, "hidden")

    if not scan.layers and not scan.unread:
        scan.unread.append(
            {
                "part": "pdf",
                "reason": (
                    "the PDF has no extractable text layer — it is probably scanned "
                    "images, which would need OCR. Nothing has been checked."
                ),
            }
        )
