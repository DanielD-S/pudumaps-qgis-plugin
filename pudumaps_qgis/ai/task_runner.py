"""QgsTask wrapper para ejecutar acciones IA sin bloquear QGIS.

Las clases en `pudumaps_qgis.ai.tools.*` exponen un `run()` síncrono
(más simple de testear, sin dependencias de QGIS). Este módulo envuelve
ese `run()` en un `QgsTask` para que el panel pueda dispararlo sin
congelar la UI.

Separación intencional:
- `AITool.run()` es puro Python — testable sin QGIS.
- `AIToolTask` es QGIS-only — solo se importa cuando hace falta.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

from qgis.core import QgsTask

from .tools import AITool, AIToolError


class AIToolTask(QgsTask):
    """Tarea QGIS que corre `tool.run()` en un hilo background.

    Uso típico desde el panel:

        task = AIToolTask(tool, raster_path, output_path, params)
        task.finished_ok.connect(on_success)
        task.finished_error.connect(on_error)
        QgsApplication.taskManager().addTask(task)

    QGIS gestiona el thread, cancelación y progreso. Si la tool lanza
    AIToolError, el task termina sin éxito y `error_message` queda
    poblado con el detalle.

    NOTA: signals/slots no se pueden heredar de QgsTask en PyQt — QGIS
    expone callbacks via overridable run()/finished(). Por eso pasamos
    callbacks por argumento en vez de signals.
    """

    def __init__(
        self,
        tool: AITool,
        raster_path: str,
        output_path: str,
        params: Optional[Dict] = None,
        on_success: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_progress: Optional[Callable[[str], None]] = None,
    ):
        super().__init__(f"Pudumaps · IA: {tool.name}", QgsTask.CanCancel)
        self._tool = tool
        self._raster_path = raster_path
        self._output_path = output_path
        self._params = params or {}
        self._on_success = on_success
        self._on_error = on_error
        self._on_progress = on_progress
        self._error_message: Optional[str] = None

    def run(self) -> bool:  # noqa: D401 — QgsTask API
        """Ejecutado en background thread por el QGIS task manager."""
        try:
            self._tool.run(
                raster_path=self._raster_path,
                output_path=self._output_path,
                params=self._params,
                progress_cb=self._emit_progress,
            )
            return True
        except AIToolError as e:
            self._error_message = str(e)
            return False
        except Exception as e:  # noqa: BLE001
            # Cualquier excepción no anticipada se convierte a fallo del task.
            self._error_message = f"Error inesperado: {type(e).__name__}: {e}"
            return False

    def finished(self, ok: bool) -> None:
        """Ejecutado en el hilo del UI tras `run()`. Dispara callbacks."""
        if ok and self._on_success is not None:
            self._on_success(self._output_path)
        elif not ok and self._on_error is not None:
            self._on_error(self._error_message or "Error desconocido")

    def cancel(self) -> None:
        super().cancel()
        # Nota: cancelación real depende de que `tool.run()` chequee
        # `self.isCanceled()` durante su loop. Las acciones actuales
        # son llamadas atómicas a geoai y no se pueden cancelar a mitad;
        # el cancel solo evita el callback de éxito si llega tarde.

    # ── Internos ─────────────────────────────────────────────────────

    def _emit_progress(self, msg: str) -> None:
        """Emite progreso al UI sin romper si el callback explota."""
        # setProgress acepta 0..100; usamos texto como descripción.
        self.setDescription(f"Pudumaps · IA: {self._tool.name} — {msg}")
        if self._on_progress is None:
            return
        try:
            self._on_progress(msg)
        except Exception:  # noqa: BLE001
            pass


__all__ = ["AIToolTask"]
