from dataclasses import FrozenInstanceError, fields
import pytest
from gazefix.correction.models import CorrectionResult, CorrectionStatus, EyeCorrection, CorrectionDebug


def test_metadata_is_frozen_and_array_free():
    result = CorrectionResult(CorrectionStatus.SKIPPED, "strength 0", 0., 0.)
    with pytest.raises(FrozenInstanceError): result.message = "changed"
    for cls in (CorrectionResult, EyeCorrection, CorrectionDebug):
        assert not any("ndarray" in str(f.type).lower() for f in fields(cls))
