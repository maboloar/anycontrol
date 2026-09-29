"""GPU(MPS) 작업 전용 단일 스레드와 모델 경로.

MPS 모델(등록 분할, Tier 1 마스크 보정, 임베딩)은 모두 이 스레드에서만 실행한다.
여러 스레드가 동시에 MPS 커맨드 큐를 쓰는 상황을 피하고, 작업 순서를 예측 가능하게 한다.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")

ROOT = Path(__file__).resolve().parents[4]  # visioninput-web/
MODELS_DIR = Path(os.environ.get("VI_MODELS_DIR", ROOT / "models"))

_executor: ThreadPoolExecutor | None = None
_lock = threading.Lock()
_thread_ident: int | None = None


def _mark() -> None:
    global _thread_ident
    _thread_ident = threading.get_ident()


def executor() -> ThreadPoolExecutor:
    global _executor
    with _lock:
        if _executor is None:
            os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
            os.environ.setdefault("TQDM_DISABLE", "1")
            _executor = ThreadPoolExecutor(1, thread_name_prefix="gpu", initializer=_mark)
        return _executor


def submit(fn: Callable[..., T], *args: Any, **kwargs: Any) -> Future[T]:
    return executor().submit(fn, *args, **kwargs)


def run(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """GPU 스레드에서 실행하고 결과를 기다린다. 이미 GPU 스레드면 바로 실행."""
    if threading.get_ident() == _thread_ident:
        return fn(*args, **kwargs)
    return submit(fn, *args, **kwargs).result()


def ml_available() -> bool:
    try:
        import efficient_track_anything  # noqa: F401
        import torch
    except ImportError:
        return False
    return bool(torch.backends.mps.is_available() or torch.cuda.is_available()) and \
        (MODELS_DIR / "efficienttam_ti_512x512.pt").is_file()


def device() -> Any:
    import torch

    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")
