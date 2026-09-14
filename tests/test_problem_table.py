"""The committed problem table, rebuilt from the registry without a cluster."""

import collections

from runner import problem_table as pt
from runner.problem_table import AOI_PARTITION, TABLE_PATH, build_table, to_csv


def test_committed_table_matches_the_pinned_registry():
    assert TABLE_PATH.read_text() == to_csv(build_table()), (
        "configs/problem-table.csv is stale: run `python -m runner.problem_table` and review the diff"
    )


def test_building_the_table_never_constructs_a_problem(monkeypatch):
    def refuse(self, problem_id):
        raise AssertionError("constructing a problem touches the cluster")

    monkeypatch.setattr(pt.ProblemRegistry, "get_problem_instance", refuse)
    assert len(build_table()) == 89


def test_each_noop_problem_gets_its_own_app():
    apps = {r["problem_id"]: r["app"] for r in build_table() if r["fault_family"] == "no_op"}
    assert apps == {
        "noop_detection_hotel_reservation-1": "HotelReservation",
        "noop_detection_social_network-1": "SocialNetwork",
        "noop_detection_astronomy_shop-1": "AstronomyShop",
    }


def test_every_group_outside_flower_maps_onto_aoi():
    unmapped = {(r["fault_family"], r["app"]) for r in build_table() if r["aoi_split"] == "not_in_aoi"}
    assert unmapped == {("flower_node_stop", "Flower"), ("flower_model_misconfig", "Flower")}


def test_task_counts_match_aoi_except_kafka_mitigation():
    """AOI counts 2 Kafka tasks; the pinned registry has 3.

    The mitigation problem was added to AIOpsLab in 7ec4d2f (2026-01-07). AOI's 86 tasks equal
    this registry's 89 minus the two Flower problems and that one, consistent with an earlier
    snapshot; AOI doesn't state its commit.
    """
    counts = collections.Counter((r["fault_family"], r["app"]) for r in build_table())
    differs = {group: (counts[group], aoi_count) for group, (_, _, aoi_count) in AOI_PARTITION.items()
               if counts[group] != aoi_count}
    assert differs == {("kafka_queue_problems", "AstronomyShop"): (3, 2)}


def test_aoi_totals_are_the_published_ones():
    totals = collections.Counter()
    for _, split, count in AOI_PARTITION.values():
        totals[split] += count
    types = collections.Counter(split for _, split, _ in AOI_PARTITION.values())
    assert totals == {"train": 38, "test": 48}
    assert types == {"train": 11, "test": 17}  # Table 7's caption says 15; it lists 17 rows
