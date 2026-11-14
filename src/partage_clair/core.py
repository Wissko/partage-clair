"""Rebuild from rendered pixels; never copy source PDF objects into an export."""

import math
import os
import tempfile
import warnings
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from io import BytesIO
from pathlib import Path
from threading import RLock

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageOps
from pypdf import PdfReader

from .pdf_output import ImagePdfWriter

MAX_BYTES = 100 * 1024 * 1024
MAX_PAGES = 50
MAX_PAGE_PIXELS = 24_000_000
MAX_TOTAL_PIXELS = 200_000_000
Image.MAX_IMAGE_PIXELS = MAX_PAGE_PIXELS
_PDFIUM_LOCK = RLock()


def serialized_pdfium(function):
    """PDFium must not run simultaneously, even with different documents."""
    @wraps(function)
    def call(*args, **kwargs):
        with _PDFIUM_LOCK:
            return function(*args, **kwargs)
    return call


class DocumentError(ValueError):
    """A document cannot be handled within this application's explicit scope."""


class ExportCancelled(DocumentError):
    """The operation stopped without publishing a completed file."""


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise ExportCancelled("Export annulé. Aucune copie finale n'a été créée.")


@dataclass(frozen=True)
class Box:
    """A black rectangle: 1-based page, normalized top-left coordinates [0, 1]."""

    page: int
    x0: float
    y0: float
    x1: float
    y1: float

    def __post_init__(self):
        if not isinstance(self.page, int) or isinstance(self.page, bool) or self.page < 1:
            raise DocumentError("Le numéro de page doit être un entier supérieur à zéro.")
        coords = (self.x0, self.y0, self.x1, self.y1)
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                   and math.isfinite(v) for v in coords):
            raise DocumentError("Les coordonnées doivent être des nombres finis.")
        if not (0 <= self.x0 < self.x1 <= 1 and 0 <= self.y0 < self.y1 <= 1):
            raise DocumentError("Rectangle invalide : attendu 0 ≤ x0 < x1 ≤ 1 et y0 < y1.")


def cover(image: Image.Image, boxes: list[Box]) -> Image.Image:
    """Burn opaque pixels into a clean RGB canvas, including a one-pixel margin."""
    clean = Image.new("RGB", image.size, "white")
    if image.mode == 'RGB':
        clean.paste(image)
    else:
        rgba = image.convert("RGBA")
        try:
            clean.paste(rgba, mask=rgba.getchannel("A"))
        finally:
            rgba.close()
    draw = ImageDraw.Draw(clean)
    w, h = clean.size
    for box in boxes:
        draw.rectangle((
            max(0, math.floor(box.x0 * w) - 1),
            max(0, math.floor(box.y0 * h) - 1),
            min(w - 1, math.ceil(box.x1 * w)),
            min(h - 1, math.ceil(box.y1 * h)),
        ), fill="black")
    return clean


