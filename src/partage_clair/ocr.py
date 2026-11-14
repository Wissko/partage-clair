"""Offline OCR using packaged, hash-pinned models. No URLs or auto-downloads."""

import hashlib
from pathlib import Path

from .core import Box, DocumentError

MODELS = {
    'Det': ('PP-OCRv6_det_small.onnx', '090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f'),
    'Rec': ('PP-OCRv6_rec_small.onnx', '6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884'),
    'Cls': ('ch_ppocr_mobile_v2.0_cls_mobile.onnx', 'e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c'),
}


class LocalOcr:
    def __init__(self):
        import onnxruntime
        import rapidocr
        onnxruntime.disable_telemetry_events()
        folder = Path(rapidocr.__file__).parent / 'models'
        params = {'Global.log_level': 'critical', 'Global.max_side_len': 2400,
                  'EngineConfig.onnxruntime.intra_op_num_threads': 2,
                  'EngineConfig.onnxruntime.inter_op_num_threads': 1}
        for module, (name, expected) in MODELS.items():
            path = folder / name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise DocumentError('Modèles OCR locaux manquants ou invalides. Aucun téléchargement lancé.')
            params[f'{module}.model_path'] = str(path)
        self.engine = rapidocr.RapidOCR(params=params)

    def layer(self, image, page):
        import numpy as np

        from .detection import TextLayer
        # Pillow input lets RapidOCR perform its documented RGB -> BGR conversion.
        result = self.engine(image, return_word_box=True, text_score=.4)
        chars, boxes = [], []
        if result.txts is None:
            return TextLayer(page, '', (), 'OCR')
        w, h = image.size

        def rectangle(points):
            points = np.array(points)
            pad = max(4, (float(points[:, 1].max()) - float(points[:, 1].min())) * .12)
            x0, y0 = max(0, (float(points[:, 0].min()) - pad) / w), max(0, (float(points[:, 1].min()) - pad) / h)
            x1, y1 = min(1, (float(points[:, 0].max()) + pad) / w), min(1, (float(points[:, 1].max()) + pad) / h)
            return Box(page, x0, y0, x1, y1)

        for index, text in enumerate(result.txts):
            fallback = rectangle(result.boxes[index])
            mapping = [fallback] * len(text)
            # Word rectangles, never proportional character-width guesses. If a word
            # cannot be aligned, use the full OCR line so a partial guess cannot leak it.
            cursor = 0
            if result.word_results and index < len(result.word_results):
                for word, _score, points in result.word_results[index]:
                    found = text.find(word, cursor)
                    if found >= 0 and points is not None:
                        mapping[found:found + len(word)] = [rectangle(points)] * len(word)
                        cursor = found + len(word)
            chars.extend(text)
            boxes.extend(mapping)
            chars.append('\n')
            boxes.append(None)
        return TextLayer(page, ''.join(chars), tuple(boxes), 'OCR')
