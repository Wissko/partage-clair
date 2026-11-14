"""Rebuild from rendered pixels; never copy source PDF objects into an export."""

import math
import warnings
import zlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageOps
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    EncodedStreamObject,
    NameObject,
    NumberObject,
)

MAX_BYTES = 100 * 1024 * 1024
MAX_PAGES = 50
MAX_PAGE_PIXELS = 24_000_000
MAX_TOTAL_PIXELS = 80_000_000
Image.MAX_IMAGE_PIXELS = MAX_PAGE_PIXELS


class DocumentError(ValueError):
    """A document cannot be handled within this application's explicit scope."""


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
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in coords):
            raise DocumentError("Les coordonnées doivent être des nombres finis.")
        if not (0 <= self.x0 < self.x1 <= 1 and 0 <= self.y0 < self.y1 <= 1):
            raise DocumentError("Rectangle invalide : attendu 0 ≤ x0 < x1 ≤ 1 et y0 < y1.")


def cover(image: Image.Image, boxes: list[Box]) -> Image.Image:
    """Burn opaque pixels into a clean RGB canvas, including a one-pixel margin."""
    clean = Image.new("RGB", image.size, "white")
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
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve(strict=True)
        self.pdf = None
        self.image = None
        self.sizes = []
        if not self.path.is_file() or self.path.stat().st_size > MAX_BYTES:
            raise DocumentError("Fichier trop volumineux (limite : 100 Mo).")
        try:
            if self.path.suffix.lower() == ".pdf":
                # Parse a snapshot, not a path that could change between readers.
                data = self.path.read_bytes()
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
                    with Image.open(self.path) as source:
                        if source.format not in {"PNG", "JPEG", "WEBP"}:
                            raise DocumentError("Le contenu ne correspond pas à une image prise en charge.")
                        if getattr(source, "n_frames", 1) != 1:
                            raise DocumentError("Les images animées ou multipages sont refusées.")
                        if source.width * source.height > MAX_PAGE_PIXELS:
                            raise DocumentError("Image trop grande (limite : 24 mégapixels).")
                        source.load()
                        oriented = ImageOps.exif_transpose(source)
                        self.image = cover(oriented, [])
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

    def render(self, index: int, dpi: int = 150) -> Image.Image:
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
            return bitmap.to_pil().convert("RGB").copy()
        finally:
            if bitmap is not None:
                bitmap.close()
            page.close()

    def export(self, target: str | Path, boxes: list[Box], dpi: int = 150) -> Path:
        target = Path(target).absolute()
        expected = ".pdf" if self.kind == "pdf" else ".png"
        if target.suffix.lower() != expected:
            raise DocumentError(f"Le fichier de sortie doit se terminer par {expected}.")
        if target.resolve() == self.path or target.exists():
            raise DocumentError("Choisissez un nouveau fichier : aucun original ne sera remplacé.")
        if any(not isinstance(box, Box) or box.page > self.pages for box in boxes):
            raise DocumentError("Un masque référence une page inexistante.")
        output = BytesIO()
        if self.kind == "image":
            image = cover(self.image, boxes)
            try:
                image.save(output, format="PNG")
            finally:
                image.close()
        else:
            if not 72 <= dpi <= 200:
                raise DocumentError("Résolution autorisée : 72 à 200 ppp.")
            total = sum(math.ceil(w * dpi / 72) * math.ceil(h * dpi / 72)
                        for w, h in self.sizes)
            if total > MAX_TOTAL_PIXELS:
                raise DocumentError("PDF trop volumineux à cette résolution. Réduisez les ppp.")
            writer = PdfWriter()
            writer.metadata = None
            for i, (w, h) in enumerate(self.sizes):
                original = self.render(i, dpi)
                try:
                    clean = cover(original, [b for b in boxes if b.page == i + 1])
                finally:
                    original.close()
                try:
                    page = writer.add_blank_page(width=w, height=h)
                    pixels = EncodedStreamObject()
                    pixels.update({
                        NameObject("/Type"): NameObject("/XObject"),
                        NameObject("/Subtype"): NameObject("/Image"),
                        NameObject("/Width"): NumberObject(clean.width),
                        NameObject("/Height"): NumberObject(clean.height),
                        NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
                        NameObject("/BitsPerComponent"): NumberObject(8),
                        NameObject("/Filter"): NameObject("/FlateDecode"),
                    })
                    pixels._data = zlib.compress(clean.tobytes())
                    # pypdf has no public generic-object registration API.
                    page[NameObject("/Resources")] = DictionaryObject({
                        NameObject("/XObject"): DictionaryObject({
                            NameObject("/Image"): writer._add_object(pixels),
                        }),
                    })
                    content = DecodedStreamObject()
                    content.set_data(f"q {w:.6f} 0 0 {h:.6f} 0 0 cm /Image Do Q".encode("ascii"))
                    page[NameObject("/Contents")] = writer._add_object(content)
                finally:
                    clean.close()
            writer.write(output)
            verify = PdfReader(BytesIO(output.getvalue()))
            if verify.metadata or verify.xmp_metadata or len(verify.pages) != self.pages:
                raise DocumentError("La vérification de l'export a échoué.")
            for page in verify.pages:
                if page.extract_text() or "/Annots" in page:
                    raise DocumentError("L'export contient des objets inattendus.")
        # Exclusive creation prevents accidental overwrite, including a race with another process.
        with target.open("xb") as stream:
            try:
                stream.write(output.getbuffer())
                stream.flush()
            except BaseException:
                stream.close()
                target.unlink(missing_ok=True)
                raise
        return target

    def close(self):
        if self.pdf is not None:
            self.pdf.close()
            self.pdf = None
        if self.image is not None:
            self.image.close()
            self.image = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

