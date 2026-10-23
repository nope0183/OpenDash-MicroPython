'''OpenDash MicroPython entry point.'''
import sys
import time

import opendash
from opendash.app import App


def main():
    print('OpenDash MicroPython', opendash.__version__)
    try:
        app = App()
        app.run()
    except Exception as exc:
        sys.print_exception(exc)
        # Keep the REPL alive: a hard reset here would hide the traceback.
        time.sleep(1)


if __name__ == '__main__':
    main()
