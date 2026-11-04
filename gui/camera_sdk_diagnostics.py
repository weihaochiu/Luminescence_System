from __future__ import annotations

"""Keep SDK operation names and HRESULTs across queued camera requests."""

import logging
from typing import Any, Callable, TypeVar

from .sdk import nncam


LOG = logging.getLogger(__name__)
_T = TypeVar("_T")
_OPTION_NAMES = {
    nncam.NNCAM_OPTION_AUTOEXP_POLICY: "NNCAM_OPTION_AUTOEXP_POLICY",
    nncam.NNCAM_OPTION_AUTOEXPOSURE_PERCENT: "NNCAM_OPTION_AUTOEXPOSURE_PERCENT",
    nncam.NNCAM_OPTION_TRIGGER: "NNCAM_OPTION_TRIGGER",
    nncam.NNCAM_OPTION_FLUSH: "NNCAM_OPTION_FLUSH",
}


def exception_hresult(error: BaseException) -> int | None:
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        value = getattr(error, "hr", None)
        if isinstance(value, int):
            return value & 0xFFFFFFFF
        error = error.__cause__ or error.__context__
    return None


class CameraSDKOperationError(RuntimeError):
    def __init__(self, operation: str, original: Exception):
        self.operation = operation
        self.hr = exception_hresult(original)
        code = f"; HRESULT=0x{self.hr:08X}" if self.hr is not None else ""
        super().__init__(f"{operation}{code}: {original}")


def sdk_call(stage: str, function: Callable[..., _T], *args: Any) -> _T:
    name = getattr(function, "__name__", type(function).__name__)
    values = [str(value) for value in args]
    if name in {"put_Option", "get_Option"} and args:
        values[0] = _OPTION_NAMES.get(args[0], values[0])
    operation = f"{stage}: {name}({', '.join(values)})"
    LOG.info("CAMERA_SDK_CALL %s", operation)
    try:
        return function(*args)
    except Exception as exc:
        error = CameraSDKOperationError(operation, exc)
        LOG.exception("CAMERA_SDK_FAILED %s", error)
        raise error from exc


def stop_for_configuration(controller: Any, stage: str) -> None:
    # Invalidate queued callbacks before stopping native acquisition.
    controller._stream_generation += 1
    sdk_call(stage, controller._camera.Stop)
    controller._scientific_frame_validated = False
