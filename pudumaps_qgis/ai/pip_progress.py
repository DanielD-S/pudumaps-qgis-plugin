"""Parser de líneas de pip para extraer progreso estructurado.

pip no emite progreso en formato máquina — solo texto humano. Esta
clase mantiene estado mientras consume líneas y devuelve un snapshot
de progreso que el dialog puede renderizar como barra determinada +
contador.

No es exacto (pip resuelve dependencias sobre la marcha y no sabemos
cuántos paquetes vendrán antes de empezar), pero un estimado basado
en heurísticas vale mucho más que una barra indeterminada.

Heurísticas:
- "Collecting <pkg>" → pip resolvió un nuevo paquete a instalar.
- "Downloading <file>.whl (X MB)" → comenzó descarga de paquete.
- "Successfully installed <list>" → fin exitoso, conocemos total real.
- Estimado base: 35 paquetes (típico geoai = ~35 con PyTorch).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Set

# "Collecting torch==2.1.0", "Collecting numpy>=1.20"
_COLLECTING = re.compile(r"^Collecting\s+([A-Za-z0-9_\-\.]+)")

# "Downloading torch-2.1.0-cp312-cp312-win_amd64.whl (203.4 MB)"
_DOWNLOADING = re.compile(
    r"^\s*Downloading\s+(\S+\.whl|\S+\.tar\.gz)\s+\(([\d.]+)\s*([kMG]?B)\)",
    re.IGNORECASE,
)

# "Successfully installed geoai-py-0.10.0 torch-2.1.0 ..."
_SUCCESS = re.compile(r"^Successfully installed\s+(.+)$")

# Estimado base de paquetes que tira geoai + GeoAgent + PyTorch.
# Si es muy bajo el progreso se queda pegado en 95%; si es muy alto
# llega al 100% antes de tiempo. 35 es razonable para geoai solo.
_DEFAULT_ESTIMATE = 35


@dataclass
class PipProgress:
    """Snapshot del progreso de una instalación pip."""

    packages_collected: int = 0
    packages_estimated: int = _DEFAULT_ESTIMATE
    bytes_downloaded: float = 0.0
    done: bool = False
    last_line: str = ""
    seen_packages: Set[str] = field(default_factory=set)

    @property
    def percent(self) -> int:
        """0..100 cap. None hasta que sepamos algo."""
        if self.done:
            return 100
        if self.packages_collected == 0:
            return 0
        pct = int(100 * self.packages_collected / max(self.packages_estimated, 1))
        # Cap a 95 hasta que veamos "Successfully installed". Evita
        # llegar a 100% y quedar pegado ahí mientras pip todavía
        # instala (la fase de descarga termina antes que la de install).
        # min(pct, 95) cubre el caso donde collected > estimated (sin
        # bump dinámico la pct sería >100; ahora siempre cap arriba).
        return min(max(pct, 0), 95)

    @property
    def human_summary(self) -> str:
        """Texto corto para la barra de progreso."""
        if self.done:
            return f"Listo · {self.packages_collected} paquetes instalados"
        if self.packages_collected == 0:
            return "Resolviendo dependencias…"
        mb = f" · {self.bytes_downloaded:.1f} MB descargados" if self.bytes_downloaded else ""
        return (
            f"Paquete {self.packages_collected} de ~{self.packages_estimated}"
            f"{mb}"
        )


class PipProgressParser:
    """Stateful parser. Llama `feed(line)` por cada línea de pip."""

    def __init__(self, estimate: int = _DEFAULT_ESTIMATE):
        self._progress = PipProgress(packages_estimated=estimate)

    @property
    def snapshot(self) -> PipProgress:
        return self._progress

    def feed(self, line: Optional[str]) -> PipProgress:
        """Consume una línea y devuelve snapshot actualizado.

        Tolera líneas vacías, None y formatos inesperados sin romper.
        """
        if not line:
            return self._progress
        self._progress.last_line = line

        m = _COLLECTING.match(line)
        if m:
            pkg = m.group(1).lower()
            if pkg not in self._progress.seen_packages:
                self._progress.seen_packages.add(pkg)
                self._progress.packages_collected += 1
                # Si ya excedemos el estimado, bumpealo dinámicamente
                # para que la barra no se quede pegada en 95%.
                if (
                    self._progress.packages_collected
                    > self._progress.packages_estimated
                ):
                    self._progress.packages_estimated = (
                        self._progress.packages_collected + 5
                    )

        m = _DOWNLOADING.search(line)
        if m:
            try:
                size = float(m.group(2))
            except ValueError:
                size = 0.0
            unit = m.group(3).lower()
            if unit.startswith("k"):
                size = size / 1024
            elif unit.startswith("g"):
                size = size * 1024
            self._progress.bytes_downloaded += size

        m = _SUCCESS.match(line)
        if m:
            installed = m.group(1).strip().split()
            self._progress.done = True
            # Si tenemos el dato real, lo usamos. Si no, dejamos el
            # contador acumulado en collected.
            if installed:
                self._progress.packages_collected = len(installed)
                self._progress.packages_estimated = len(installed)

        return self._progress

    def feed_many(self, lines: Iterable[str]) -> PipProgress:
        for line in lines:
            self.feed(line)
        return self._progress


__all__ = ["PipProgress", "PipProgressParser"]
