"""The optional booster seam.

The demo ships with no trained model, so the path that matters most is the one
where there is nothing to load: detection must run on the rules alone and the
API must still come up. The blending path is exercised with a stub booster —
`lightgbm` itself is not a test dependency.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.analytics.features import FEATURE_ORDER, NetworkFeatures
from app.analytics.lightgbm_adapter import LightGBMAdapter
from app.analytics.pipeline import DetectionService
from app.core.config import Settings
from app.schemas.simulation import FaultType
from app.services.memory_repository import InMemoryRepository
from detection_fixtures import build_history


def _features() -> NetworkFeatures:
    now = datetime.now(timezone.utc)
    return NetworkFeatures(
        service_area_id="sa-1", ts=now, window_start=now, window_end=now
    )


class _StubBooster:
    """Stands in for `lightgbm.Booster` — same surface, no dependency."""

    def __init__(self, scores: list[float] | None = None, *, raises: bool = False):
        self._scores = scores or []
        self._raises = raises
        self.seen: list[list[float]] = []

    def predict(self, rows: list[list[float]]) -> list[list[float]]:
        if self._raises:
            raise RuntimeError("booster is corrupt")
        self.seen.append(rows[0])
        return [self._scores]


def _adapter_with(
    booster: _StubBooster,
    classes: list[FaultType],
    *,
    blend_weight: float = 0.5,
    model_path: str = "models/vitpur.txt",
) -> LightGBMAdapter:
    adapter = LightGBMAdapter(blend_weight=blend_weight)
    adapter.model_path = model_path
    adapter._booster = booster
    adapter._classes = classes
    return adapter


# -- the shipped configuration: no model ------------------------------------
def test_no_model_configured_is_not_an_error() -> None:
    adapter = LightGBMAdapter()

    assert adapter.available is False
    assert adapter.load_error is None
    assert adapter.version_suffix == ""


def test_a_missing_model_file_degrades_instead_of_raising(tmp_path) -> None:
    adapter = LightGBMAdapter(str(tmp_path / "not-here.txt"))

    assert adapter.available is False
    assert "not found" in adapter.load_error


def test_rules_pass_through_untouched_without_a_model() -> None:
    rule_scores = {FaultType.PUMP_FAILURE: 0.8, FaultType.POWER_OUTAGE: 0.3}

    assert LightGBMAdapter().blend(rule_scores, _features()) == rule_scores


def test_predict_is_empty_without_a_model() -> None:
    assert LightGBMAdapter().predict(_features()) == {}


# -- blending ---------------------------------------------------------------
def test_blend_is_a_convex_combination() -> None:
    adapter = _adapter_with(
        _StubBooster([0.2, 0.6]),
        [FaultType.PUMP_FAILURE, FaultType.POWER_OUTAGE],
        blend_weight=0.5,
    )

    blended = adapter.blend(
        {FaultType.PUMP_FAILURE: 0.8, FaultType.POWER_OUTAGE: 0.4}, _features()
    )

    assert blended[FaultType.PUMP_FAILURE] == pytest.approx(0.5)
    assert blended[FaultType.POWER_OUTAGE] == pytest.approx(0.5)


def test_a_class_only_the_model_knows_still_enters_the_ranking() -> None:
    adapter = _adapter_with(
        _StubBooster([0.9]), [FaultType.PIPELINE_BURST], blend_weight=0.5
    )

    blended = adapter.blend({FaultType.PUMP_FAILURE: 1.0}, _features())

    assert blended[FaultType.PIPELINE_BURST] == pytest.approx(0.45)
    assert blended[FaultType.PUMP_FAILURE] == pytest.approx(0.5)


def test_blend_weight_zero_ignores_the_model() -> None:
    adapter = _adapter_with(
        _StubBooster([0.9, 0.1]),
        [FaultType.PUMP_FAILURE, FaultType.POWER_OUTAGE],
        blend_weight=0.0,
    )
    rule_scores = {FaultType.PUMP_FAILURE: 0.2, FaultType.POWER_OUTAGE: 0.7}

    blended = adapter.blend(rule_scores, _features())

    assert blended[FaultType.PUMP_FAILURE] == pytest.approx(0.2)
    assert blended[FaultType.POWER_OUTAGE] == pytest.approx(0.7)


def test_blend_weight_is_clamped_to_the_unit_interval() -> None:
    assert LightGBMAdapter(blend_weight=4.0).blend_weight == 1.0
    assert LightGBMAdapter(blend_weight=-2.0).blend_weight == 0.0


def test_the_model_is_fed_features_in_declared_order() -> None:
    booster = _StubBooster([1.0])
    adapter = _adapter_with(booster, [FaultType.PUMP_FAILURE])

    adapter.predict(_features())

    assert len(booster.seen[0]) == len(FEATURE_ORDER)


def test_a_booster_that_throws_falls_back_to_the_rules() -> None:
    """Inference is best-effort. A broken model must not stop detection."""
    adapter = _adapter_with(_StubBooster(raises=True), [FaultType.PUMP_FAILURE])
    rule_scores = {FaultType.PUMP_FAILURE: 0.8}

    assert adapter.predict(_features()) == {}
    assert adapter.blend(rule_scores, _features()) == rule_scores


def test_extra_model_outputs_without_a_label_are_dropped() -> None:
    adapter = _adapter_with(
        _StubBooster([0.5, 0.3, 0.2]), [FaultType.PUMP_FAILURE, FaultType.POWER_OUTAGE]
    )

    scores = adapter.predict(_features())

    assert set(scores) == {FaultType.PUMP_FAILURE, FaultType.POWER_OUTAGE}


# -- provenance -------------------------------------------------------------
def test_version_suffix_records_the_model_and_the_weight() -> None:
    adapter = _adapter_with(
        _StubBooster([1.0]),
        [FaultType.PUMP_FAILURE],
        blend_weight=0.25,
        model_path="models/vitpur-v3.txt",
    )

    assert adapter.version_suffix == "+lgbm:vitpur-v3@0.25"


def test_class_labels_can_come_from_a_sidecar_file(tmp_path) -> None:
    model = tmp_path / "vitpur.txt"
    model.write_text("stub", encoding="utf-8")
    model.with_suffix(".classes.json").write_text(
        json.dumps(["PUMP_FAILURE", "POWER_OUTAGE"]), encoding="utf-8"
    )

    classes = LightGBMAdapter._read_classes(object(), model)

    assert classes == [FaultType.PUMP_FAILURE, FaultType.POWER_OUTAGE]


def test_class_labels_in_the_model_params_win_over_a_sidecar(tmp_path) -> None:
    model = tmp_path / "vitpur.txt"
    booster = _StubBooster()
    booster.params = {"class_names": "VALVE_CLOSURE,PIPELINE_BURST"}

    classes = LightGBMAdapter._read_classes(booster, model)

    assert classes == [FaultType.VALVE_CLOSURE, FaultType.PIPELINE_BURST]


# -- the seam, wired into the real pipeline ---------------------------------
@pytest.mark.asyncio
async def test_a_loaded_model_is_named_in_the_classification(
    repository: InMemoryRepository, settings: Settings
) -> None:
    """Any decision in the ledger must be traceable to what produced it."""
    service = DetectionService(repository, settings)
    assert service.booster.available is False

    now = await build_history(
        repository, fault_type=FaultType.VALVE_CLOSURE, asset_code="VLV-01"
    )
    rules_only = await service.run(now=now)
    assert "+lgbm:" not in rules_only.classification.classifier_version

    service.booster = _adapter_with(
        _StubBooster([1.0]), [FaultType.VALVE_CLOSURE], blend_weight=0.2
    )
    blended = await service.run(now=now)

    assert blended.classification.classifier_version.endswith("+lgbm:vitpur@0.2")


@pytest.mark.asyncio
async def test_a_confident_model_cannot_resurrect_a_gated_out_rule(
    repository: InMemoryRepository, settings: Settings
) -> None:
    """The rules hold the veto.

    A model certain of PIPELINE_BURST must not produce a burst diagnosis when
    the hydraulics never supported one — otherwise an unauditable booster
    quietly becomes the decision-maker.
    """
    service = DetectionService(repository, settings)
    service.booster = _adapter_with(
        _StubBooster([1.0]), [FaultType.PIPELINE_BURST], blend_weight=0.9
    )

    now = await build_history(
        repository, fault_type=FaultType.VALVE_CLOSURE, asset_code="VLV-01"
    )
    run = await service.run(now=now)

    assert run.classification.fault_type is not FaultType.PIPELINE_BURST
