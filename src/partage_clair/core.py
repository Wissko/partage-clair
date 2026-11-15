"""Rebuild from rendered pixels; never copy source PDF objects into an export."""

import hashlib
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
from PIL import Image, ImageDraw, ImageFont, ImageOps
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


@dataclass(frozen=True)
class OutputLabel:
    box: Box
    text: str
    method: str

    def __post_init__(self):
        if (not isinstance(self.box, Box) or self.method not in ('generalise', 'pseudonym')
                or not isinstance(self.text, str) or not 1 <= len(self.text) <= 64
                or not self.text.strip() or any(ord(c) < 32 for c in self.text)):
            raise DocumentError('Remplacement invalide : une ligne de 1 à 64 caractères est requise.')


def label_bounds(box, size):
    w, h = size
    return math.floor(box.x0 * w), math.floor(box.y0 * h), math.ceil(box.x1 * w), math.ceil(box.y1 * h)


def label_patch(size, text):
    """Only replacement pixels; clipping makes it impossible to paint outside the mask."""
    w, h = size
    for font_size in range(min(48, h - 4), 3, -1):
        font = ImageFont.load_default(size=font_size)
        left, top, right, bottom = font.getbbox(text)
        if right - left <= w - 4 and bottom - top <= h - 4:
            patch = Image.new('RGB', size, 'black')
            ImageDraw.Draw(patch).text(((w - right + left) / 2 - left,
                                       (h - bottom + top) / 2 - top), text, font=font, fill='white')
            return patch
    raise DocumentError('Zone trop petite pour un remplacement lisible. Choisissez le masquage complet.')


def cover(image: Image.Image, boxes: list[Box], labels=()) -> Image.Image:
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
    for box in [*boxes, *(label.box for label in labels)]:
        draw.rectangle((
            max(0, math.floor(box.x0 * w) - 1),
            max(0, math.floor(box.y0 * h) - 1),
            min(w - 1, math.ceil(box.x1 * w)),
            min(h - 1, math.ceil(box.y1 * h)),
        ), fill="black")
    try:
        for label in labels:
            left, top, right, bottom = label_bounds(label.box, clean.size)
            patch = label_patch((right - left, bottom - top), label.text)
            try:
                clean.paste(patch, (left, top))
            finally:
                patch.close()
    except BaseException:
        clean.close()
        raise
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
            self.source_digest = hashlib.sha256(data).hexdigest()
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

    @serialized_pdfium
    def text_layer(self, index):
        """Native glyph geometry in the same cropped/rotated space as rendering."""
        from .detection import TextLayer
        self._require_open()
        if self.kind != 'pdf' or not 0 <= index < self.pages:
            raise DocumentError('Page PDF inexistante.')
        page = self.pdf[index]
        textpage = None
        try:
            textpage = page.get_textpage()
            count = textpage.count_chars()
            if count > 100_000:
                raise DocumentError('Page trop dense pour une analyse complète.')
            w, h = self.sizes[index]
            # Four device pixels per point keep rounding below a quarter point.
            pw, ph = math.ceil(w * 4), math.ceil(h * 4)
            converter = pdfium.PdfPosConv(page, (0, 0, pw, ph, 0))
            text, boxes = [], []
            for char_index in range(count):
                code = pdfium.raw.FPDFText_GetUnicode(textpage, char_index)
                char = chr(code) if 0 < code <= 0x10ffff else ' '
                text.append(char)
                box = None
                if not char.isspace():
                    try:
                        left, bottom, right, top = textpage.get_charbox(char_index, loose=True)
                        corners = [converter.to_bitmap(x, y) for x in (left, right) for y in (bottom, top)]
                        x0 = max(0, min(p[0] for p in corners) / pw - 1 / w)
                        y0 = max(0, min(p[1] for p in corners) / ph - 1 / h)
                        x1 = min(1, max(p[0] for p in corners) / pw + 1 / w)
                        y1 = min(1, max(p[1] for p in corners) / ph + 1 / h)
                        if x0 < x1 and y0 < y1:
                            box = Box(index + 1, x0, y0, x1, y1)
                    except (ValueError, pdfium.PdfiumError):
                        pass
                boxes.append(box)
            return TextLayer(index + 1, ''.join(text), tuple(boxes), 'PDF')
        finally:
            if textpage is not None:
                textpage.close()
            page.close()

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

    @serialized_pdfium
    def has_visual_objects(self, index):
        """Flag non-text objects, including nested forms, without image recognition."""
        self._require_open()
        if self.kind != 'pdf':
            return True
        page = self.pdf[index]
        try:
            return any(obj.type != pdfium.raw.FPDF_PAGEOBJ_TEXT for obj in page.get_objects())
        finally:
            page.close()

    def export(self, target: str | Path, boxes: list[Box], dpi: int = 150, *,
               progress: Callable[[int, int], None] | None = None, cancel=None, labels=()) -> Path:
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
        if any(not isinstance(label, OutputLabel) or label.box.page > self.pages for label in labels):
            raise DocumentError('Un remplacement référence une page inexistante.')
        from .methods import overlaps
        if any(overlaps(label.box, box) for label in labels for box in boxes):
            raise DocumentError('Un remplacement chevauche un masque complet. Résolvez le plan avant export.')
        if any(overlaps(a.box, b.box) for i, a in enumerate(labels) for b in labels[i + 1:]):
            raise DocumentError('Deux remplacements se chevauchent. Résolvez le plan avant export.')
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
                    clean = cover(self.image, boxes, labels)
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
                            clean = cover(original, grouped[i + 1], [label for label in labels if label.box.page == i + 1])
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

