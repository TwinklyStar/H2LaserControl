"""Scope-style averaging of the snapshot display (user 2026-11-18)."""

import numpy as np
import pytest

from h2lasercontrol.daq.picoscope.averaging import (
    N_CHOICES,
    WaveAverager,
    default_n,
    n_label,
    offset_and_area,
)

DT = 20.0  # ns


def waves(rng, k=1000):
    out = []
    for _ in range(k):
        a = rng.normal(5.0, 0.3, 1000)  # 5 mV baseline + noise
        a[100:150] -= rng.normal(80, 5)  # pulse
        out.append({"A": a, "B": rng.normal(0, 1, 1000)})
    return out


def test_choices_and_labels():
    assert N_CHOICES == [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, None]
    assert n_label(None) == "∞" and n_label(64) == "64"
    assert default_n(100) == 128 and default_n(None) == 64


def test_offset_uses_first_5_percent_and_is_subtracted():
    w = np.zeros(1000)
    w[:50] = 2.0  # first 5 %
    w[50:] = 2.0
    w[500:510] = 12.0
    off, area = offset_and_area(w, DT)
    assert off == pytest.approx(2.0)
    assert area == pytest.approx(10 * 10.0 * DT * 1e-3)  # only the pulse counts


@pytest.mark.parametrize("n", [1, 8, 128])
def test_last_n_average_and_statistics_match_numpy(n):
    rng = np.random.default_rng(1)
    ws = waves(rng, 300)
    av = WaveAverager(n, "A")
    for w in ws:
        av.add(w, DT)
    last = ws[-n:]
    np.testing.assert_allclose(av.mean_waves()["A"], np.mean([w["A"] for w in last], axis=0))
    np.testing.assert_allclose(av.mean_waves()["B"], np.mean([w["B"] for w in last], axis=0),
                               atol=1e-12)
    offs, areas = zip(*(offset_and_area(w["A"], DT) for w in last), strict=True)
    st = av.stats()
    assert st.n == n
    assert st.offset_mv == pytest.approx(np.mean(offs))
    assert st.area == pytest.approx(np.mean(areas))
    std = np.std(areas, ddof=1) if n > 1 else 0.0
    assert st.std == pytest.approx(std, rel=1e-6, abs=1e-9)
    assert st.stderr == pytest.approx(std / np.sqrt(n), rel=1e-6, abs=1e-9)


def test_infinite_averages_everything_since_clear():
    rng = np.random.default_rng(2)
    ws = waves(rng, 50)
    av = WaveAverager(None, "A")
    for w in ws:
        av.add(w, DT)
    np.testing.assert_allclose(av.mean_waves()["A"], np.mean([w["A"] for w in ws], axis=0))
    areas = [offset_and_area(w["A"], DT)[1] for w in ws]
    st = av.stats()
    assert st.n == 50 and st.area == pytest.approx(np.mean(areas))
    assert st.std == pytest.approx(np.std(areas, ddof=1))
    av.clear()
    assert av.stats() is None and av.mean_waves() == {}


def test_fewer_waveforms_than_n_and_changing_n_restarts():
    rng = np.random.default_rng(3)
    av = WaveAverager(1024, "A")
    for w in waves(rng, 10):
        av.add(w, DT)
    assert av.stats().n == 10  # not yet full: average of what arrived
    av.set_n(4)
    assert av.count == 0  # restarted, as on an oscilloscope


def test_long_run_does_not_drift():
    rng = np.random.default_rng(4)
    av = WaveAverager(16, "A")
    ws = waves(rng, 9000)
    for w in ws:
        av.add(w, DT)
    np.testing.assert_allclose(av.mean_waves()["A"], np.mean([w["A"] for w in ws[-16:]], axis=0),
                               atol=1e-9)
