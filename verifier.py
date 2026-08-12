import os
import subprocess

elan_bin = os.path.expanduser("~/.elan/bin")
if elan_bin not in os.environ.get("PATH", "").split(os.pathsep):
    os.environ["PATH"] = elan_bin + os.pathsep + os.environ.get("PATH", "")

from lean_interact import LeanREPLConfig, LeanServer, FileCommand
from lean_interact.project import LocalProject

from config import LEAN_TOOLCHAIN, LEAN_PROJECT_DIR


def setup_lean_project(project_dir=LEAN_PROJECT_DIR):
    if os.path.exists(os.path.join(project_dir, "lakefile.lean")):
        return project_dir

    os.makedirs(project_dir, exist_ok=True)
    subprocess.run(["lake", "new", "lean_project", "math"], cwd=os.path.dirname(project_dir), check=True)

    toolchain_path = os.path.join(project_dir, "lean-toolchain")
    with open(toolchain_path, "w") as f:
        f.write(f"{LEAN_TOOLCHAIN}\n")

    subprocess.run(["elan", "toolchain", "install", LEAN_TOOLCHAIN], check=True)
    subprocess.run(["elan", "override", "set", LEAN_TOOLCHAIN], cwd=project_dir, check=True)
    subprocess.run(["lake", "build"], cwd=project_dir, check=True)

    return project_dir


class LeanVerifier:
    def __init__(self, project_dir=LEAN_PROJECT_DIR):
        self.project_dir = setup_lean_project(project_dir)
        project = LocalProject(directory=self.project_dir, auto_build=True)
        config = LeanREPLConfig(project=project, force_pull_repl=False, verbose=False)
        self.server = LeanServer(config)

    def verify(self, lean_code):
        filepath = os.path.join(self.project_dir, "Verification.lean")
        with open(filepath, "w") as f:
            f.write(lean_code)

        response = self.server.run(FileCommand(path=filepath))

        errors = [
            m for m in getattr(response, "messages", [])
            if getattr(m, "severity", None) == "error"
        ]

        is_valid = len(errors) == 0
        error_messages = [getattr(e, "data", str(e)) for e in errors]

        return {
            "valid": is_valid,
            "errors": error_messages,
            "num_errors": len(errors),
        }
