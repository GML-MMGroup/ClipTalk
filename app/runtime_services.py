from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from .process_supervisor import process_supervisor


@dataclass
class RuntimeServices:
    """Process-local execution resources for the single-user application.

    The application deliberately stays single-process. Keeping every pool,
    cancellation registry and generation lock in one owned object gives the
    FastAPI lifespan a deterministic shutdown boundary without introducing a
    distributed queue.
    """

    analysis_executor: ThreadPoolExecutor
    render_executor: ThreadPoolExecutor
    preview_executor: ThreadPoolExecutor
    source_proxy_executor: ThreadPoolExecutor
    output_preview_executor: ThreadPoolExecutor
    thumbnail_executor: ThreadPoolExecutor
    timeline_assets_executor: ThreadPoolExecutor
    jobs_lock: threading.RLock = field(default_factory=threading.RLock)
    waveform_generation_lock: threading.Lock = field(default_factory=threading.Lock)
    timeline_generation_lock: threading.Lock = field(default_factory=threading.Lock)
    composition_generation_lock: threading.Lock = field(default_factory=threading.Lock)
    fragment_download_lock: threading.Lock = field(default_factory=threading.Lock)
    automatic_composition_lock: threading.Lock = field(default_factory=threading.Lock)
    output_preview_generation_lock: threading.Lock = field(default_factory=threading.Lock)
    browser_preview_generation_lock: threading.Lock = field(default_factory=threading.Lock)
    source_preview_generation_lock: threading.Lock = field(default_factory=threading.Lock)
    delete_intents_lock: threading.Lock = field(default_factory=threading.Lock)
    delete_audit_lock: threading.Lock = field(default_factory=threading.Lock)
    content_index_locks_guard: threading.Lock = field(default_factory=threading.Lock)
    jobs: dict[str, dict[str, Any]] = field(default_factory=dict)
    cancel_events: dict[str, threading.Event] = field(default_factory=dict)
    analysis_futures: dict[str, Future[Any]] = field(default_factory=dict)
    subtitle_transcription_futures: dict[str, Future[Any]] = field(default_factory=dict)
    subtitle_transcription_cancels: dict[str, threading.Event] = field(default_factory=dict)
    render_futures: dict[str, set[Future[Any]]] = field(default_factory=dict)
    active_model_clients: dict[str, Any] = field(default_factory=dict)
    active_automatic_compositions: set[str] = field(default_factory=set)
    upload_attempts: dict[str, list[float]] = field(default_factory=dict)
    delete_intents: dict[str, dict[str, Any]] = field(default_factory=dict)
    content_index_locks: dict[str, threading.Lock] = field(default_factory=dict)

    @classmethod
    def create(cls, maximum_workers: int) -> "RuntimeServices":
        return cls(
            analysis_executor=ThreadPoolExecutor(
                max_workers=maximum_workers, thread_name_prefix="vlm-highlight",
            ),
            render_executor=ThreadPoolExecutor(max_workers=2, thread_name_prefix="highlight-render"),
            preview_executor=ThreadPoolExecutor(max_workers=1, thread_name_prefix="event-preview"),
            source_proxy_executor=ThreadPoolExecutor(max_workers=1, thread_name_prefix="source-proxy"),
            output_preview_executor=ThreadPoolExecutor(max_workers=1, thread_name_prefix="output-preview"),
            thumbnail_executor=ThreadPoolExecutor(max_workers=1, thread_name_prefix="task-thumbnail"),
            timeline_assets_executor=ThreadPoolExecutor(max_workers=1, thread_name_prefix="timeline-assets"),
        )

    def shutdown(self) -> None:
        # Cancel work that has not started. Running FFmpeg/model calls receive
        # their existing cooperative cancellation signal and are not awaited
        # indefinitely during process shutdown.
        for event in list(self.cancel_events.values()):
            event.set()
        for event in list(self.subtitle_transcription_cancels.values()):
            event.set()
        for client in list(self.active_model_clients.values()):
            cancel = getattr(client, "cancel", None)
            if callable(cancel):
                try:
                    cancel()
                except Exception:
                    # Shutdown must continue even if a provider adapter has
                    # already closed its transport.
                    pass
        process_supervisor.shutdown()
        for executor in (
            self.timeline_assets_executor,
            self.thumbnail_executor,
            self.output_preview_executor,
            self.source_proxy_executor,
            self.preview_executor,
            self.render_executor,
            self.analysis_executor,
        ):
            executor.shutdown(wait=False, cancel_futures=True)
