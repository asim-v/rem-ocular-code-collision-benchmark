from hashlib import sha256
import subprocess

import numpy as np
import pytest

import scripts.run_confirmatory_benchmark as confirmatory_runner
from scripts.run_ocular_code_benchmark import condition_seed, trailing_scale


def test_trailing_scale_cannot_see_future_samples():
    rng = np.random.default_rng(4)
    signal = rng.normal(size=2000)
    invalid = np.zeros(2000, dtype=bool)
    first = trailing_scale(signal, invalid, 1000, 10.0, 50.0, 10.0)
    changed_future = signal.copy()
    changed_future[1000:] *= 1000
    second = trailing_scale(changed_future, invalid, 1000, 10.0, 50.0, 10.0)
    assert first == second


def test_condition_seed_is_stable_and_label_specific():
    assert condition_seed(17, "00", "sync8_c0") == condition_seed(
        17, "00", "sync8_c0"
    )
    assert condition_seed(17, "00", "sync8_c0") != condition_seed(
        17, "01", "sync8_c0"
    )


def test_frozen_revision_accepts_git_equivalent_line_endings(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo,
        check=True,
    )
    (repo / ".gitattributes").write_bytes(b"*.py text eol=crlf\n")
    tracked = repo / "tracked.py"
    tracked.write_bytes(b"value = 1\r\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "freeze"], cwd=repo, check=True)
    monkeypatch.setattr(confirmatory_runner, "ROOT", repo)

    commit, hashes = confirmatory_runner.require_frozen_revision(("tracked.py",))
    head_bytes = subprocess.run(
        ["git", "show", "HEAD:tracked.py"],
        cwd=repo,
        check=True,
        capture_output=True,
    ).stdout
    assert commit
    assert tracked.read_bytes() != head_bytes
    assert hashes == {"tracked.py": sha256(head_bytes).hexdigest()}

    tracked.write_bytes(b"value = 2\r\n")
    with pytest.raises(RuntimeError, match="requires no tracked worktree changes"):
        confirmatory_runner.require_frozen_revision(("tracked.py",))
