"""OpenMontage Studio — file de tâches locale (étape G0).

Les opérations longues (narration, rendu, contrôle, export) s'exécutent en arrière-plan,
UNE SEULE À LA FOIS : une nouvelle tâche est refusée tant qu'une autre est en cours.
Chaque tâche a un journal, une progression facultative et peut être annulée (annulation
coopérative : la fonction reçoit un `JobContext` dont elle consulte `cancelled`).
"""

from __future__ import annotations

import threading
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from lib.studio.project import now_iso

PENDING, RUNNING, DONE, FAILED, CANCELLED = "en_attente", "en_cours", "terminee", "echouee", "annulee"
MAX_LOG_LINES = 500


class JobBusyError(RuntimeError):
    """Une tâche est déjà en cours."""


@dataclass
class Job:
    id: str
    name: str
    project: Optional[str]
    status: str = PENDING
    created: str = field(default_factory=now_iso)
    started: Optional[str] = None
    finished: Optional[str] = None
    progress: Optional[float] = None
    log: list[str] = field(default_factory=list)
    result: Any = None
    error: Optional[str] = None
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    thread: Optional[threading.Thread] = field(default=None, repr=False)

    def as_dict(self) -> dict:
        return {"id": self.id, "nom": self.name, "projet": self.project, "statut": self.status,
                "cree_le": self.created, "debut": self.started, "fin": self.finished,
                "progression": self.progress, "journal": list(self.log[-50:]),
                "resultat": self.result if isinstance(self.result, (dict, list, str, int, float, type(None))) else str(self.result),
                "erreur": self.error}


class JobContext:
    """Passé à la fonction de la tâche."""

    def __init__(self, job: Job, lock: threading.Lock) -> None:
        self._job, self._lock = job, lock

    @property
    def cancel_event(self) -> threading.Event:
        return self._job.cancel_event

    @property
    def cancelled(self) -> bool:
        return self._job.cancel_event.is_set()

    def log(self, line: str) -> None:
        with self._lock:
            self._job.log.append(str(line))
            del self._job.log[:-MAX_LOG_LINES]

    def progress(self, value: float) -> None:
        with self._lock:
            self._job.progress = max(0.0, min(1.0, float(value)))


class JobQueue:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._current: Optional[str] = None

    def submit(self, name: str, fn: Callable[[JobContext], Any], project: Optional[str] = None) -> Job:
        with self._lock:
            if self._current and self._jobs[self._current].status in (PENDING, RUNNING):
                raise JobBusyError(f"Une tâche est déjà en cours : {self._jobs[self._current].name}.")
            job = Job(id=uuid.uuid4().hex[:12], name=name, project=project)
            self._jobs[job.id] = job
            self._current = job.id
        job.thread = threading.Thread(target=self._run, args=(job, fn), daemon=True, name=f"studio-{job.id}")
        job.thread.start()
        return job

    def _run(self, job: Job, fn: Callable[[JobContext], Any]) -> None:
        ctx = JobContext(job, self._lock)
        with self._lock:
            job.status, job.started = RUNNING, now_iso()
        try:
            result = fn(ctx)
            status, error = (CANCELLED, "annulée") if job.cancel_event.is_set() else (DONE, None)
        except BaseException as exc:  # noqa: BLE001 — la tâche ne doit jamais emporter le serveur
            result = None
            status = CANCELLED if job.cancel_event.is_set() else FAILED
            error = f"{type(exc).__name__}: {exc}"
            ctx.log(traceback.format_exc(limit=3))
        with self._lock:
            job.status, job.result, job.error, job.finished = status, result, error, now_iso()
            if status == DONE:
                job.progress = 1.0

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.status not in (PENDING, RUNNING):
            return False
        job.cancel_event.set()
        return True

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def current(self) -> Optional[Job]:
        job = self._jobs.get(self._current) if self._current else None
        return job if job and job.status in (PENDING, RUNNING) else None

    def list(self) -> list[Job]:
        return sorted(self._jobs.values(), key=lambda j: j.created, reverse=True)

    def wait(self, job_id: str, timeout: Optional[float] = None) -> Job:
        job = self._jobs[job_id]
        if job.thread:
            job.thread.join(timeout)
        return job
