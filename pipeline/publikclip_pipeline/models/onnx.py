"""Prefer CUDA for vision inference, retaining CPU support on other machines."""

import logging
from functools import lru_cache

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def providers() -> list[str]:
    import onnxruntime as ort

    if "CUDAExecutionProvider" in ort.get_available_providers():
        # Reuse the CUDA/cuDNN libraries supplied with PyTorch. ONNX's preload
        # API also finds NVIDIA Python packages when they are not on LD_LIBRARY_PATH.
        import torch  # noqa: F401

        if hasattr(ort, "preload_dlls"):
            ort.preload_dlls()
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]
    return ["CPUExecutionProvider"]


def session(model_path: str, options=None):
    import onnxruntime as ort

    requested = providers()
    result = ort.InferenceSession(model_path, sess_options=options, providers=requested)
    if "CUDAExecutionProvider" in requested and "CUDAExecutionProvider" not in result.get_providers():
        log.warning("CUDA could not initialize for %s; using CPU inference", model_path)
    return result
