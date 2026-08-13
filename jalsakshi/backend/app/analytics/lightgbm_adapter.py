"""Optional LightGBM booster, blended with the signature rules.

The demo ships without a trained model, and that is a deliberate choice: rules
derived from hydraulics are auditable, need no training data, and can explain
themselves to a village committee. A booster is worth adding once a deployment
has accumulated labelled history, so the seam is built now and left empty.

Behaviour:

* no `LIGHTGBM_MODEL_PATH`, no `lightgbm` installed, or an unreadable file ->
  `available` is False and the rules run alone. The app still starts; a missing
  optional model is not an outage.
* a loaded model -> its class probabilities are blended with the rule score at
  `LIGHTGBM_BLEND_WEIGHT`, and the resulting `classifier_version` records both,
  so any decision in the ledger can be traced to what produced it.

The model is expected to consume `features.FEATURE_ORDER` positionally and to
carry its class labels in `booster.params["class_names"]` or a sibling
`<model>.classes.json`. Anything else is refused rather than guessed at.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.analytics.features import FEATURE_ORDER, NetworkFeatures, to_vector
from app.schemas.simulation import FaultType

logger = logging.getLogger(__name__)


class LightGBMAdapter:
    """Wraps a booster if one is configured; a no-op if not."""

    def __init__(self, model_path: str = "", *, blend_weight: float = 0.5) -> None:
        self.model_path = model_path
        self.blend_weight = max(0.0, min(1.0, blend_weight))
        self._booster = None
        self._classes: list[FaultType] = []
        self.load_error: str | None = None
        if model_path:
            self._load(model_path)

    # -- loading -----------------------------------------------------------
    def _load(self, model_path: str) -> None:
        path = Path(model_path)
        if not path.is_file():
            self.load_error = f"model file not found: {path}"
            logger.warning("lightgbm model not loaded: %s", self.load_error)
            return
        try:
            import lightgbm  # noqa: PLC0415 -- optional dependency, imported late
        except ImportError:
            self.load_error = "lightgbm is not installed"
            logger.warning("lightgbm model not loaded: %s", self.load_error)
            return

        try:
            booster = lightgbm.Booster(model_file=str(path))
            classes = self._read_classes(booster, path)
        except Exception as error:  # a bad model must not take the API down
            self.load_error = f"{type(error).__name__}: {error}"
            logger.warning("lightgbm model not loaded: %s", self.load_error)
            return

        if not classes:
            self.load_error = "model carries no class labels"
            logger.warning("lightgbm model not loaded: %s", self.load_error)
            return
        if booster.num_feature() != len(FEATURE_ORDER):
            self.load_error = (
                f"model expects {booster.num_feature()} features, "
                f"FEATURE_ORDER has {len(FEATURE_ORDER)}"
            )
            logger.warning("lightgbm model not loaded: %s", self.load_error)
            return

        self._booster = booster
        self._classes = classes
        logger.info("lightgbm model loaded from %s (%s classes)", path, len(classes))

    @staticmethod
    def _read_classes(booster: object, path: Path) -> list[FaultType]:
        raw: list[str] = []
        params = getattr(booster, "params", None) or {}
        if isinstance(params, dict) and params.get("class_names"):
            names = params["class_names"]
            raw = names.split(",") if isinstance(names, str) else list(names)
        else:
            sidecar = path.with_suffix(".classes.json")
            if sidecar.is_file():
                raw = json.loads(sidecar.read_text(encoding="utf-8"))
        return [FaultType(name.strip()) for name in raw if name.strip()]

    # -- inference ---------------------------------------------------------
    @property
    def available(self) -> bool:
        return self._booster is not None

    @property
    def version_suffix(self) -> str:
        if not self.available:
            return ""
        return f"+lgbm:{Path(self.model_path).stem}@{self.blend_weight:g}"

    def predict(self, features: NetworkFeatures) -> dict[FaultType, float]:
        """Class probabilities, or `{}` when no model is loaded."""
        if self._booster is None:
            return {}
        try:
            scores = self._booster.predict([to_vector(features)])[0]
        except Exception as error:  # never let inference break detection
            logger.warning("lightgbm inference failed: %s", error)
            return {}
        values = list(scores) if hasattr(scores, "__iter__") else [float(scores)]
        return {
            fault_type: float(value)
            for fault_type, value in zip(self._classes, values, strict=False)
        }

    def blend(
        self, rule_scores: dict[FaultType, float], features: NetworkFeatures
    ) -> dict[FaultType, float]:
        """Convex combination of rule scores and model probabilities."""
        model_scores = self.predict(features)
        if not model_scores:
            return rule_scores
        w = self.blend_weight
        classes = set(rule_scores) | set(model_scores)
        return {
            fault_type: (1 - w) * rule_scores.get(fault_type, 0.0)
            + w * model_scores.get(fault_type, 0.0)
            for fault_type in classes
        }


__all__ = ["LightGBMAdapter"]
