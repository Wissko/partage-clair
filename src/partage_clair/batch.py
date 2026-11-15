"""In-memory, bounded batches. Approval binds masks to an exact source snapshot."""

from dataclasses import dataclass, replace
from pathlib import Path
from queue import Queue
from threading import Event, Thread
from uuid import uuid4

from .assurance import audit_export, file_digest
from .core import Box, Document, DocumentError, ExportCancelled, check_cancel
from .detection import ScanReport, merge_zones, scan
from .detection_options import DetectionOptions
from .references import load_csv

MAX_FILES = 100


@dataclass(frozen=True)
class BatchJob:
    id: str
    path: Path
    digest: str = ''
    kind: str = ''
    pages: int = 0
    report: ScanReport | None = None
    approved: frozenset[str] = frozenset()
    boxes: tuple[Box, ...] = ()
    reviewed: frozenset[int] = frozenset()
    revision: int = 0
    approval_revision: int = -1
    output: Path | None = None
    status: str = 'À analyser'

    @property
    def ready(self):
        return self.report is not None and self.approval_revision == self.revision

    @property
    def masks(self):
        return merge_zones((*self.boxes, *(z for f in self.report.findings if f.id in self.approved for z in f.zones)))


class BatchSession:
    def __init__(self):
        self.jobs = {}
        self.options = DetectionOptions(mode='rules')

    def clear(self):
        self.jobs = {}
        return ()

    def analyze(self, paths, options, *, cancel=None, progress=None):
        paths = tuple(dict.fromkeys(Path(p).resolve() for p in paths))
        if not 1 <= len(paths) <= MAX_FILES:
            raise DocumentError('Choisissez de 1 à 100 documents.')
        self.options = options
        self.jobs = {str(i): BatchJob(str(i), path) for i, path in enumerate(paths, 1)}
        for number, job in enumerate(tuple(self.jobs.values()), 1):
            check_cancel(cancel)
            try:
                with Document(job.path) as doc:
                    _, report = scan(doc, options=options, cancel=cancel)
                    job = replace(job, digest=doc.source_digest, kind=doc.kind, pages=doc.pages,
                                  report=report, status='À vérifier')
            except ExportCancelled:
                raise
            except DocumentError as error:
                job = replace(job, status='Refusé : ' + str(error)[:180])
            except Exception:
                # Never store parser exceptions containing recognized content in a batch log.
                job = replace(job, status='Erreur de lecture — document refusé')
            self.jobs[job.id] = job
            if progress:
                progress(number, len(paths), job)
        return tuple(self.jobs.values())

    def _get(self, key):
        job = self.jobs[key]
        if job.report is None:
            raise DocumentError('Ce document doit être analysé avant vérification.')
        return job

    def _change(self, job, **changes):
        job = replace(job, revision=job.revision + 1, approval_revision=-1, output=None,
                      status='À vérifier', **changes)
        self.jobs[job.id] = job
        return job

    def candidates(self, key, identifiers, approve=True):
        job = self._get(key)
        identifiers = frozenset(identifiers)
        if not identifiers <= {f.id for f in job.report.findings}:
            raise DocumentError('Une suggestion ne correspond plus au document.')
        return self._change(job, approved=job.approved | identifiers if approve else job.approved - identifiers)

    def add_box(self, key, box):
        job = self._get(key)
        if not isinstance(box, Box) or box.page > job.pages:
            raise DocumentError('Zone manuelle invalide.')
        return self._change(job, boxes=(*job.boxes, box))

    def undo_box(self, key):
        job = self._get(key)
        return self._change(job, boxes=job.boxes[:-1])

    def review_page(self, key, page):
        job = self._get(key)
        if not 1 <= page <= job.pages:
            raise DocumentError('Page inexistante.')
        job = replace(job, reviewed=job.reviewed | {page})
        self.jobs[key] = job
        return job

    def approve_document(self, key):
        job = self._get(key)
        if job.reviewed != frozenset(range(1, job.pages + 1)):
            raise DocumentError('Confirmez la vérification de chaque page avant de valider ce document.')
        # Check the same snapshot again at export, after this explicit approval.
        job = replace(job, approval_revision=job.revision, status='Validé pour export')
        self.jobs[key] = job
        return job

    def _open_bound(self, key):
        job = self._get(key)
        document = Document(job.path)
        if document.source_digest != job.digest:
            document.close()
            self.jobs[key] = replace(job, approval_revision=-1, status='Source modifiée — réanalyse requise')
            raise DocumentError('Le fichier source a changé. Réanalysez le lot ; ses anciennes zones ne sont plus utilisables.')
        return document

    def render(self, key, page, dpi=120):
        with self._open_bound(key) as document:
            return document.render(page - 1, dpi)

    def export(self, folder, *, cancel=None, progress=None):
        folder = Path(folder).resolve(strict=True)
        if not folder.is_dir():
            raise DocumentError('Choisissez un dossier de sortie.')
        selected = [job for job in self.jobs.values() if job.ready and job.output is None]
        if not selected:
            raise DocumentError('Aucun document validé à exporter.')
        token = uuid4().hex[:10]
        for number, job in enumerate(selected, 1):
            check_cancel(cancel)
            target = folder / f'lot-{token}-document-{int(job.id):03d}-masque.{"pdf" if job.kind == "pdf" else "png"}'
            try:
                with self._open_bound(job.id) as document:
                    masks = job.masks
                    document.export(target, list(masks), cancel=cancel)
                    audit = audit_export(document, target, masks,
                        [f for f in job.report.findings if f.id in job.approved], file_digest(target),
                        mode=job.report.mode, cancel=cancel)
                    if not audit.passed:
                        raise DocumentError('Le contrôle technique de la copie a échoué.')
                job = replace(job, output=target, status='Exporté — copie à relire')
            except ExportCancelled:
                # A completed file may exist if cancellation arrives during its audit.
                job = replace(job, output=target if target.exists() else None, approval_revision=-1,
                              status='Annulé — copie éventuelle à contrôler')
                self.jobs[job.id] = job
                if progress:
                    progress(number, len(selected), job)
                raise
            except Exception:
                job = replace(job, output=target if target.exists() else None, approval_revision=-1,
                              status='Refusé — source modifiée ou contrôle impossible')
            self.jobs[job.id] = job
            if progress:
                progress(number, len(selected), job)
        return tuple(self.jobs.values())


