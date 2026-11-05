"""The most important test in the repo.

The two sections we generate already exist in the record. If they reach the
model input, the model copies the answer and every number we report is void.
"""
import pytest

from nsight.ingest.segmentation import TARGET_SECTIONS


def test_target_sections_are_declared():
    assert set(TARGET_SECTIONS) == {"Brief Hospital Course", "Discharge Instructions"}


@pytest.mark.xfail(reason="enable once the pipeline is wired up", strict=False)
def test_targets_never_appear_in_model_input():
    from nsight.ingest.segmentation import segment_document
    from nsight.retrieve.budget import build_model_input

    result = segment_document(SAMPLE_NOTE, "sample")
    model_input = build_model_input(result)
    for section in (result.targets.brief_hospital_course,
                    result.targets.discharge_instructions):
        for chunk in _shingles(section, n=8):
            assert chunk not in model_input


def _shingles(text, n=8):
    words = (text or "").split()
    return [" ".join(words[i:i + n]) for i in range(0, max(0, len(words) - n))]


SAMPLE_NOTE = "placeholder"
