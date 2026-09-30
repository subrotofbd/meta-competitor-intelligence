"""Worker entrypoint: `python -m worker`.

S1.2 -- consumes jobs from the PostgresJobQueue and executes collection runs.

The worker:
1. Builds the provider, job queue, and collection orchestrator
2. Loops forever, claiming jobs up to a batch limit
3. Executes each job based on its kind
4. Marks jobs complete or failed with typed error info
5. Handles lease extension for long-running jobs
6. Backs off when the queue is empty
"""

from __future__ import annotations

import logging
import signal
import sys
import time
import uuid

from app.composition import build_collection_orchestrator, build_job_queue
from app.models import CollectionRunStatus
from app.services.jobs import JobQueue

logger = logging.getLogger("worker")

# Graceful shutdown handling
_shutdown = False


def _signal_handler(signum: int, frame: object) -> None:
    global _shutdown
    logger.info("Received signal %s, shutting down...", signum)
    _shutdown = True


def main() -> int:
    """Run the worker loop until shutdown signal."""
    global _shutdown

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # Configure logging for the worker
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    logger.info("Worker starting (S1.2)")

    try:
        orchestrator, session = build_collection_orchestrator()
        job_queue = build_job_queue()

        worker_id = f"worker-{__import__('os').getpid()}"

        logger.info("Worker %s ready, polling queue...", worker_id)

        while not _shutdown:
            try:
                # Claim up to 5 jobs at a time
                claimed = job_queue.claim(limit=5, worker_id=worker_id)

                if not claimed:
                    # No work - back off briefly
                    time.sleep(2)
                    continue

                logger.info("Worker %s claimed %d job(s)", worker_id, len(claimed))

                for job in claimed:
                    if _shutdown:
                        break

                    try:
                        execute_job(orchestrator, job, job_queue, worker_id)
                    except Exception as e:
                        logger.exception("Job %s failed unexpectedly: %s", job.job_id, e)
                        job_queue.fail(job.job_id, reason=f"Worker error: {e}")

            except Exception as e:
                logger.exception("Worker loop error: %s", e)
                time.sleep(5)  # Back off on unexpected errors

    finally:
        try:
            session.close()
        except Exception:
            logger.warning("Error closing session on shutdown", exc_info=True)
        logger.info("Worker stopped")

    return 0


def execute_job(
    orchestrator,
    job,
    job_queue: JobQueue,
    worker_id: str,
) -> None:
    """Execute a single claimed job based on its kind."""
    if job.kind != "collection.run":
        logger.warning("Unknown job kind %r, marking failed", job.kind)
        job_queue.fail(job.job_id, reason=f"Unknown job kind: {job.kind}")
        return

    run_id_str = job.payload.get("collection_run_id")
    if not run_id_str:
        logger.error("Job %s missing collection_run_id", job.job_id)
        job_queue.fail(job.job_id, reason="Missing collection_run_id in payload")
        return

    run_id = uuid.UUID(run_id_str)

    logger.info("Executing collection run %s (attempt %d)", run_id, job.attempt)

    try:
        # Execute the collection run
        orchestrator.execute_collection_job(run_id)

        # Check the run status to determine job outcome
        status = orchestrator.get_run_status(run_id)

        if status is None:
            logger.error("CollectionRun %s not found after execution", run_id)
            job_queue.fail(job.job_id, reason="Run not found after execution")
            return

        if status == CollectionRunStatus.COMPLETE:
            logger.info("Collection run %s completed successfully", run_id)
            job_queue.complete(job.job_id)
        elif status == CollectionRunStatus.FAILED:
            error_message, error_type = orchestrator.get_run_error(run_id)
            logger.warning("Collection run %s failed: %s", run_id, error_message)
            job_queue.fail(
                job.job_id,
                reason=error_message or "Unknown error",
                error_type=error_type or "unknown",
            )
        elif status == CollectionRunStatus.PARTIAL:
            logger.info("Collection run %s completed partially", run_id)
            job_queue.complete(job.job_id)
        else:
            logger.warning("Collection run %s in unexpected state %s", run_id, status)
            job_queue.fail(job.job_id, reason=f"Unexpected run status: {status}")

    except Exception as e:
        logger.exception("Error executing collection run %s: %s", run_id, e)
        job_queue.fail(job.job_id, reason=f"Execution error: {e}")


if __name__ == "__main__":
    sys.exit(main())
