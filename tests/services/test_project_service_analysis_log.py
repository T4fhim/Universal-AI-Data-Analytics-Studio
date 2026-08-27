# File: tests/services/test_project_service_analysis_log.py
"""Pure-service-layer round-trip test for ProjectService.record_analysis_log/get_recorded_analysis_logs.

Backs milestone 20's acceptance criterion 4 ("closing and reopening a project preserves the
analysis log") at the service layer, independent of any UI wiring -- a real ``tmp_path`` file on
disk, no mocks. See ``tests/ui/controllers/test_pipeline_controller.py`` for the controller-level
version of the same round trip, which additionally exercises
:class:`~src.ui.controllers.pipeline_controller.PipelineController`'s persist/restore methods.
"""

from __future__ import annotations

from src.services.project_service import ProjectService


def test_record_then_get_recorded_analysis_logs_round_trips_in_memory() -> None:
    service = ProjectService()
    project = service.new_project("Test")
    log_dict = {
        "dataset_id": "d1",
        "entries": [
            {
                "stage": "understand",
                "tool_name": "profile_dataset",
                "inputs": {},
                "outputs": {"row_count": 3},
                "explanation": None,
                "timestamp": "2026-01-01T00:00:00+00:00",
            }
        ],
    }

    service.record_analysis_log(project, "d1", log_dict)

    assert service.get_recorded_analysis_logs(project) == {"d1": log_dict}


def test_get_recorded_analysis_logs_is_empty_for_a_project_with_no_pipeline_history() -> (
    None
):
    service = ProjectService()
    project = service.new_project("Test")
    assert service.get_recorded_analysis_logs(project) == {}


def test_analysis_log_survives_a_real_save_and_reopen_round_trip(tmp_path) -> None:
    """The full acceptance-criterion-4 path, purely at the service layer."""
    service = ProjectService()
    project = service.new_project("Round Trip")
    log_dict = {
        "dataset_id": "d1",
        "entries": [
            {
                "stage": "understand",
                "tool_name": "profile_dataset",
                "inputs": {},
                "outputs": {"row_count": 1204, "column_count": 8},
                "explanation": None,
                "timestamp": "2026-01-01T00:00:00+00:00",
            }
        ],
    }
    service.record_analysis_log(project, "d1", log_dict)
    project_path = tmp_path / "round_trip.uads.json"
    service.save_project(project, project_path)

    # Fresh service instance, matching a real close-then-reopen -- nothing
    # in-memory carries over except what the file on disk actually holds.
    reopened_service = ProjectService()
    reopened_project = reopened_service.open_project(project_path)

    recorded = reopened_service.get_recorded_analysis_logs(reopened_project)
    assert recorded == {"d1": log_dict}
    assert recorded["d1"]["entries"][0]["outputs"]["row_count"] == 1204
