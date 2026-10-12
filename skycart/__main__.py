"""Lets you log in from a terminal with:

    python -m skycart

(Python runs this file when you use `-m` with a package name.) Add --paste if
your browser can't reach this machine, e.g. inside Docker.
"""

import sys

from .auth import login

login(paste="--paste" in sys.argv)