class BatchWorker:
    """One serial owner for all batch document operations, no Tk on this thread."""

    def __init__(self):
        self.session = BatchSession()
        self.requests, self.results = Queue(), Queue()
        self.cancel = Event()
        self.sequence, self.stopping = 0, False
        self.thread = Thread(target=self._run, name='partage-clair-lots', daemon=True)
        self.thread.start()

    def submit(self, operation, **arguments):
        if self.stopping:
            raise RuntimeError('Le traitement du lot est fermé.')
        self.sequence += 1
        self.requests.put((self.sequence, operation, arguments))
        return self.sequence

    def stop(self):
        self.stopping = True
        self.cancel.set()
        self.requests.put((0, 'shutdown', {}))

    def _run(self):
        while True:
            request, operation, args = self.requests.get()
            if operation == 'shutdown':
                break
            if self.stopping:
                continue
            try:
                def progress(done, total, job):
                    self.results.put((request, operation, 'progress', (done, total, job)))
                if operation == 'analyze':
                    result = self.session.analyze(**args, cancel=self.cancel, progress=progress)
                elif operation == 'export':
                    result = self.session.export(**args, cancel=self.cancel, progress=progress)
                elif operation == 'import_references':
                    result = args['source'], load_csv(args['path'], args['source'], self.cancel)
                elif operation in ('candidates', 'add_box', 'undo_box', 'review_page', 'approve_document', 'render', 'clear'):
                    result = getattr(self.session, operation)(**args)
                else:
                    raise DocumentError('Opération du lot inconnue.')
            except Exception as error:
                self.results.put((request, operation, 'error', error))
            else:
                self.results.put((request, operation, 'ok', result))
