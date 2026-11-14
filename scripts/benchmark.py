"""Reproducible synthetic PDF benchmark. Requires psutil in the development environment."""

import argparse
import json
import random
import subprocess
import sys
import time
import zlib
from pathlib import Path

import psutil
from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    EncodedStreamObject,
    NameObject,
    NumberObject,
)


def fixture(path):
    writer = PdfWriter()
    pixels = EncodedStreamObject()
    pixels.update({
        NameObject('/Type'): NameObject('/XObject'),
        NameObject('/Subtype'): NameObject('/Image'),
        NameObject('/Width'): NumberObject(1000),
        NameObject('/Height'): NumberObject(1400),
        NameObject('/ColorSpace'): NameObject('/DeviceGray'),
        NameObject('/BitsPerComponent'): NumberObject(8),
        NameObject('/Filter'): NameObject('/FlateDecode'),
    })
    pixels._data = zlib.compress(random.Random(20261114).randbytes(1000 * 1400))
    ref = writer._add_object(pixels)
    for _ in range(20):
        page = writer.add_blank_page(595, 842)
        page[NameObject('/Resources')] = DictionaryObject({
            NameObject('/XObject'): DictionaryObject({NameObject('/Im'): ref}),
        })
        stream = DecodedStreamObject()
        stream.set_data(b'q 595 0 0 842 0 0 cm /Im Do Q')
        page[NameObject('/Contents')] = writer._add_object(stream)
    writer.write(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('label')
    args = parser.parse_args()
    folder = Path('tmp/benchmark')
    folder.mkdir(parents=True, exist_ok=True)
    source = folder / 'synthetic-20-pages.pdf'
    if not source.exists():
        fixture(source)
    target = folder / f'{args.label}.pdf'
    if target.exists():
        raise SystemExit('Choose a new benchmark label: outputs are never overwritten.')
    started = time.perf_counter()
    process = subprocess.Popen([sys.executable, '-m', 'partage_clair.cli', str(source),
                                '-o', str(target)], stdout=subprocess.DEVNULL)
    peak = 0
    monitor = psutil.Process(process.pid)
    while process.poll() is None:
        try:
            processes = [monitor, *monitor.children(recursive=True)]
            peak = max(peak, sum(p.memory_info().rss for p in processes if p.is_running()))
        except psutil.NoSuchProcess:
            break
        time.sleep(.02)
    code = process.wait()
    if code:
        raise SystemExit(code)
    result = dict(label=args.label, seconds=round(time.perf_counter() - started, 3),
                  peak_rss_mib=round(peak / 1024**2, 1), bytes=target.stat().st_size,
                  pages=20, dpi=150, python=sys.version.split()[0], platform=sys.platform)
    (folder / f'{args.label}.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
