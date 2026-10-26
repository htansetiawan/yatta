"""Point Yatta at throwaway data and key files before any yatta module is imported."""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="yatta-test-")
os.environ["YATTA_DATA"] = os.path.join(_tmp, "data")
os.environ["YATTA_AUTH_FILE"] = os.path.join(_tmp, "auth.json")
os.environ["YATTA_ENV_FILE"] = os.path.join(_tmp, "missing.env")
os.environ["YATTA_HOSTS"] = "yatta.example.com,old.example.com"
os.environ["YATTA_WEB_DIST"] = os.path.join(_tmp, "dist")
