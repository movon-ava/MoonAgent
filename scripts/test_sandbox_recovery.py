"""Live check: a deleted sandbox container is recreated instead of 404-looping.

Run: uv run python scripts/test_sandbox_recovery.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from backend.sandbox import DockerSandbox


async def main() -> int:
    root = Path(__file__).resolve().parent.parent
    sandbox = DockerSandbox(
        image="ctf-sandbox",
        challenge_dir=str(root / "challenges" / "smoke-deepseek"),
        memory_limit="1g",
    )
    await sandbox.start()
    first_id = sandbox.container_id
    print("started:", first_id[:12])

    result = await sandbox.exec("echo hello")
    assert result.exit_code == 0 and "hello" in result.stdout, result
    print("exec ok:", result.stdout.strip())

    # Simulate `docker rm -f` from another process (this is what broke the run).
    await sandbox._container.delete(force=True)
    print("container deleted externally")

    result = await sandbox.exec("echo recovered")
    assert result.exit_code == 0, result
    assert "recovered" in result.stdout, result
    second_id = sandbox.container_id
    assert second_id != first_id, "a fresh container must be created"
    print("recovered:", second_id[:12], "->", result.stdout.strip())

    # read/write also survive a container loss
    await sandbox._container.delete(force=True)
    await sandbox.write_file("/challenge/workspace/after.txt", "survived")
    assert (await sandbox.read_file("/challenge/workspace/after.txt")) == "survived"
    print("read/write recovery ok")

    await sandbox.stop()
    print("\nALL SANDBOX RECOVERY CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
