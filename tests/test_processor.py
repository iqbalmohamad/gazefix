import numpy as np

from gazefix.pipeline.processor import PassthroughProcessor


def test_passthrough_processor_preserves_frame_and_does_not_copy() -> None:
    frame = np.zeros((2, 3, 3), dtype=np.uint8)
    frame.setflags(write=False)

    output = PassthroughProcessor().process(frame)

    assert output is frame
    assert not output.flags.writeable

