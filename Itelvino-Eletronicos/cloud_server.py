"""Public entry point for a single-instance cloud deployment."""

import os

from database import Database, data_directory
from mobile_server import MobileServer


def main():
    if not os.environ.get("ITELVINO_DATA_DIR"):
        raise RuntimeError("Configure ITELVINO_DATA_DIR to point to persistent storage.")
    data_directory()
    public_access = os.environ.get("ITELVINO_PUBLIC") == "1"
    host = "0.0.0.0" if public_access else "127.0.0.1"
    port = int(os.environ.get("PORT", "10000"))
    server = MobileServer(Database())
    httpd = server.listen(host, port, public_access=public_access)
    print(f"Itelvino web server listening on {host}:{port}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
