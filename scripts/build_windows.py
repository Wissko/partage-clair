"""Build and smoke-test a Windows portable ZIP with dependency license notices."""

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from importlib.metadata import distribution
from pathlib import Path

from packaging.requirements import Requirement

from partage_clair import __version__

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.platform != 'win32':
        raise SystemExit('Build this distribution on Windows.')
    from partage_clair.ner import verify_assets
    from partage_clair.ner_assets import MODEL_FILES, model_folder
    verify_assets(model_folder())  # Refuse to produce a portable without the verified model.
    notices = ROOT / 'build' / 'licenses'
    notices.mkdir(parents=True, exist_ok=True)
    pending = {'Pillow', 'pypdf', 'pypdfium2', 'pyinstaller', 'rapidocr', 'onnxruntime', 'tokenizers'}
    visited = set()
    while pending:
        name = pending.pop()
        normalized = name.casefold().replace('_', '-')
        if normalized in visited:
            continue
        visited.add(normalized)
        dist = distribution(name)
        for dependency in dist.requires or ():
            requirement = Requirement(dependency)
            if requirement.marker is None or requirement.marker.evaluate():
                pending.add(requirement.name)
        for entry in dist.files or []:
            if any(word in entry.name.lower() for word in ('license', 'licence', 'copying', 'notice')):
                relative = Path(*[part for part in entry.parts if part not in ('.', '..')])
                target = notices / name / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(dist.locate_file(entry), target)
    shutil.copyfile(Path(sys.base_prefix) / 'LICENSE.txt', notices / 'Python-LICENSE.txt')
    shutil.copyfile(ROOT / 'docs' / 'NER_MODEL_LICENSE.txt', notices / 'NER-MODEL-LICENSE.txt')
    for entry in (Path(sys.base_prefix) / 'tcl').rglob('license.terms'):
        relative = entry.relative_to(Path(sys.base_prefix) / 'tcl')
        target = notices / 'Tcl-Tk' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(entry, target)
    (notices / 'README.txt').write_text(
        'Partage Clair includes Python, Tcl/Tk, Pillow, pypdf, pypdfium2, PDFium,\n'
        'RapidOCR, ONNX Runtime and their dependencies. OCR model weights are\n'
        'copyright Baidu and/or applicable PaddleOCR rights holders, Apache-2.0.\n'
        'Model attribution and exact hashes are in the RapidOCR MODEL_LICENSES notice.\n'
        'French NERmemberta weights and tokenizer are included under MIT; author and\n'
        'ONNX conversion attribution are in NER-MODEL-LICENSE.txt.\n'
        'The respective authors retain their rights. License texts and third-party\n'
        'PDFium notices are reproduced in this folder. PyInstaller is distributed\n'
        'with its bootloader exception; its license is included.\n', encoding='utf-8')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--noupx',
        '--onefile', '--windowed', '--name', 'PartageClair', '--paths', 'src',
        '--workpath', 'build/pyinstaller', '--specpath', 'build', '--distpath', 'dist',
        '--collect-all', 'pypdfium2_raw', '--collect-all', 'rapidocr',
        '--hidden-import', 'rapidocr.inference_engine.onnxruntime.main',
        '--copy-metadata', 'pypdfium2',
        '--copy-metadata', 'pypdf', '--copy-metadata', 'Pillow',
        '--collect-all', 'tokenizers',
        '--exclude-module', 'onnxruntime.quantization', '--exclude-module', 'onnx',
        '--add-data', f'{notices};licenses', 'packaging/desktop_entry.py'], cwd=ROOT, check=True)
    exe = ROOT / 'dist' / 'PartageClair.exe'
    # Keep the context weights beside the executable: do not unpack 443 MB at every launch.
    portable_models = ROOT / 'dist' / 'models' / 'ner'
    portable_models.mkdir(parents=True, exist_ok=True)
    for name in (*MODEL_FILES, 'MODEL_LICENSE.txt'):
        shutil.copyfile(model_folder() / name, portable_models / name)
    with tempfile.TemporaryDirectory(prefix='partage-clair-buildcheck-') as folder:
        report = Path(folder) / 'selfcheck.json'
        # A frozen executable loads its own Python, Tk and decoder DLLs.
        subprocess.run([str(exe), '--self-test', str(report)], cwd=folder, check=True, timeout=180)
        result = json.loads(report.read_text(encoding='utf-8'))
        if not result['success'] or result['version'] != __version__:
            raise SystemExit(f'Frozen self-check failed: {result}')
    destination = ROOT / 'dist' / f'PartageClair-{__version__}-windows-x64.zip'
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.write(exe, 'PartageClair.exe')
        archive.write(ROOT / 'LICENSE', 'LICENSE')
        archive.write(ROOT / 'packaging' / 'LISEZ-MOI.txt', 'LISEZ-MOI.txt')
        for name in ('liste-clients.csv', 'liste-salaries.csv'):
            archive.write(ROOT / 'examples' / name, 'exemples/' + name)
        for name in (*MODEL_FILES, 'MODEL_LICENSE.txt'):
            archive.write(portable_models / name, 'models/ner/' + name)
        for entry in notices.rglob('*'):
            if entry.is_file():
                archive.write(entry, 'licenses/' + entry.relative_to(notices).as_posix())
    with destination.open('rb') as stream:
        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
    destination.with_suffix('.zip.sha256').write_text(f'{checksum}  {destination.name}\n', encoding='ascii')
    print(json.dumps({'zip': str(destination), 'sha256': checksum, 'selfcheck': result}, indent=2))


if __name__ == '__main__':
    main()
