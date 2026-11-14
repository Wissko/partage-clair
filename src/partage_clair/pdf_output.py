"""Minimal image-only PDF writer: one page in memory, no source PDF objects.

The file uses classic xref tables and lossless PNG predictor streams. The
independent pypdf reader and PDFium renderer validate the generated structure in tests.
"""

import struct
from io import BytesIO

from PIL import Image, ImageChops


class ImagePdfWriter:
    def __init__(self, stream, sizes):
        self.stream = stream
        self.sizes = sizes
        self.offsets = [0] * (3 + 3 * len(sizes))
        stream.write(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
        self.object(1, b'<< /Type /Catalog /Pages 2 0 R >>')
        kids = ' '.join(f'{3 + 3 * i} 0 R' for i in range(len(sizes)))
        self.object(2, f'<< /Type /Pages /Count {len(sizes)} /Kids [{kids}] >>'.encode())

    def begin(self, number):
        self.offsets[number] = self.stream.tell()
        self.stream.write(f'{number} 0 obj\n'.encode())

    def object(self, number, content):
        self.begin(number)
        self.stream.write(content)
        self.stream.write(b'\nendobj\n')

    def page(self, index: int, image: Image.Image):
        if image.mode != 'RGB':
            raise ValueError('PDF output requires a clean RGB image.')
        w, h = self.sizes[index]
        page_id = 3 + 3 * index
        image_id, content_id = page_id + 1, page_id + 2
        page = (
            f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w:.6f} {h:.6f}] '
            f'/Resources << /XObject << /Image {image_id} 0 R >> >> '
            f'/Contents {content_id} 0 R >>'
        )
        self.object(page_id, page.encode())
        # A truly grey page needs one byte per pixel, with exactly the same colours.
        red, green, blue = image.split()
        grey = True
        try:
            for channel in (green, blue):
                difference = ImageChops.difference(red, channel)
                try:
                    if difference.getbbox() is not None:
                        grey = False
                        break
                finally:
                    difference.close()
        finally:
            green.close()
            blue.close()
        if not grey:
            red.close()
        encoded_image = red if grey else image
        colors = 1 if grey else 3
        with BytesIO() as encoded:
            try:
                encoded_image.save(encoded, format='PNG', compress_level=3)
            finally:
                if grey:
                    red.close()
            data = encoded.getbuffer()
            try:
                # The encoder is controlled here: RGB, 8 bits, non-interlaced.
                color_type = 0 if grey else 2
                if (bytes(data[12:16]) != b'IHDR'
                        or bytes(data[24:29]) != bytes((8, color_type, 0, 0, 0))):
                    raise ValueError('Unexpected PNG encoding.')
                chunks = []
                cursor = 8
                while cursor < len(data):
                    length = struct.unpack_from('>I', data, cursor)[0]
                    if bytes(data[cursor + 4:cursor + 8]) == b'IDAT':
                        chunks.append((cursor + 8, length))
                    cursor += length + 12
                length = sum(length for _, length in chunks)
                self.begin(image_id)
                header = (
                    f'<< /Type /XObject /Subtype /Image /Width {image.width} '
                    f'/Height {image.height} /ColorSpace /Device{"Gray" if grey else "RGB"} '
                    f'/BitsPerComponent 8 /Filter /FlateDecode '
                    f'/DecodeParms << /Predictor 15 /Colors {colors} '
                    f'/BitsPerComponent 8 /Columns {image.width} >> /Length {length} >>\nstream\n'
                )
                self.stream.write(header.encode())
                for start, length in chunks:
                    self.stream.write(data[start:start + length])
                self.stream.write(b'\nendstream\nendobj\n')
            finally:
                data.release()
        commands = f'q {w:.6f} 0 0 {h:.6f} 0 0 cm /Image Do Q'.encode()
        self.object(content_id, f'<< /Length {len(commands)} >>\nstream\n'.encode()
                    + commands + b'\nendstream')

    def finish(self):
        if any(offset == 0 for offset in self.offsets[1:]):
            raise ValueError('PDF output is incomplete.')
        start = self.stream.tell()
        count = len(self.offsets)
        self.stream.write(f'xref\n0 {count}\n0000000000 65535 f \n'.encode())
        for offset in self.offsets[1:]:
            self.stream.write(f'{offset:010d} 00000 n \n'.encode())
        self.stream.write(
            f'trailer\n<< /Size {count} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode()
        )
