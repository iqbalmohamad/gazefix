import numpy as np

from gazefix.pipeline.processor import FrameContext, PassthroughProcessor


def test_passthrough_processor_preserves_frame_and_does_not_copy() -> None:
    frame = np.zeros((2, 3, 3), dtype=np.uint8)
    frame.setflags(write=False)

    output = PassthroughProcessor().process(frame, FrameContext(1, 0, 1))

    assert output.frame is frame
    assert output.tracking is None
    assert not output.frame.flags.writeable
    PassthroughProcessor().close()

