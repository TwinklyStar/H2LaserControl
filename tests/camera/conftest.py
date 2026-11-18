"""Session-wide test fixtures — Qt offscreen platform + QApplication."""
from __future__ import annotations

import os

import pytest
from PySide6.QtWidgets import QApplication


def pytest_configure(config: pytest.Config) -> None:
    """Force offscreen Qt backend before QApplication is created."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(["laserdaq-test"])
    return app  # type: ignore[return-value]


# H2LaserControl merge: the real-camera tests open and close the camera many times; the old
# notes report that this camera's USB 2.0 link dies after a few cycles. Run them only on request.
def pytest_collection_modifyitems(config: pytest.Config, items: list) -> None:
    if os.environ.get("H2_CAMERA_HW") == "1":
        return
    skip = pytest.mark.skip(reason="real camera: set H2_CAMERA_HW=1 to run (opens/closes it)")
    for item in items:
        if "test_cam_ids_camera" in item.nodeid:
            item.add_marker(skip)
