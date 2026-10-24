import subprocess
import sys


def test_dashboard_imports_like_streamlit_run(db):
    """streamlit run puts only app/ on sys.path; the page must still import app.queries."""
    code = ("import sys, runpy; sys.path[:] = ['app'] + [p for p in sys.path if p.endswith(('.zip', 'lib/python3.12', 'site-packages')) or 'lib-dynload' in p];"
            "runpy.run_path('app/dashboard.py', run_name='__main__')")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       env={"PATH": "/usr/local/bin:/usr/bin", "CNP_DB": db, "HOME": "/tmp"})
    assert "ModuleNotFoundError" not in r.stderr and "ImportError" not in r.stderr, r.stderr[-400:]
