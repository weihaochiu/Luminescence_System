from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable

from PySide6.QtCore import QObject, QTimer, Signal

from .keysight_b2900 import KeysightB2900Driver, is_keysight_b2900
from .smu_base import SMUDevice, SMUDriver
from .smu_control import SMUControlManager
from .smu_control import SMUOwnership


def select_auto_connect_device(
    devices: list[SMUDevice],
    preferred_serial: str = "",
    preferred_address: str = "",
) -> SMUDevice | None:
    """Choose a supported SMU without guessing between ambiguous devices."""

    supported = [device for device in devices if device.supported]
    serial = preferred_serial.strip().casefold()
    if serial:
        serial_matches = [
            device
            for device in supported
            if device.serial_number.strip().casefold() == serial
        ]
        if len(serial_matches) == 1:
            return serial_matches[0]
    address = preferred_address.strip().casefold()
    if address:
        address_matches = [
            device
            for device in supported
            if device.visa_address.strip().casefold() == address
        ]
        if len(address_matches) == 1:
            return address_matches[0]
    return supported[0] if len(supported) == 1 else None


class SMUManager(QObject):
    """Asynchronous VISA discovery and connection management.

    This stage intentionally exposes no source, measure, compliance, reset, or
    output commands. Discovery and connection use identity/status queries only.
    """

    scan_started = Signal()
    scan_finished = Signal(object)
    connection_started = Signal(str)
    connected = Signal(object)
    connection_failed = Signal(str)
    disconnected = Signal()
    status_changed = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.devices: list[SMUDevice] = []
        self.connected_device: SMUDevice | None = None
        self._driver: SMUDriver | None = None
        self.control = SMUControlManager(parent=self)
        self._resource_manager: Any | None = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="smu-visa")
        self._future: Future[Any] | None = None
        self._operation = ""
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(80)
        self._poll_timer.timeout.connect(self._poll_future)

    @property
    def is_busy(self) -> bool:
        return self._future is not None

    @property
    def is_connected(self) -> bool:
        return self._driver is not None and self.connected_device is not None

    def scan(self) -> None:
        if self.is_busy:
            return
        if self.is_connected:
            self.error_occurred.emit("請先中斷目前的 SMU 連線，再重新掃描 VISA 儀器。")
            return
        self.scan_started.emit()
        self.status_changed.emit("正在掃描 VISA 儀器…")
        self._start_operation("scan", self._scan_worker)

    def connect_device(self, device: SMUDevice) -> None:
        if self.is_busy:
            return
        if self.is_connected:
            self.error_occurred.emit("目前已有 SMU 連線；請先中斷連線再選擇其他儀器。")
            return
        self.connection_started.emit(device.visa_address)
        self.status_changed.emit(f"正在連線 SMU：{device.visa_address}")
        self._start_operation("connect", lambda: self._connect_worker(device))

    def output_enabled(self) -> bool | None:
        if not self._driver:
            return None
        if self.connected_device is not None and self.connected_device.supported:
            return self.control.confirm_output_enabled()
        return self._driver.query_output_enabled()

    def disconnect(self, force: bool = False) -> bool:
        if not self.is_connected:
            return True
        if not force:
            if (
                self.is_busy
                or self.control.ownership is not SMUOwnership.IDLE
                or self.control.is_busy
            ):
                self.error_occurred.emit(
                    "SMU 仍有 ownership 或 I/O 工作。請先安全關閉輸出再中斷連線。"
                )
                return False
            try:
                enabled = self.output_enabled()
            except Exception:
                enabled = None
            if enabled is not False:
                self.error_occurred.emit(
                    "無法確認 SMU Output 已關閉，請先安全關閉輸出。"
                )
                return False
        if not self._close_session(safe_output=force, force_unbind=force):
            return False
        self.disconnected.emit()
        self.status_changed.emit("SMU 已中斷連線")
        return True

    def connection_metadata(self, selected_address: str = "") -> dict[str, Any]:
        if self.connected_device is None:
            return {
                "connected": False,
                "visa_address": selected_address,
                "manufacturer": "",
                "model": "",
                "serial_number": "",
                "firmware_version": "",
                "idn": "",
                "visa_backend": "",
                "driver_name": "",
                "supported": False,
            }
        metadata = self.connected_device.to_metadata()
        metadata["connected"] = True
        return metadata

    def shutdown(self) -> None:
        self._poll_timer.stop()
        self.control.shutdown()
        self._close_session(safe_output=True, force_unbind=True)
        self._executor.shutdown(wait=False, cancel_futures=True)

    def safe_stop(self) -> bool:
        """Immediately attempt to put the connected SMU into a safe state."""
        stopped = self.control.safe_shutdown()
        if stopped:
            self.status_changed.emit("SMU output disabled")
        return stopped

    def _start_operation(self, operation: str, task: Callable[[], Any]) -> None:
        self._operation = operation
        self._future = self._executor.submit(task)
        self._poll_timer.start()

    def _poll_future(self) -> None:
        if self._future is None or not self._future.done():
            return
        self._poll_timer.stop()
        future = self._future
        operation = self._operation
        self._future = None
        self._operation = ""
        try:
            result = future.result()
            if operation == "scan":
                self.devices = result
                self.scan_finished.emit(self.devices)
                if self.devices:
                    self.status_changed.emit(f"找到 {len(self.devices)} 台可回應的 VISA 儀器")
                else:
                    self.status_changed.emit("找不到可回應的 VISA 儀器")
            elif operation == "connect":
                resource_manager, resource, device, driver = result
                self._adopt_connection(resource_manager, resource, device, driver)
                self.connected.emit(device)
                suffix = "｜手動控制可用｜OUTPUT：OFF" if device.supported else ""
                self.status_changed.emit(f"SMU 已連線：{device.display_name}{suffix}")
        except Exception as exc:
            prefix = "SMU 掃描失敗" if operation == "scan" else "SMU 連線失敗"
            message = f"{prefix}：{self._format_visa_error(exc)}"
            if operation == "connect":
                self.connection_failed.emit(message)
            self.error_occurred.emit(message)

    def _adopt_connection(
        self,
        resource_manager: Any,
        resource: Any,
        device: SMUDevice,
        driver: SMUDriver,
    ) -> None:
        """Publish a session atomically, or close and clear every partial field."""

        self._resource_manager = resource_manager
        self._driver = driver
        self.connected_device = device
        try:
            self.control.bind_driver(
                driver if device.supported else None,
                output_confirmed_off=device.supported,
            )
        except Exception:
            try:
                driver.close(safe_stop=False)
            except Exception:
                try:
                    resource.close()
                except Exception:
                    pass
            try:
                resource_manager.close()
            except Exception:
                pass
            self._resource_manager = None
            self._driver = None
            self.connected_device = None
            try:
                self.control.bind_driver(None, force=True)
            except Exception:
                pass
            raise

    @staticmethod
    def _open_resource_manager() -> tuple[Any, str]:
        try:
            import pyvisa
        except ImportError as exc:
            raise RuntimeError("尚未安裝 PyVISA；請重新執行 setup_and_run.bat") from exc

        errors: list[str] = []
        for backend, label in ((None, "系統 VISA"), ("@py", "PyVISA-py")):
            try:
                manager = pyvisa.ResourceManager(backend) if backend else pyvisa.ResourceManager()
                manager.list_resources()
                return manager, label
            except Exception as exc:
                errors.append(str(exc))
        raise RuntimeError("無法建立 VISA 連線；請安裝 Keysight IO Libraries Suite。" + " / ".join(errors))

    @classmethod
    def _scan_worker(cls) -> list[SMUDevice]:
        manager, backend_label = cls._open_resource_manager()
        devices: list[SMUDevice] = []
        try:
            addresses = manager.list_resources()
            for address in addresses:
                resource = None
                try:
                    resource = manager.open_resource(address, open_timeout=1500)
                    resource.timeout = 1200
                    resource.write_termination = "\n"
                    resource.read_termination = "\n"
                    idn = str(resource.query("*IDN?")).strip()
                    device = cls._device_from_idn(address, idn, backend_label)
                    devices.append(device)
                except Exception:
                    # Non-SCPI VISA resources are intentionally omitted.
                    continue
                finally:
                    if resource is not None:
                        try:
                            resource.close()
                        except Exception:
                            pass
        finally:
            manager.close()
        devices.sort(key=lambda item: (not item.supported, item.display_name.lower(), item.visa_address))
        return devices

    @classmethod
    def _connect_worker(
        cls, device: SMUDevice
    ) -> tuple[Any, Any, SMUDevice, SMUDriver]:
        manager, backend_label = cls._open_resource_manager()
        resource = None
        try:
            resource = manager.open_resource(device.visa_address, open_timeout=2500)
            resource.timeout = 2500
            resource.write_termination = "\n"
            resource.read_termination = "\n"
            idn = str(resource.query("*IDN?")).strip()
            verified = cls._device_from_idn(device.visa_address, idn, backend_label)
            driver_class: type[SMUDriver]
            driver_class = KeysightB2900Driver if verified.supported else SMUDriver
            driver = driver_class(resource, verified)
            if verified.supported:
                assert isinstance(driver, KeysightB2900Driver)
                driver.set_output_enabled(False)
                if driver.query_output_enabled() is not False:
                    raise RuntimeError("無法確認 SMU 安全初始化時 OUTPUT 為 OFF")
                driver.set_auto_output_enabled(False)
                if driver.query_auto_output_enabled() is not False:
                    raise RuntimeError(
                        "無法確認 Keysight B2900 auto-output 已停用"
                    )
                driver.set_voltage(0.0)
                driver.set_current(0.0)
                if driver.query_output_enabled() is not False:
                    raise RuntimeError("無法確認 SMU 安全初始化後 OUTPUT 為 OFF")
            return manager, resource, verified, driver
        except Exception:
            if resource is not None:
                try:
                    resource.close()
                except Exception:
                    pass
            manager.close()
            raise

    @staticmethod
    def _device_from_idn(address: str, idn: str, backend_label: str) -> SMUDevice:
        fields = [part.strip() for part in idn.split(",")]
        fields.extend([""] * (4 - len(fields)))
        manufacturer, model, serial_number, firmware_version = fields[:4]
        supported = is_keysight_b2900(manufacturer, model)
        driver_name = KeysightB2900Driver.driver_name if supported else SMUDriver.driver_name
        return SMUDevice(
            visa_address=address,
            manufacturer=manufacturer,
            model=model,
            serial_number=serial_number,
            firmware_version=firmware_version,
            idn=idn,
            visa_backend=backend_label,
            driver_name=driver_name,
            supported=supported,
        )

    def _close_session(self, safe_output: bool = False, force_unbind: bool = False) -> bool:
        if self._driver is not None:
            if safe_output:
                try:
                    if self.connected_device is not None and self.connected_device.supported:
                        self.safe_stop()
                    else:
                        self._driver.safe_stop()
                except Exception as exc:
                    self.error_occurred.emit(f"SMU best-effort safety stop failed：{exc}")
            try:
                self.control.bind_driver(None, force=force_unbind)
            except Exception as exc:
                if not force_unbind:
                    self.error_occurred.emit(str(exc))
                    return False
            try:
                self._driver.close(safe_stop=False)
            except Exception as exc:
                self.error_occurred.emit(f"SMU VISA session close failed：{exc}")
        if self._resource_manager is not None:
            try:
                self._resource_manager.close()
            except Exception:
                pass
        self._driver = None
        self._resource_manager = None
        self.connected_device = None
        return True

    @staticmethod
    def _format_visa_error(exc: Exception) -> str:
        abbreviation = getattr(exc, "abbreviation", "")
        if abbreviation:
            return f"{abbreviation}（{exc}）"
        return str(exc)