class Document:
    @serialized_pdfium
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve(strict=True)
        self.pdf = None
        self.image = None
        self.sizes = []
        self._closed = False
        if not self.path.is_file() or self.path.stat().st_size > MAX_BYTES:
            raise DocumentError("Fichier trop volumineux (limite : 100 Mo).")
        try:
            with self.path.open('rb') as stream:
                data = stream.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise DocumentError("Fichier trop volumineux (limite : 100 Mo).")
            if self.path.suffix.lower() == ".pdf":
                # Parse a snapshot, not a path that could change between readers.
                reader = PdfReader(BytesIO(data))
                if reader.is_encrypted:
                    raise DocumentError("Les PDF chiffrés ne sont pas pris en charge.")
                self.pdf = pdfium.PdfDocument(data)
                if not 1 <= len(self.pdf) <= MAX_PAGES:
                    raise DocumentError("Le PDF doit contenir entre 1 et 50 pages.")
                self.pdf.init_forms()
                for i in range(len(self.pdf)):
                    page = self.pdf[i]
                    try:
                        size = page.get_size()
                        if not all(math.isfinite(v) and v > 0 for v in size):
                            raise DocumentError("Dimensions de page invalides.")
                        self.sizes.append(size)
                    finally:
                        page.close()
                self.kind = "pdf"
            elif self.path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(BytesIO(data)) as source:
                        if source.format not in {"PNG", "JPEG", "WEBP"}:
                            raise DocumentError("Le contenu ne correspond pas à une image prise en charge.")
                        if getattr(source, "n_frames", 1) != 1:
                            raise DocumentError("Les images animées ou multipages sont refusées.")
                        if source.width * source.height > MAX_PAGE_PIXELS:
                            raise DocumentError("Image trop grande (limite : 24 mégapixels).")
                        source.load()
                        oriented = ImageOps.exif_transpose(source)
                        try:
                            self.image = cover(oriented, [])
                        finally:
                            oriented.close()
                self.sizes = [self.image.size]
                self.kind = "image"
            else:
                raise DocumentError("Formats acceptés : PDF, PNG, JPEG et WebP statique.")
        except Exception:
            self.close()
            raise

    @property
    def pages(self) -> int:
        return len(self.sizes)

    @serialized_pdfium
    def render(self, index: int, dpi: int = 150) -> Image.Image:
        self._require_open()
        if not 0 <= index < self.pages:
            raise DocumentError("Page inexistante.")
        if self.kind == "image":
            return self.image.copy()
        if not 72 <= dpi <= 200:
            raise DocumentError("Résolution autorisée : 72 à 200 ppp.")
        w, h = self.sizes[index]
        if math.ceil(w * dpi / 72) * math.ceil(h * dpi / 72) > MAX_PAGE_PIXELS:
            raise DocumentError("Page trop grande à cette résolution. Essayez 72 ppp.")
        page = self.pdf[index]
        bitmap = None
        try:
            bitmap = page.render(scale=dpi / 72, draw_annots=True)
            return bitmap.to_pil().convert("RGB")
        finally:
            if bitmap is not None:
                bitmap.close()
            page.close()

    def _require_open(self):
        if self._closed:
            raise DocumentError("Ce document est fermé. Ouvrez-le à nouveau.")

    def estimate(self, dpi: int = 150) -> int:
        """Validate an export before creating a temporary file."""
        self._require_open()
        if not isinstance(dpi, int) or isinstance(dpi, bool) or not 72 <= dpi <= 200:
            raise DocumentError("Résolution autorisée : un entier de 72 à 200 ppp.")
        if self.kind == 'image':
            return self.image.width * self.image.height
        pixels = [math.ceil(w * dpi / 72) * math.ceil(h * dpi / 72) for w, h in self.sizes]
        if sum(pixels) > MAX_TOTAL_PIXELS:
            raise DocumentError("PDF trop volumineux à cette résolution. Réduisez les ppp.")
        if max(pixels) > MAX_PAGE_PIXELS:
            raise DocumentError("Page trop grande à cette résolution. Réduisez les ppp.")
        return sum(pixels)

    def export(self, target: str | Path, boxes: list[Box], dpi: int = 150, *,
               progress: Callable[[int, int], None] | None = None, cancel=None) -> Path:
        self._require_open()
        self.estimate(dpi)
        check_cancel(cancel)
        target = Path(target).absolute()
        expected = ".pdf" if self.kind == "pdf" else ".png"
        if target.suffix.lower() != expected:
            raise DocumentError(f"Le fichier de sortie doit se terminer par {expected}.")
        if target.resolve() == self.path or target.exists():
            raise DocumentError("Choisissez un nouveau fichier : aucun original ne sera remplacé.")
        if any(not isinstance(box, Box) or box.page > self.pages for box in boxes):
            raise DocumentError("Un masque référence une page inexistante.")
        grouped = defaultdict(list)
        for box in boxes:
            grouped[box.page].append(box)
        if progress:
            progress(0, self.pages)
        # Only already-masked pixels are written here. Originals are never staged on disk.
        descriptor, filename = tempfile.mkstemp(prefix='.partage-clair-', suffix='.tmp',
                                               dir=target.parent)
        temporary = Path(filename)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                if self.kind == 'image':
                    clean = cover(self.image, boxes)
                    try:
                        clean.save(stream, format='PNG', compress_level=3)
                    finally:
                        clean.close()
                    if progress:
                        progress(1, 1)
                else:
                    writer = ImagePdfWriter(stream, self.sizes)
                    for i in range(self.pages):
                        check_cancel(cancel)
                        original = self.render(i, dpi)
                        try:
                            clean = cover(original, grouped[i + 1])
                        finally:
                            original.close()
                        try:
                            writer.page(i, clean)
                        finally:
                            clean.close()
                        if progress:
                            progress(i + 1, self.pages)
                    writer.finish()
                stream.flush()
                os.fsync(stream.fileno())
            check_cancel(cancel)
            self._verify(temporary)
            check_cancel(cancel)
            self._publish(temporary, target, cancel)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def _verify(self, temporary):
        if self.kind == 'image':
            with Image.open(temporary) as output:
                if output.info or output.mode != 'RGB':
                    raise DocumentError("La vérification de l'image exportée a échoué.")
                output.verify()
            return
        with temporary.open('rb') as stream:
            verify = PdfReader(stream)
            if (verify.metadata or verify.xmp_metadata or len(verify.pages) != self.pages
                    or set(verify.root_object) != {'/Type', '/Pages'}):
                raise DocumentError("La vérification de l'export a échoué.")
            for page in verify.pages:
                if (page.extract_text() or '/Annots' in page
                        or set(page['/Resources']) != {'/XObject'}
                        or len(page['/Resources']['/XObject']) != 1):
                    raise DocumentError("L'export contient des objets inattendus.")

    @staticmethod
    def _publish(temporary, target, cancel):
        try:
            # Atomic and exclusive on NTFS, APFS and normal Unix file systems.
            os.link(temporary, target)
        except FileExistsError as error:
            raise DocumentError("Le fichier existe déjà : choisissez un nouveau nom.") from error
        except OSError:
            # FAT/exFAT and some shares do not support links. Exclusive copying keeps
            # the no-overwrite guarantee. Partial copies are removed on handled errors.
            with target.open('xb') as output:
                try:
                    with temporary.open('rb') as source:
                        while data := source.read(1024 * 1024):
                            check_cancel(cancel)
                            output.write(data)
                    output.flush()
                    os.fsync(output.fileno())
                except BaseException:
                    output.close()
                    target.unlink(missing_ok=True)
                    raise

    @serialized_pdfium
    def close(self):
        if self.pdf is not None:
            self.pdf.close()
            self.pdf = None
        if self.image is not None:
            self.image.close()
            self.image = None
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

