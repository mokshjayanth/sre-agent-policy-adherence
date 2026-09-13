"""Problem selection against the pinned harness registry. Counts change if the harness pin moves."""

import pytest

from runner.problem_sets import EXCLUDED, select_problems, task_type

FLOOD_LOCALIZATION = "astronomy_shop_loadgenerator_flood_homepage-localization-1"


def test_task_filter_includes_noop_controls_and_skips_exclusions():
    problems, skipped = select_problems(task="detection")
    assert len(problems) == 33
    assert sum("noop" in p for p in problems) == 3
    assert "astronomy_shop_loadgenerator_flood_homepage-detection-1" in skipped


def test_all_problems_skip_the_known_broken_ones():
    problems, skipped = select_problems()
    assert len(problems) == 87
    assert set(skipped) == set(EXCLUDED)


def test_explicit_ids_drop_exclusions_unless_asked():
    problems, skipped = select_problems(ids=[FLOOD_LOCALIZATION, "pod_kill_hotel_res-detection-1"])
    assert problems == ["pod_kill_hotel_res-detection-1"]
    assert list(skipped) == [FLOOD_LOCALIZATION]
    assert select_problems(ids=[FLOOD_LOCALIZATION], include_excluded=True) == ([FLOOD_LOCALIZATION], {})


def test_id_file_ignores_comments_blank_lines_and_duplicates(tmp_path):
    id_file = tmp_path / "ids.txt"
    id_file.write_text("# comment\nmisconfig_app_hotel_res-detection-1\n\nmisconfig_app_hotel_res-detection-1\n")
    assert select_problems(id_file=id_file) == (["misconfig_app_hotel_res-detection-1"], {})


def test_unknown_ids_are_rejected():
    with pytest.raises(ValueError, match="no-such-problem-1"):
        select_problems(ids=["no-such-problem-1"])


@pytest.mark.parametrize(
    ("problem_id", "expected"),
    [
        ("noop_detection_hotel_reservation-1", "detection"),
        ("k8s_target_port-misconfig-mitigation-1", "mitigation"),
        ("flower_node_stop-detection", "detection"),
        ("something-else", "other"),
    ],
)
def test_task_type(problem_id, expected):
    assert task_type(problem_id) == expected
