"""
Entry point for PyInstaller EXE.
Starts Streamlit web server then opens the browser automatically.
"""
import sys
import os

if getattr(sys, 'frozen', False):
    # Running inside PyInstaller bundle
    _base = sys._MEIPASS
    os.chdir(_base)                                          # make relative paths work
    os.environ['STREAMLIT_SERVER_FILE_WATCHER_TYPE'] = 'none'
    os.environ['STREAMLIT_BROWSER_GATHER_USAGE_STATS'] = 'false'
    if _base not in sys.path:
        sys.path.insert(0, _base)
else:
    _base = os.path.dirname(os.path.abspath(__file__))

import threading
import webbrowser
import time


def _open_browser():
    time.sleep(4)
    webbrowser.open('http://localhost:8501')


if __name__ == '__main__':
    threading.Thread(target=_open_browser, daemon=True).start()

    from streamlit.web import cli as stcli
    app_path = os.path.join(_base, 'app.py')
    sys.argv = [
        'streamlit', 'run', app_path,
        '--server.headless=true',
        '--server.port=8501',
        '--browser.gatherUsageStats=false',
    ]
    sys.exit(stcli.main())
