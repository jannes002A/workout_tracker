"""Gunicorn settings for the container. Read by `--config gunicorn.conf.py`.

This is what serves the app in a deployment: `python main.py` runs Flask's own
development server with `debug=True`, whose interactive debugger executes
arbitrary Python from the browser. That is a local convenience and must never
be what listens on a deployed port.
"""

import os

# Inside the container only. What the port is reachable *from* is decided on
# the host, by the port mapping in compose.yaml — which publishes to localhost.
bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"

# The database is a single SQLite file, and SQLite locks the whole file for
# each write. A couple of workers absorb slow clients without turning every
# logged session into a contended write, which is the right shape for an app
# one household uses. Raising this does not make SQLite more concurrent.
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))

# Build the app once, before forking. db.create_all() then runs a single time
# instead of once per worker, all of them racing on the same file.
preload_app = True

# A request that has not finished in this long is a stuck worker, not a slow
# page: nothing here does real work.
timeout = 30
graceful_timeout = 30
keepalive = 5

# Recycle workers periodically, with jitter so they do not all go at once. A
# leak or a wedged connection cannot then accumulate for the life of the
# container.
max_requests = 1000
max_requests_jitter = 100

# Caps on what a single request may send before it is refused. The defaults
# are already modest; these are explicit so that a change is a decision.
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190

# Logs to the container's stdout/stderr, which is where `docker logs` and any
# log driver expect them, rather than to files inside a read-only filesystem.
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")

# Deliberately *not* set to "*". X-Forwarded-For and X-Forwarded-Proto are
# trusted only from this list, so a client cannot forge its own address or
# claim the request arrived over HTTPS. Behind a reverse proxy, set
# FORWARDED_ALLOW_IPS to that proxy's address on the container network — never
# to "*" on a network anything else can reach.
forwarded_allow_ips = os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1")

# Gunicorn 26 opens a unix socket under $HOME for runtime commands. Nothing
# here drives it, the app user has no home directory, and the root filesystem
# is read-only — so it is switched off rather than pointed at a writable path.
# One less control channel inside the container.
control_socket_disable = True

proc_name = "training-log"
