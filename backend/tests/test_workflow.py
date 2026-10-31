from __future__ import annotations

import pytest

from services.workflow import InvalidTransition, transition


class Task:
    def __init__(self, status: str):
        self.status = status


def test_happy_path_must_progress_one_stage_at_a_time():
    task = Task("PENDING")
    for target in ("CHECKING", "PARSING", "VERIFYING", "REPORTING", "DONE"):
        transition(task, target)
    assert task.status == "DONE"


def test_supplement_can_only_resume_from_need_supplement():
    task = Task("NEED_SUPPLEMENT")
    transition(task, "PARSING")
    assert task.status == "PARSING"


def test_state_machine_rejects_skipping_directly_to_done():
    with pytest.raises(InvalidTransition):
        transition(Task("PENDING"), "DONE")
