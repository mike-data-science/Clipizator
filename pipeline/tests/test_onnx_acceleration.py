import sys
from types import SimpleNamespace

from publikclip_pipeline.models import onnx


def test_cpu_provider_without_gpu_runtime(monkeypatch):
    onnx.providers.cache_clear()
    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(
        get_available_providers=lambda: ["CPUExecutionProvider"],
    ))
    try:
        assert onnx.providers() == ["CPUExecutionProvider"]
    finally:
        onnx.providers.cache_clear()


def test_cuda_provider_preloads_libraries(monkeypatch):
    onnx.providers.cache_clear()
    loaded = []
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(
        get_available_providers=lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"],
        preload_dlls=lambda: loaded.append(True),
    ))
    try:
        assert onnx.providers() == ["CUDAExecutionProvider", "CPUExecutionProvider"]
        assert loaded == [True]
    finally:
        onnx.providers.cache_clear()
