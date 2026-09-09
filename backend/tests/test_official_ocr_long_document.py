from copy import deepcopy

import fitz
import pytest
from test_aliyun_ocr_runtime import official_env

from libs.ocr_runtime import ocr_runtime_config
from libs.official_ocr_pipeline import official_ocr_extract


class PageClient:
    def __init__(self):
        self.pages = []

    def call(self, path, *, task, page_no, **kwargs):
        assert path.is_file()
        assert task == "advanced_recognition"
        self.pages.append(page_no)
        return {"provider": "aliyun_model_studio", "model": "offline-test", "task": task,
                "pageNo": page_no, "requestId": f"page-{page_no}", "costCny": .0001, "durationMs": 1,
                "input": {"width": 288, "height": 288, "sha256": f"test-page-{page_no}"},
                "text": "", "ocrResult": {"words_info": [{"text": f"PAGE-{page_no}",
                "location": [10, 10, 100, 10, 100, 30, 10, 30]}]}}


@pytest.mark.parametrize("batch_size", [3, 30])
def test_long_pdf_executes_every_page_and_resumes_missing_tail_only(tmp_path, batch_size):
    source = tmp_path / "35-pages.pdf"
    with fitz.open() as document:
        for _ in range(35):
            document.new_page(width=72, height=72)
        document.save(source)
    runtime = ocr_runtime_config(env=official_env(AICHECK_ALIYUN_OCR_MAX_PAGES_PER_BATCH=str(batch_size)), validate=True)
    profile = {"profileId": "offline-long-document-test", "requiredFields": [], "requiredTables": [],
               "sealRules": {"required": False}}
    cache = {}
    progress = []

    def completed(page, count, total, calls):
        cache[page] = deepcopy(calls)
        progress.append((count, total))

    client = PageClient()
    result = official_ocr_extract(source, profile=profile, runtime=runtime, client=client,
                                  work_directory=tmp_path / "first", page_completed=completed)
    assert sorted(client.pages) == list(range(1, 36))
    assert sorted(row["pageNo"] for row in result["fragments"]) == list(range(1, 36))
    assert result["outcomeStatus"] == "completed"
    assert progress[-1] == (35, 35)
    assert len(cache) == 35
    cache.pop(35)
    resumed_client = PageClient()
    resumed = official_ocr_extract(source, profile=profile, runtime=runtime, client=resumed_client,
                                   work_directory=tmp_path / "resumed", page_call_cache=cache)
    assert resumed_client.pages == [35]
    assert sorted(row["pageNo"] for row in resumed["fragments"]) == list(range(1, 36))
    assert resumed["outcomeStatus"] == "completed"


def test_interrupted_batch_retains_checkpoints_and_can_finish_remaining_pages(tmp_path):
    source = tmp_path / "interrupted.pdf"
    with fitz.open() as document:
        for _ in range(7):
            document.new_page(width=72, height=72)
        document.save(source)
    runtime = ocr_runtime_config(env=official_env(AICHECK_ALIYUN_OCR_MAX_PAGES_PER_BATCH="3"), validate=True)
    profile = {"profileId": "offline-interruption-test", "requiredFields": [], "requiredTables": []}
    cache = {}

    class InterruptedClient(PageClient):
        def call(self, path, *, task, page_no, **kwargs):
            if page_no == 4:
                raise RuntimeError("offline injected interruption")
            return super().call(path, task=task, page_no=page_no, **kwargs)

    def completed(page, count, total, calls):
        cache[page] = deepcopy(calls)

    with pytest.raises(RuntimeError, match="injected interruption"):
        official_ocr_extract(source, profile=profile, runtime=runtime, client=InterruptedClient(),
                             work_directory=tmp_path / "interrupted", page_completed=completed)
    assert {1, 2, 3}.issubset(cache)
    assert 4 not in cache
    missing = sorted(set(range(1, 8)) - set(cache))
    resumed_client = PageClient()
    result = official_ocr_extract(source, profile=profile, runtime=runtime, client=resumed_client,
                                  work_directory=tmp_path / "resumed", page_call_cache=cache)
    assert sorted(resumed_client.pages) == missing
    assert sorted(row["pageNo"] for row in result["fragments"]) == list(range(1, 8))
    assert result["outcomeStatus"] == "completed"
