import sys

from app.ai_workbench.execution.supervisor import run_process


def test_supervisor_sends_stdin_and_separates_streams():
    script = "import sys; data=sys.stdin.read(); print('out:' + data); print('err:x', file=sys.stderr)"

    result = run_process((sys.executable, "-c", script), stdin_text="prompt", timeout_seconds=3)

    assert result.status == "completed"
    assert result.exit_code == 0
    assert "out:prompt" in result.stdout
    assert "err:x" in result.stderr


def test_supervisor_times_out_process():
    script = "import time; time.sleep(5)"

    result = run_process((sys.executable, "-c", script), timeout_seconds=0.2)

    assert result.status == "timeout"
    assert result.exit_code is not None

