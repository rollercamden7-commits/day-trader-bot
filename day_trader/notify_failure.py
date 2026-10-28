"""
Called by GitHub when a job fails. Emails you a link to the failed run -
unless the engine already emailed about its own crash.
"""
import os
import sys

from . import config as C
from .emailer import send_email

if __name__ == "__main__":
    if (C.PKG_DIR / ".crash_emailed").exists():
        sys.exit(0)
    job = sys.argv[1] if len(sys.argv) > 1 else "day trader"
    url = (f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
           f"{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}")
    send_email(f"ERROR - the {job} job failed",
               f"The {job} job failed before finishing. Open trades keep their stop-loss and "
               f"target orders on Alpaca, and the 3:50pm backstop will close anything left.\n\n"
               f"Details: {url}")
