"""French named-entity recognition on CPU. Never downloads or saves document text."""

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache

from .core import DocumentError, check_cancel
from .ner_assets import MODEL_FILES, model_folder

ENTITY_KINDS = {'PER': 'Nom', 'ORG': 'Entreprise / client', 'LOC': 'Lieu'}


@dataclass(frozen=True)
class Entity:
    kind: str
    start: int
    end: int


def expand_word(text, start, end):
    def inside(char):
        return char.isalnum() or char in "-'’‑"
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    while start > 0 and inside(text[start - 1]):
        start -= 1
    while end < len(text) and inside(text[end]):
        end += 1
    return start, end


def aggregate(text, offsets, labels, scores, *, threshold=.5):
    """Aggregate before thresholding; never redact just a fragment of a predicted word."""
    groups, current = [], None
    for (start, end), label, score in zip(offsets, labels, scores):
        kind = ENTITY_KINDS.get(label.split('-')[-1])
        if start == end or kind is None:
            if current:
                groups.append(current)
                current = None
            continue
        if (current and current[0] == kind and not label.startswith('B-')
                and (start <= current[2] or text[current[2]:start].isspace())):
            current[2] = max(current[2], end)
            current[3].append(float(score))
        else:
            if current:
                groups.append(current)
            current = [kind, start, end, [float(score)]]
    if current:
        groups.append(current)
    for kind, start, end, confidences in groups:
        if sum(confidences) / len(confidences) >= threshold:
            start, end = expand_word(text, start, end)
            if end - start >= 2 and any(char.isalpha() for char in text[start:end]):
                yield Entity(kind, start, end)


def sentence_spans(text):
    """A second, local view of long pages, retaining original character positions."""
    start = 0
    for match in re.finditer(r'[.!?](?=\s|$)|\n', text):
        if match.group() == '.':
            word = re.search(r'([^\W\d_]+)\.$', text[start:match.end()])
            if word and (len(word[1]) <= 2 or word[1].casefold() in {'mme', 'mlle', 'dr', 'etc'}):
                continue
        end = match.end()
        left = start
        while left < end and text[left].isspace():
            left += 1
        if end > left:
            yield left, end
        start = end
    while start < len(text) and text[start].isspace():
        start += 1
    if start < len(text):
        yield start, len(text)


@lru_cache(maxsize=1)
def _load(folder):
    import onnxruntime as ort
    from tokenizers import Tokenizer

    ort.disable_telemetry_events()
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    options.log_severity_level = 3
    options.enable_profiling = False
    session = ort.InferenceSession(str(folder / 'model.onnx'), sess_options=options,
                                   providers=['CPUExecutionProvider'])
    tokenizer = Tokenizer.from_file(str(folder / 'tokenizer.json'))
    tokenizer.enable_truncation(max_length=512, stride=64)
    config = json.loads((folder / 'config.json').read_text(encoding='utf-8'))
    return session, tokenizer, config['id2label']


def verify_assets(folder):
    for name, (size, expected, _) in MODEL_FILES.items():
        path = folder / name
        if not path.is_file() or path.stat().st_size != size:
            raise DocumentError('Modèle de contexte local absent ou invalide. Aucun téléchargement lancé.')
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                raise DocumentError('Modèle de contexte local absent ou invalide. Aucun téléchargement lancé.')


class LocalNer:
    def __init__(self):
        folder = model_folder()
        verify_assets(folder)
        self.session, self.tokenizer, self.labels = _load(folder)

    def _predict(self, text, encoded, cancel):
        import numpy as np
        found = []
        for window in [encoded, *encoded.overflowing]:
            check_cancel(cancel)
            available = {'input_ids': window.ids, 'attention_mask': window.attention_mask,
                         'token_type_ids': window.type_ids}
            inputs = {item.name: np.array([available[item.name]], dtype=np.int64)
                      for item in self.session.get_inputs()}
            logits = self.session.run(None, inputs)[0][0]
            check_cancel(cancel)
            probabilities = np.exp(logits - logits.max(axis=-1, keepdims=True))
            probabilities /= probabilities.sum(axis=-1, keepdims=True)
            if not np.isfinite(probabilities).all():
                raise DocumentError('Reconnaissance du contexte impossible : résultats invalides.')
            indices = probabilities.argmax(axis=-1)
            labels = [self.labels[str(int(index))] for index in indices]
            scores = probabilities[np.arange(len(indices)), indices]
            found.extend(aggregate(text, window.offsets, labels, scores))
        return found

    def entities(self, text, *, cancel=None):
        check_cancel(cancel)
        if not text.strip():
            return ()
        encoded = self.tokenizer.encode(text)
        found = self._predict(text, encoded, cancel)
        if encoded.overflowing:
            # Long boilerplate can obscure a short entity in a large window.
            # Supplement that view with sentences; the temporary cache avoids
            # repeatedly inferring identical boilerplate and is discarded here.
            cache = {}
            for start, end in sentence_spans(text):
                check_cancel(cancel)
                unit = text[start:end]
                if unit == text:
                    continue
                if unit not in cache:
                    cache[unit] = self._predict(unit, self.tokenizer.encode(unit), cancel)
                found.extend(Entity(entity.kind, start + entity.start, start + entity.end)
                             for entity in cache[unit])
        # Overlapping windows can return truncated duplicates: union their spans.
        merged = []
        for entity in sorted(set(found), key=lambda e: (e.kind, e.start, e.end)):
            if merged and entity.kind == merged[-1].kind and entity.start < merged[-1].end:
                previous = merged[-1]
                merged[-1] = Entity(previous.kind, previous.start, max(previous.end, entity.end))
            else:
                merged.append(entity)
        return tuple(sorted(merged, key=lambda e: (e.start, e.end, e.kind)))
