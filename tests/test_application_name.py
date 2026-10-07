import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

from boletinDiario.__main__ import main
from radar.__main__ import main as internal_main
from radar.app import create_app

ROOT = Path(__file__).resolve().parents[1]


def test_public_module_and_console_command_use_application_name():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert config["project"]["name"] == "boletinDiario"
    assert config["project"]["scripts"] == {"boletinDiario": "boletinDiario.__main__:main"}
    assert "boletinDiario*" in config["tool"]["setuptools"]["packages"]["find"]["include"]
    assert main is internal_main  # No segundo coordinador, implementación o biblioteca.
    result = subprocess.run([sys.executable, "-m", "boletinDiario", "--help"], cwd=ROOT, text=True, capture_output=True, check=True)
    assert "usage: boletinDiario" in result.stdout
    assert "--port" in result.stdout


def test_service_installer_generates_new_name_and_public_module_without_touching_systemd(tmp_path):
    project = tmp_path / "project"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    shutil.copyfile(ROOT / "scripts" / "install-service.sh", scripts / "install-service.sh")
    python = project / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\nexit 0\n")
    python.chmod(0o700)
    commands = tmp_path / "commands"
    commands.mkdir()
    systemctl = commands / "systemctl"
    systemctl.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$HOME/systemctl-calls"\n')
    systemctl.chmod(0o700)
    home = tmp_path / "home"
    home.mkdir()
    env = {**os.environ, "HOME": str(home), "PATH": str(commands) + os.pathsep + os.environ["PATH"]}
    subprocess.run(["bash", str(scripts / "install-service.sh")], env=env, check=True, capture_output=True, text=True)
    units = home / ".config" / "systemd" / "user"
    assert [path.name for path in units.iterdir()] == ["boletinDiario.service"]
    unit = (units / "boletinDiario.service").read_text()
    assert "Description=boletinDiario" in unit
    assert "-m boletinDiario" in unit
    assert "--user enable --now boletinDiario.service" in (home / "systemctl-calls").read_text()


def test_ollama_installer_and_readme_use_consistent_service_names():
    installer = (ROOT / "scripts" / "install-ollama-service.sh").read_text()
    for line in ("Before=boletinDiario.service", "Requires=boletinDiario-ollama.service", "After=boletinDiario-ollama.service"):
        assert line in installer
    assert "boletinDiario.service.d/ollama.conf" in installer
    readme = (ROOT / "README.md").read_text()
    assert "systemctl --user stop boletinDiario.service" in readme
    assert ".venv/bin/python -m boletinDiario" in readme


def test_web_application_and_browser_title_use_application_name(tmp_path):
    app = create_app(tmp_path, start_engine=False)
    assert app.title == "boletinDiario"
    with TestClient(app, base_url="http://localhost") as client:
        assert "<title>boletinDiario</title>" in client.get("/").text
