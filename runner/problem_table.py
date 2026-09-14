"""Problem table: every registered AIOpsLab problem with its task, fault family, app and AOI split.

Built from the registry without constructing any problem: constructing one creates its
namespace and ConfigMaps on the cluster (notes/2026-09-14-agent-prompt-and-context.md,
Finding 6). Registry entries are classes, or lambdas that call a class with keyword
arguments. The fault family is the problem package the class lives in, the app is what
the class's __init__ assigns to self.app, and the target is the faulty_service the entry
passes or the class sets.

The aoi_fault_type and aoi_split columns map each problem onto the fault-type partition
published by AOI (arXiv:2603.03378, Appendix B.3, Tables 6 and 7). AOI names a fault type
by fault and app, which is one (fault_family, app) group here.

configs/problem-table.csv is the committed output; tests/test_problem_table.py fails if the
pinned harness no longer produces it. From the repo root, with the harness environment active:

    python -m runner.problem_table        # rewrite configs/problem-table.csv
"""

import csv
import inspect
import io
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AIOPSLAB_ROOT = REPO_ROOT / "third_party" / "aiopslab"
for _path in (AIOPSLAB_ROOT, REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from aiopslab.orchestrator.problems.registry import ProblemRegistry  # noqa: E402

from runner.problem_sets import EXCLUDED, task_type  # noqa: E402

TABLE_PATH = REPO_ROOT / "configs" / "problem-table.csv"
COLUMNS = [
    "problem_id", "task", "fault_family", "app", "target", "problem_class", "excluded",
    "aoi_fault_type", "aoi_split",
]

# NoOpBaseTask.__init__ chooses its app from app_name (problems/no_op/no_op.py); it's the
# only problem class that assigns more than one app.
NOOP_APPS = {"hotel": "HotelReservation", "social": "SocialNetwork", "astronomy_shop": "AstronomyShop"}

# (fault_family, app) -> (AOI fault type as printed, split, AOI's task count for that type).
# Table 6 lists the 11 training types (38 tasks); Table 7 lists the test types (48 tasks) in
# 17 rows, although its caption says 15 types.
AOI_PARTITION = {
    ("k8s_target_port_misconfig", "SocialNetwork"): ("k8s_target_port-misconfig", "train", 12),
    ("scale_pod", "SocialNetwork"): ("scale_pod_zero_social_net", "train", 4),
    ("misconfig_app", "HotelReservation"): ("misconfig_app_hotel_res", "train", 4),
    ("cart_service_failure", "AstronomyShop"): ("astronomy_shop_cart_service_failure", "train", 2),
    ("payment_service_failure", "AstronomyShop"): ("astronomy_shop_payment_service_failure", "train", 2),
    ("product_catalog_failure", "AstronomyShop"): ("astronomy_shop_product_catalog_failure", "train", 2),
    ("recommendation_service_cache_failure", "AstronomyShop"): ("astronomy_shop_recommend_cache_failure", "train", 2),
    ("auth_miss_mongodb", "SocialNetwork"): ("auth_miss_mongodb", "train", 4),
    ("network_loss", "HotelReservation"): ("network_loss_hotel_res", "train", 2),
    ("no_op", "HotelReservation"): ("noop_detection_hotel_reservation", "train", 1),
    ("redeploy_without_pv", "HotelReservation"): ("redeploy_without_PV", "train", 3),
    ("revoke_auth", "HotelReservation"): ("revoke_auth_mongodb", "test", 8),
    ("storage_user_unregistered", "HotelReservation"): ("user_unregistered_mongodb", "test", 8),
    ("assign_non_existent_node", "SocialNetwork"): ("assign_to_non_existent_node_social_net", "test", 4),
    ("wrong_bin_usage", "HotelReservation"): ("wrong_bin_usage", "test", 4),
    ("ad_service_high_cpu", "AstronomyShop"): ("astronomy_shop_ad_service_high_cpu", "test", 2),
    ("ad_service_manual_gc", "AstronomyShop"): ("astronomy_shop_ad_service_manual_gc", "test", 2),
    ("ad_service_failure", "AstronomyShop"): ("astronomy_shop_ad_service_failure", "test", 2),
    ("network_delay", "HotelReservation"): ("network_delay_hotel_res", "test", 2),
    ("pod_kill", "HotelReservation"): ("pod_kill_hotel_res", "test", 2),
    ("pod_failure", "HotelReservation"): ("pod_failure_hotel_res", "test", 2),
    ("image_slow_load", "AstronomyShop"): ("astronomy_shop_image_slow_load", "test", 2),
    ("kafka_queue_problems", "AstronomyShop"): ("astronomy_shop_kafka_queue_problems", "test", 2),
    ("loadgenerator_flood_homepage", "AstronomyShop"): ("astronomy_shop_loadgen_flood_homepage", "test", 2),
    ("payment_service_unreachable", "AstronomyShop"): ("astronomy_shop_payment_unreachable", "test", 2),
    ("no_op", "SocialNetwork"): ("noop_detection_social_network", "test", 1),
    ("no_op", "AstronomyShop"): ("noop_detection_astronomy_shop", "test", 1),
    ("container_kill", "HotelReservation"): ("container_kill", "test", 2),
}

_APP_ASSIGNMENT = re.compile(r"self\.app\s*=\s*(\w+)\(")
_FAULTY_SERVICE = re.compile(r"self\.faulty_service\s*=\s*[\"']([^\"']*)[\"']")
_KWARG = re.compile(r"(\w+)\s*=\s*[\"']([^\"']*)[\"']")


def _problem_class(entry):
    if inspect.isclass(entry):
        return entry
    classes = [entry.__globals__[n] for n in entry.__code__.co_names if inspect.isclass(entry.__globals__.get(n))]
    if len(classes) != 1:
        raise ValueError(f"registry lambda calls {len(classes)} classes, expected 1: {inspect.getsource(entry)}")
    return classes[0]


def _kwargs(entry) -> dict[str, str]:
    """String keyword arguments a registry lambda passes to its class; {} for a bare class."""
    if inspect.isclass(entry):
        return {}
    source = inspect.getsource(entry)
    call = source[source.index("lambda"):]
    return dict(_KWARG.findall(call[: call.index(")") + 1]))


def _init_sources(cls) -> list[str]:
    sources = []
    for klass in cls.__mro__:
        init = klass.__dict__.get("__init__")
        if init is None:
            continue
        try:
            sources.append(inspect.getsource(init))
        except (OSError, TypeError):
            continue
    return sources


def _app(cls, kwargs: dict[str, str]) -> str:
    for source in _init_sources(cls):
        assignments = _APP_ASSIGNMENT.findall(source)
        if len(assignments) == 1:
            return assignments[0]
        if len(assignments) > 1:
            if kwargs.get("app_name") in NOOP_APPS:
                return NOOP_APPS[kwargs["app_name"]]
            raise ValueError(f"{cls.__name__} assigns apps {assignments}; can't choose from {kwargs}")
    raise ValueError(f"{cls.__name__} assigns no app")


def _target(cls, kwargs: dict[str, str]) -> str:
    if "faulty_service" in kwargs:
        return kwargs["faulty_service"]
    for source in _init_sources(cls):
        found = [s for s in _FAULTY_SERVICE.findall(source) if s != "PLACEHOLDER"]
        if found:
            return found[0]
    return ""


def build_table() -> list[dict]:
    rows = []
    for problem_id, entry in ProblemRegistry().PROBLEM_REGISTRY.items():
        cls = _problem_class(entry)
        kwargs = _kwargs(entry)
        module = cls.__module__.split(".")
        family = module[module.index("problems") + 1]
        app = _app(cls, kwargs)
        aoi_type, aoi_split, _ = AOI_PARTITION.get((family, app), ("", "not_in_aoi", 0))
        rows.append({
            "problem_id": problem_id,
            "task": task_type(problem_id),
            "fault_family": family,
            "app": app,
            "target": _target(cls, kwargs),
            "problem_class": cls.__name__,
            "excluded": str(problem_id in EXCLUDED).lower(),
            "aoi_fault_type": aoi_type,
            "aoi_split": aoi_split,
        })
    return rows


def to_csv(rows: list[dict]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def main() -> None:
    TABLE_PATH.write_text(to_csv(build_table()))
    print(f"wrote {TABLE_PATH}")


if __name__ == "__main__":
    main()
