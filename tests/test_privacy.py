"""Synthetic fixtures only. Verify removal at object, text and pixel levels."""

import json

import pytest
from PIL import Image, PngImagePlugin
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    FloatObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

from partage_clair.cli import main
from partage_clair.core import Box, Document, DocumentError


@pytest.fixture
def source_pdf(tmp_path):
    writer = PdfWriter()
    writer.add_metadata({"/Author": "PERSONAL_AUTHOR_SENTINEL", "/Title": "PRIVATE_TITLE"})
    writer.add_attachment("PRIVATE_ATTACHMENT.txt", b"ATTACHMENT_SENTINEL")
    writer.root_object[NameObject("/OpenAction")] = DictionaryObject({
        NameObject("/S"): NameObject("/JavaScript"),
        NameObject("/JS"): TextStringObject("app.alert('SCRIPT_SENTINEL')"),
    })
    for index in range(2):
        page = writer.add_blank_page(width=400, height=300)
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        })
        content = DecodedStreamObject()
        content.set_data(
            f"BT /F1 16 Tf 40 240 Td (VISIBLE PAGE {index + 1}) Tj "
            "0 -60 Td (MASK_ME_SENTINEL) Tj "
            "3 Tr 0 -60 Td (HIDDEN_TEXT_SENTINEL) Tj ET".encode("ascii")
        )
        page[NameObject("/Contents")] = writer._add_object(content)
        annotation = DictionaryObject({
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Text"),
            NameObject("/Rect"): ArrayObject([FloatObject(v) for v in (350, 20, 370, 40)]),
            NameObject("/Contents"): TextStringObject("ANNOTATION_SECRET_SENTINEL"),
        })
        page[NameObject("/Annots")] = ArrayObject([writer._add_object(annotation)])
    path = tmp_path / "private.pdf"
    writer.write(path)
    return path


def test_pdf_rebuild_removes_source_objects_and_burns_masks(source_pdf, tmp_path):
    original = source_pdf.read_bytes()
    target = tmp_path / "shared.pdf"
    assert "MASK_ME_SENTINEL" in PdfReader(source_pdf).pages[0].extract_text()
    with Document(source_pdf) as doc:
        assert doc.pages == 2
        before = doc.render(0, 72)
        assert before.crop((35, 100, 250, 130)).getextrema() != ((255, 255),) * 3
        doc.export(target, [Box(1, .05, .32, .85, .46)], dpi=72)
    assert source_pdf.read_bytes() == original
    reader = PdfReader(target)
    assert len(reader.pages) == 2
    assert reader.metadata is None
    assert reader.xmp_metadata is None
    assert not reader.attachments
    assert "/OpenAction" not in reader.root_object
    assert "/AcroForm" not in reader.root_object
    assert "/Names" not in reader.root_object
    for page in reader.pages:
        assert page.extract_text() == ""
        assert "/Annots" not in page
        assert set(page["/Resources"]) == {"/XObject"}
        assert len(page.images) == 1
    # Check decompressed pixel payloads, not only a superficial raw-byte search.
    for page in reader.pages:
        image = next(iter(page["/Resources"]["/XObject"].values())).get_object()
        for sentinel in (b"MASK_ME_SENTINEL", b"HIDDEN_TEXT_SENTINEL", b"ATTACHMENT_SENTINEL"):
            assert sentinel not in image.get_data()
    with Document(target) as doc:
        after = doc.render(0, 72)
        assert after.getpixel((100, 115)) == (0, 0, 0)
        assert after.getpixel((10, 10)) == before.getpixel((10, 10))
        second = doc.render(1, 72)
        assert second.getpixel((100, 115)) != (0, 0, 0)


