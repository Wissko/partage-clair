"""Serial document worker. No Tk calls or callbacks are made on this thread."""

from collections import OrderedDict
from dataclasses import dataclass, replace
from pathlib import Path
from queue import Queue
from threading import Event, Thread

from .core import Document


@dataclass(frozen=True)
class DocumentInfo:
    name: str
    kind: str
    pages: int
    sizes: tuple


class DocumentWorker:
    def __init__(self):
        self.requests = Queue()
        self.results = Queue()
        self.cancel = Event()
        self.sequence = 0
        self.stopping = False
        self.thread = Thread(target=self._run, name='partage-clair-documents', daemon=True)
        self.thread.start()

    def submit(self, operation, **arguments):
        if self.stopping:
            raise RuntimeError('The worker is shutting down.')
        self.sequence += 1
        self.requests.put((self.sequence, operation, arguments))
        return self.sequence

    def stop(self):
        if not self.stopping:
            self.stopping = True
            self.cancel.set()
            self.requests.put((0, 'shutdown', {}))

    def _run(self):
        document = None
        detection_index = None
        manual_findings = set()
        analysis_mode = 'assisted'
        last_export = None
        cache = OrderedDict()

        def clear():
            for image in cache.values():
                image.close()
            cache.clear()

        def preview(page, dpi):
            key = page, dpi
            if key not in cache:
                cache[key] = document.render(page, dpi)
            cache.move_to_end(key)
            result = cache[key].copy()
            while (len(cache) > 3
                    or sum(im.width * im.height for im in cache.values()) > 8_000_000):
                _, old = cache.popitem(last=False)
                old.close()
            return result

        try:
            while True:
                request, operation, args = self.requests.get()
                if operation == 'shutdown':
                    break
                if self.stopping:
                    continue
                try:
                    if operation == 'open':
                        candidate = Document(args['path'])
                        try:
                            image = candidate.render(0, 90)
                        except Exception:
                            candidate.close()
                            raise
                        clear()
                        if document:
                            document.close()
                        document = candidate
                        detection_index = None
                        manual_findings.clear()
                        last_export = None
                        analysis_mode = 'assisted'
                        cache[(0, 90)] = image
                        info = DocumentInfo(Path(args['path']).name, document.kind,
                                            document.pages, tuple(document.sizes))
                        result = info, image.copy()
                    elif operation == 'render':
                        if document is None:
                            raise ValueError('Aucun document ouvert.')
                        result = preview(args['page'], args['dpi'])
                    elif operation == 'export':
                        if document is None:
                            raise ValueError('Aucun document ouvert.')
                        # Clear only when submitting from the UI, so an immediate cancel
                        # before this job starts cannot be lost here.
                        groups = args.pop('groups', ())
                        choices = args.pop('choices', {})
                        export_mode = args.pop('mode', analysis_mode)
                        if groups:
                            if detection_index is None:
                                raise ValueError('Analyse requise pour retrouver les noms validés.')
                            detection_index.approved_zones(groups)  # Refuse stale/unknown identifiers.
                        from .methods import redaction_plan
                        registry = {key: detection_index.findings[key] for key in groups}
                        args['boxes'], labels = redaction_plan(args['boxes'], registry, choices)
                        args['labels'] = labels
                        result = document.export(**args, cancel=self.cancel,
                            progress=lambda done, total: self.results.put(
                                (request, operation, 'progress', (done, total))))
                        from .assurance import file_digest
                        last_export = (result, tuple(args['boxes']),
                                       tuple(detection_index.findings[key] for key in groups),
                                       file_digest(result), labels, export_mode)
                    elif operation == 'audit_export':
                        from .assurance import audit_export
                        if document is None or last_export is None:
                            raise ValueError('Exportez d’abord une copie du document.')
                        path, masks, approved_findings, digest, labels, mode = last_export
                        mode = args.get('mode', analysis_mode)
                        result = audit_export(document, path, masks, approved_findings, digest,
                            labels=labels, mode=mode, cancel=self.cancel, progress=lambda done, total: self.results.put(
                                (request, operation, 'progress', (done, total))))
                    elif operation == 'scan':
                        from .detection import scan
                        if document is None:
                            raise ValueError('Aucun document ouvert.')
                        index, result = scan(document, **args, cancel=self.cancel,
                            progress=lambda done, total: self.results.put(
                                (request, operation, 'progress', (done, total))))
                        if detection_index is not None:
                            from .detection import merge_zones
                            for key, old in detection_index.findings.items():
                                current = index.findings.get(key)
                                index.findings[key] = (replace(current, zones=merge_zones(
                                    (*old.zones, *current.zones))) if current else old)
                            # Keep the complete registry for approved masks and undo/export.
                            # Never reintroduce unselected categories into a new report.
                            from .detection_options import category_for
                            visible = {f.id: f for f in result.findings}
                            for key, old in detection_index.findings.items():
                                if key in manual_findings and category_for(old.kind) in result.categories:
                                    visible.setdefault(key, index.findings[key])
                            result = replace(result, findings=tuple(index.findings[k] for k in visible))
                        detection_index = index
                        analysis_mode = result.mode
                    elif operation == 'import_references':
                        from .references import load_csv
                        result = args['source'], load_csv(args['path'], args['source'], self.cancel)
                    elif operation in ('find_name', 'find_term'):
                        if detection_index is None:
                            raise ValueError('Lancez d’abord une analyse complète du document.')
                        method = detection_index.add_name if operation == 'find_name' else detection_index.add_term
                        result = method(args['value'], cancel=self.cancel)
                        manual_findings.add(result.id)
                    else:
                        raise ValueError('Opération inconnue.')
                except Exception as error:
                    self.results.put((request, operation, 'error', error))
                else:
                    self.results.put((request, operation, 'ok', result))
        finally:
            clear()
            if document:
                document.close()
