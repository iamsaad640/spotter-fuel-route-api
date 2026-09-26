import os

bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"
workers = int(os.getenv("WEB_CONCURRENCY", "2"))
threads = int(os.getenv("GUNICORN_THREADS", "4"))
worker_class = "gthread"
# Load the app once in the master so workers share the station index copy-on-write.
preload_app = True
timeout = 30
graceful_timeout = 20
keepalive = 5
max_requests = 1000
max_requests_jitter = 100
worker_tmp_dir = "/dev/shm"
accesslog = "-"
errorlog = "-"
forwarded_allow_ips = os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1")
