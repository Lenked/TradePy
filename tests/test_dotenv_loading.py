import os
import sys
import importlib


def test_dotenv_loading(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("MT5_LOGIN=1234\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MT5_LOGIN", raising=False)

    sys.modules.pop("main", None)
    import main
    importlib.reload(main)

    assert main.DOTENV_LOADED is True
    assert os.getenv("MT5_LOGIN") == "1234"