def test_png_metadata_and_pixels_are_removed(tmp_path):
    path = tmp_path / "source.png"
    info = PngImagePlugin.PngInfo()
    info.add_text("Author", "PERSONAL_AUTHOR_SENTINEL")
    info.add_text("XML:com.adobe.xmp", "XMP_SECRET_SENTINEL")
    Image.new("RGB", (100, 80), "red").save(path, pnginfo=info)
    target = tmp_path / "shared.png"
    with Document(path) as doc:
        doc.export(target, [Box(1, .1, .2, .6, .7)])
    with Image.open(target) as image:
        assert not image.info
        assert not image.getexif()
        assert image.getpixel((20, 30)) == (0, 0, 0)
        assert image.getpixel((90, 70)) == (255, 0, 0)
    assert b"SENTINEL" not in target.read_bytes()


def test_jpeg_exif_orientation_is_applied_then_removed(tmp_path):
    path = tmp_path / "camera.jpg"
    exif = Image.Exif()
    exif[274] = 6
    exif[315] = "PERSONAL_AUTHOR_SENTINEL"
    Image.new("RGB", (80, 40), "blue").save(path, exif=exif)
    with Document(path) as doc:
        doc.export(tmp_path / "shared.png", [])
    with Image.open(tmp_path / "shared.png") as image:
        assert image.size == (40, 80)
        assert not image.getexif()
        assert not image.info


def test_transparent_hidden_rgb_is_not_carried_over(tmp_path):
    path = tmp_path / "transparent.png"
    Image.new("RGBA", (10, 10), (123, 45, 67, 0)).save(path)
    with Document(path) as doc:
        doc.export(tmp_path / "shared.png", [])
    with Image.open(tmp_path / "shared.png") as image:
        assert image.mode == "RGB"
        assert image.getpixel((0, 0)) == (255, 255, 255)


def test_palette_transparency_is_flattened(tmp_path):
    path = tmp_path / "palette.png"
    source = Image.new("P", (10, 10), 0)
    source.putpalette([123, 45, 67] + [0] * 765)
    source.save(path, transparency=0)
    with Document(path) as doc:
        doc.export(tmp_path / "shared.png", [])
    with Image.open(tmp_path / "shared.png") as image:
        assert image.getpixel((0, 0)) == (255, 255, 255)


@pytest.mark.parametrize("coords", [
    (1, .5, .1, .2, .8), (1, -.1, 0, .2, .3),
    (1, 0, 0, float("nan"), 1), (1, 0, 0, 1, float("inf")),
    (0, 0, 0, 1, 1), (1.5, 0, 0, 1, 1), (True, 0, 0, 1, 1),
])
def test_invalid_boxes_fail_closed(coords):
    with pytest.raises(DocumentError):
        Box(*coords)


def test_no_original_or_existing_output_is_overwritten(source_pdf, tmp_path):
    before = source_pdf.read_bytes()
    with Document(source_pdf) as doc:
        with pytest.raises(DocumentError):
            doc.export(source_pdf, [])
        target = tmp_path / "already.pdf"
        target.write_bytes(b"DO_NOT_OVERWRITE")
        with pytest.raises(DocumentError):
            doc.export(target, [])
        assert target.read_bytes() == b"DO_NOT_OVERWRITE"
    assert source_pdf.read_bytes() == before


def test_invalid_page_and_extension_produce_no_output(source_pdf, tmp_path):
    with Document(source_pdf) as doc:
        with pytest.raises(DocumentError):
            doc.export(tmp_path / "bad.pdf", [Box(3, 0, 0, 1, 1)])
        with pytest.raises(DocumentError):
            doc.export(tmp_path / "bad.jpg", [])
        with pytest.raises(DocumentError):
            doc.export(tmp_path / "bad.pdf", [], dpi=1000)
    assert not (tmp_path / "bad.pdf").exists()


def test_encrypted_pdf_is_refused(source_pdf, tmp_path):
    writer = PdfWriter(clone_from=source_pdf)
    writer.encrypt("test-only-password")
    path = tmp_path / "encrypted.pdf"
    writer.write(path)
    with pytest.raises(DocumentError, match="chiffrés"):
        Document(path)


