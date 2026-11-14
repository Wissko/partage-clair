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
