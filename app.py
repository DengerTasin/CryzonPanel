"""CryzonCloud Cpanel — application entry point.

Run directly for development::

    CRYZON_DEMO=1 python app.py

or via gunicorn in production::

    gunicorn -w 4 -b 0.0.0.0:8080 app:app
"""
import os

from ccp import create_app

app = create_app()


if __name__ == "__main__":
    host = os.environ.get("CRYZON_HOST", "0.0.0.0")
    port = int(os.environ.get("CRYZON_PORT", "8080"))
    debug = os.environ.get("CRYZON_DEBUG") == "1"
    demo = os.environ.get("CRYZON_DEMO") == "1"

    banner = r"""
   ______                 ______                 __
  / ____/_____ __  __ ____/ ____/___  __  ______/ /
 / /   / ___/ / / /_/_  / /   / __ \/ / / / __  /
/ /___/ /  / /_/ /  / /_/ /___/ /_/ / /_/ / /_/ /
\____/_/   \__, /\___/\____/\____/\__,_/\__,_/
          /____/        Cpanel  v3
"""
    print(banner)
    print(f"  » Panel:  http://{host}:{port}")
    print(f"  » Mode:   {'DEMO (simulated containers)' if demo else 'LIVE (LXD)'}")
    print(f"  » Login:  admin / admin123\n")

    app.run(host=host, port=port, debug=debug, threaded=True)