def test_animation_is_refused(tmp_path):
    path = tmp_path / "animated.png"
    Image.new("RGB", (8, 8), "red").save(path, save_all=True,
        append_images=[Image.new("RGB", (8, 8), "blue")], duration=100, loop=0)
    with pytest.raises(DocumentError, match="animées"):
        Document(path)


def test_cropped_rotated_pdf_keeps_visual_coordinate_system(source_pdf, tmp_path):
    writer = PdfWriter(clone_from=source_pdf)
    writer.pages[0].rotate(90)
    writer.pages[0].cropbox.lower_left = (20, 10)
    writer.pages[0].cropbox.upper_right = (380, 290)
    path = tmp_path / "rotated.pdf"
    writer.write(path)
    with Document(path) as doc:
        size = doc.sizes[0]
        doc.export(tmp_path / "shared.pdf", [Box(1, 0, 0, .4, .3)], dpi=72)
    with Document(tmp_path / "shared.pdf") as doc:
        assert doc.sizes[0] == size
        assert doc.render(0, 72).getpixel((5, 5)) == (0, 0, 0)


def test_cli_and_bad_masks(source_pdf, tmp_path, capsys):
    masks = tmp_path / "masks.json"
    masks.write_text(json.dumps([dict(page=1, x0=0, y0=0, x1=1, y1=1)]))
    output = tmp_path / "share.pdf"
    assert main([str(source_pdf), "-o", str(output), "--masks", str(masks)]) == 0
    assert output.exists()
    masks.write_text('{"not": "a list"}')
    assert main([str(source_pdf), "-o", str(tmp_path / "bad.pdf"), "--masks", str(masks)]) == 1
    assert not (tmp_path / "bad.pdf").exists()
    assert "liste JSON" in capsys.readouterr().err


def test_oversized_page_fails_before_render(tmp_path):
    writer = PdfWriter()
    writer.add_blank_page(100000, 100000)
    path = tmp_path / "large.pdf"
    writer.write(path)
    with Document(path) as doc:
        with pytest.raises(DocumentError, match="trop grande"):
            doc.render(0)
        with pytest.raises(DocumentError, match="trop volumineux"):
            doc.export(tmp_path / "no.pdf", [])


def test_pdf_forms_and_xmp_are_not_carried_over(source_pdf, tmp_path):
    writer = PdfWriter(clone_from=source_pdf)
    xmp = DecodedStreamObject()
    xmp.set_data(b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><private>XML_SECRET</private></x:xmpmeta>')
    xmp[NameObject("/Type")] = NameObject("/Metadata")
    xmp[NameObject("/Subtype")] = NameObject("/XML")
    writer.root_object[NameObject("/Metadata")] = writer._add_object(xmp)
    field = DictionaryObject({
        NameObject("/FT"): NameObject("/Tx"),
        NameObject("/T"): TextStringObject("PrivateField"),
        NameObject("/V"): TextStringObject("FORM_SECRET"),
        NameObject("/Type"): NameObject("/Annot"),
        NameObject("/Subtype"): NameObject("/Widget"),
        NameObject("/Rect"): ArrayObject([NumberObject(v) for v in (10, 10, 100, 30)]),
    })
    ref = writer._add_object(field)
    writer.pages[0]["/Annots"].append(ref)
    writer.root_object[NameObject("/AcroForm")] = DictionaryObject({
        NameObject("/Fields"): ArrayObject([ref]),
    })
    path = tmp_path / "forms.pdf"
    writer.write(path)
    with Document(path) as doc:
        doc.export(tmp_path / "clean.pdf", [Box(1, 0, .8, .4, 1)])
    reader = PdfReader(tmp_path / "clean.pdf")
    assert not reader.get_fields()
    assert reader.xmp_metadata is None
    assert b"XML_SECRET" not in (tmp_path / "clean.pdf").read_bytes()
