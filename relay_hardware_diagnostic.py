from __future__ import annotations

"""Manual DCTTech USBRelay8 mechanical-click and readback diagnostic."""

import logging

from gui.relay_controller import RelayController, RelayError, run_hardware_diagnostic


def main() -> int:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    controller = RelayController()
    message = controller.refresh_connection()
    print(message)
    if not controller.connected:
        return 1
    try:
        run_hardware_diagnostic(controller)
    except RelayError as exc:
        print(f"diagnostic failed: {exc}")
        return 1
    finally:
        controller.disconnect()
    print("Diagnostic commands completed. Hardware verification still requires audible relay clicks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
