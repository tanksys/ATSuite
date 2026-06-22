import os
import subprocess


def run_command(command: str) -> dict:
    timeout = float(os.environ.get("ATSUITE_SANDBOX_TIMEOUT", "300"))
    try:
        completed = subprocess.run(
            command,
            shell=True,
            executable="/bin/bash",
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + (exc.stderr or "")
        message = output.rstrip("\n")
        if message:
            message += "\n"
        message += f"Command timed out after {timeout} seconds."
        return {"returncode": 124, "output": message}

    output = (completed.stdout or "") + (completed.stderr or "")
    return {"returncode": completed.returncode, "output": output.rstrip("\n")}
