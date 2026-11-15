"""Pinned public assets. Only the explicit installation script downloads them."""

import sys
from pathlib import Path

REVISION = 'a1c0156aa005269dcb875f45a4b59663cebd2bf1'
REPOSITORY = 'julienkilo/onnx_NERmemberta-4entities'
MODEL_FILES = {
    'model.onnx': (443391054, '77454f580606e61c7e2aca67f220030547d6c7fc033318d156cddc5c091bd82f', 'onnx/model.onnx'),
    'tokenizer.json': (755933, '9a73847b1816a4ba8f99a11e602fc983d717b3cc393696239b2a57d32adbedca', 'tokenizer.json'),
    'config.json': (1180, 'a8d4eaade4e37245507b2f6ce955b794c7bd0c5a154a05223914f6a8f19a8a27', 'config.json'),
}


def model_folder():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent / 'models' / 'ner'
    return Path(__file__).parent / 'models' / 'ner'
