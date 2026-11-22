"""gunicorn settings. Marks dead workers for prometheus_client multiprocess mode so their series are cleaned up."""
import os

if os.environ.get('PROMETHEUS_MULTIPROC_DIR'):
    def child_exit(server, worker):
        from prometheus_client import multiprocess
        multiprocess.mark_process_dead(worker.pid)
