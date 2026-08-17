"""Tests del parser de líneas de pip a progreso estructurado."""

from __future__ import annotations

from pudumaps_qgis.ai.pip_progress import PipProgress, PipProgressParser


def test_initial_state():
    p = PipProgressParser().snapshot
    assert p.packages_collected == 0
    assert p.bytes_downloaded == 0.0
    assert p.done is False
    assert p.percent == 0


def test_collecting_increments_counter():
    parser = PipProgressParser(estimate=10)
    parser.feed("Collecting torch==2.1.0")
    parser.feed("Collecting numpy>=1.20")
    snap = parser.snapshot
    assert snap.packages_collected == 2


def test_collecting_same_package_twice_doesnt_double_count():
    parser = PipProgressParser(estimate=10)
    parser.feed("Collecting torch==2.1.0")
    parser.feed("Collecting torch==2.1.0")
    assert parser.snapshot.packages_collected == 1


def test_downloading_accumulates_bytes_mb():
    parser = PipProgressParser()
    parser.feed("Collecting torch")
    parser.feed("  Downloading torch-2.1.0-cp312.whl (203.4 MB)")
    assert parser.snapshot.bytes_downloaded == 203.4


def test_downloading_converts_kb_to_mb():
    parser = PipProgressParser()
    parser.feed("  Downloading tiny-1.0.whl (512 kB)")
    assert parser.snapshot.bytes_downloaded == 0.5


def test_downloading_converts_gb_to_mb():
    parser = PipProgressParser()
    parser.feed("  Downloading huge-1.0.whl (1.5 GB)")
    assert parser.snapshot.bytes_downloaded == 1536.0


def test_percent_caps_at_95_until_success():
    """Sin importar cuántos paquetes vea, sin "Successfully installed"
    nunca llega a 100. Esto evita el caso UX donde la barra dice 100%
    pero pip todavía está corriendo la fase de install."""
    parser = PipProgressParser(estimate=5)
    for i in range(20):
        parser.feed(f"Collecting pkg{i}")
    snap = parser.snapshot
    assert snap.done is False
    assert snap.percent <= 95


def test_percent_jumps_to_100_on_success():
    parser = PipProgressParser(estimate=10)
    parser.feed("Collecting torch")
    parser.feed("Successfully installed torch-2.1.0 numpy-1.24")
    assert parser.snapshot.percent == 100
    assert parser.snapshot.done is True


def test_estimate_grows_dynamically_to_avoid_stuck_95():
    """Si pip resuelve más paquetes que el estimado inicial, el estimado crece."""
    parser = PipProgressParser(estimate=5)
    for i in range(15):
        parser.feed(f"Collecting pkg{i}")
    snap = parser.snapshot
    assert snap.packages_estimated > 5
    assert snap.packages_estimated >= snap.packages_collected


def test_success_line_uses_real_total():
    parser = PipProgressParser(estimate=50)
    parser.feed("Successfully installed geoai-py-0.10.0 torch-2.1.0 numpy-1.24")
    snap = parser.snapshot
    assert snap.packages_collected == 3
    assert snap.packages_estimated == 3
    assert snap.done is True


def test_human_summary_reflects_state():
    parser = PipProgressParser(estimate=10)
    assert "Resolviendo" in parser.snapshot.human_summary

    parser.feed("Collecting torch")
    parser.feed("  Downloading torch-2.1.0.whl (203.4 MB)")
    summary = parser.snapshot.human_summary
    assert "1" in summary
    assert "MB" in summary

    parser.feed("Successfully installed torch-2.1.0")
    final = parser.snapshot.human_summary
    assert "Listo" in final


def test_empty_and_garbage_lines_dont_crash():
    """El parser debe tolerar líneas vacías, mensajes de warning, etc."""
    parser = PipProgressParser()
    parser.feed("")
    parser.feed("WARNING: pip is being invoked by an old script wrapper")
    parser.feed("blah blah random text")
    parser.feed(None)  # type: ignore[arg-type]  # defensa
    # No debería crashear
    assert parser.snapshot.packages_collected == 0


def test_feed_many_processes_full_log():
    parser = PipProgressParser(estimate=10)
    log = [
        "Collecting geoai-py==0.10.0",
        "  Downloading geoai_py-0.10.0.tar.gz (1.2 MB)",
        "Collecting torch>=2.0",
        "  Downloading torch-2.1.0.whl (203.4 MB)",
        "Collecting numpy",
        "  Downloading numpy-1.24.whl (16 MB)",
        "Successfully installed geoai-py-0.10.0 torch-2.1.0 numpy-1.24",
    ]
    snap = parser.feed_many(log)
    assert snap.done is True
    assert snap.packages_collected == 3
    assert snap.percent == 100
    # 1.2 + 203.4 + 16 = 220.6
    assert abs(snap.bytes_downloaded - 220.6) < 0.1
