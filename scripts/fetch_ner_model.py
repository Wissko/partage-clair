"""Explicit installation/build download, never called by document analysis."""

import hashlib
import os
import shutil
import tempfile
import urllib.request
from pathlib import Path

from partage_clair.ner_assets import MODEL_FILES, REPOSITORY, REVISION, model_folder


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    folder = model_folder()
    folder.mkdir(parents=True, exist_ok=True)
    for name, (size, expected, remote) in MODEL_FILES.items():
        destination = folder / name
        if destination.is_file() and destination.stat().st_size == size and digest(destination) == expected:
            print(f'Already verified: {name}')
            continue
        print(f'Installing verified public asset: {name}', flush=True)
        descriptor, temporary = tempfile.mkstemp(prefix='ner-install-', dir=folder)
        temporary = Path(temporary)
        try:
            with os.fdopen(descriptor, 'wb') as output, urllib.request.urlopen(
                    f'https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{remote}', timeout=90) as source:
                while data := source.read(1024 * 1024):
                    output.write(data)
                    if output.tell() > size:
                        raise ValueError('Unexpected model size')
            if temporary.stat().st_size != size or digest(temporary) != expected:
                raise ValueError('Model integrity check failed')
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    shutil.copyfile(Path(__file__).resolve().parents[1] / 'docs' / 'NER_MODEL_LICENSE.txt',
                    folder / 'MODEL_LICENSE.txt')
    print('Context recognition ready. Document processing needs no network.')


if __name__ == '__main__':
    main()
