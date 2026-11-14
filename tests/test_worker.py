import time
from queue import Empty

import pytest
from PIL import Image
from pypdf import PdfWriter

from partage_clair.core import Box, ExportCancelled
from partage_clair.worker import DocumentWorker


def result(worker, request):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            event = worker.results.get(timeout=.1)
        except Empty:
            continue
        if event[0] == request and event[2] != 'progress':
            return event
    pytest.fail('Worker did not finish in time')


@pytest.fixture
def worker():
    worker = DocumentWorker()
    yield worker
    worker.stop()
    worker.thread.join(timeout=10)
    assert not worker.thread.is_alive()


def test_worker_open_render_export_and_failed_open_keeps_document(worker, tmp_path):
    source = tmp_path / 'source.png'
    Image.new('RGB', (100, 80), 'red').save(source)
    event = result(worker, worker.submit('open', path=source))
    assert event[2] == 'ok'
    info, image = event[3]
    assert info.pages == 1
    image.close()
    assert result(worker, worker.submit('open', path=tmp_path / 'missing.pdf'))[2] == 'error'
    event = result(worker, worker.submit('render', page=0, dpi=90))
    assert event[3].getpixel((10, 10)) == (255, 0, 0)
    event[3].close()
    target = tmp_path / 'share.png'
    event = result(worker, worker.submit('export', target=target, boxes=[Box(1, 0, 0, .5, .5)], dpi=150))
    assert event[2] == 'ok'
    with Image.open(target) as output:
        assert output.getpixel((10, 10)) == (0, 0, 0)


def test_immediate_cancel_is_not_lost_when_job_starts(worker, tmp_path):
    source = tmp_path / 'source.pdf'
    writer = PdfWriter()
    writer.add_blank_page(400, 300)
    writer.write(source)
    event = result(worker, worker.submit('open', path=source))
    event[3][1].close()
    worker.cancel.set()
    event = result(worker, worker.submit('export', target=tmp_path / 'cancelled.pdf', boxes=[], dpi=150))
    assert event[2] == 'error'
    assert isinstance(event[3], ExportCancelled)
    assert not (tmp_path / 'cancelled.pdf').exists()
    worker.cancel.clear()
    event = result(worker, worker.submit('export', target=tmp_path / 'retry.pdf', boxes=[], dpi=150))
    assert event[2] == 'ok'


def test_worker_rejects_requests_after_shutdown(worker):
    worker.stop()
    with pytest.raises(RuntimeError):
        worker.submit('render', page=0, dpi=90)


def test_worker_binds_export_audit_to_current_file_and_rejects_tampering(worker, tmp_path):
    source = tmp_path / 'source.png'
    Image.new('RGB', (80, 80), 'white').save(source)
    result(worker, worker.submit('open', path=source))[3][1].close()
    assert result(worker, worker.submit('audit_export'))[2] == 'error'
    target = tmp_path / 'copy.png'
    assert result(worker, worker.submit('export', target=target, boxes=[], dpi=150))[2] == 'ok'
    target.write_bytes(b'changed')
    event = result(worker, worker.submit('audit_export'))
    assert event[2] == 'error' and 'changé' in str(event[3])


def test_validated_names_export_everywhere_and_survive_rescan(worker, tmp_path):
    from tests.test_detection import make_pdf
    source = make_pdf(tmp_path / 'names.pdf', ['Nom : Alice Dupont', 'ALICE signe. DUPONT signe.'])
    result(worker, worker.submit('open', path=source))[3][1].close()
    event = result(worker, worker.submit('scan', use_ocr=False))
    assert event[2] == 'ok'
    report = event[3]
    finding = next(f for f in report.findings if f.kind == 'Nom' and f.value == 'Alice Dupont')
    assert finding.pages == (1, 2)
    custom = result(worker, worker.submit('find_name', value='Dupont'))[3]
    assert result(worker, worker.submit('scan', use_ocr=False))[2] == 'ok'
    target = tmp_path / 'names-shared.pdf'
    event = result(worker, worker.submit('export', target=target, boxes=[], groups=[custom.id], dpi=150))
    assert event[2] == 'ok'
    from partage_clair.core import Document
    with Document(target) as doc:
        for box in custom.zones:
            image = doc.render(box.page - 1, 150)
            assert image.getpixel((round((box.x0 + box.x1) * image.width / 2),
                                   round((box.y0 + box.y1) * image.height / 2))) == (0, 0, 0)
            image.close()
    failed = result(worker, worker.submit('export', target=tmp_path / 'bad.pdf',
                                         boxes=[], groups=['unknown'], dpi=150))
    assert failed[2] == 'error' and not (tmp_path / 'bad.pdf').exists()


def test_worker_replacement_is_bound_to_approved_group_and_audited(worker, tmp_path):
    from partage_clair.methods import MethodChoice
    from tests.test_detection import make_pdf
    source = make_pdf(tmp_path / 'source.pdf', ['Nom : Alice Dupont'])
    result(worker, worker.submit('open', path=source))[3][1].close()
    report = result(worker, worker.submit('scan', use_ocr=False))[3]
    name = next(f for f in report.findings if f.kind == 'Nom')
    target = tmp_path / 'copy.pdf'
    event = result(worker, worker.submit('export', target=target, boxes=[], groups=[name.id],
                                         choices={name.id: MethodChoice('pseudonym', 'Personne A')}))
    assert event[2] == 'ok'
    audit = result(worker, worker.submit('audit_export'))
    assert audit[2] == 'ok' and audit[3].labels_ok and not audit[3].approved_residuals
    bad = tmp_path / 'bad-copy.pdf'
    event = result(worker, worker.submit('export', target=bad, boxes=[], groups=[],
                                         choices={name.id: MethodChoice('pseudonym', 'Personne A')}))
    assert event[2] == 'error' and not bad.exists()
