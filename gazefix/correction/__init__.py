"""Provider-neutral correction contract. Engine selection is caller-owned."""
from gazefix.correction.engine import CorrectionEngine, CorrectionEngineFactory
from gazefix.correction.models import (CorrectionDebug, CorrectionOutput, CorrectionResult,
                                       CorrectionStatus, EyeCorrection)

__all__ = ["CorrectionEngine", "CorrectionEngineFactory", "CorrectionDebug", "CorrectionOutput",
           "CorrectionResult", "CorrectionStatus", "EyeCorrection"]
