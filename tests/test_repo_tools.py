import pytest
from pathlib import Path
from app.agent.tools.repo_tools import inspect_repo_structure, read_code_file, search_codebase


def test_inspect_benchmark_structure():
    benchmark_dir = Path("benchmarks/fastapi_nplusone")
    res = inspect_repo_structure(benchmark_dir)
    assert res["total_source_files"] >= 2
    assert any("routes.py" in f for f in res["source_files"])
    assert any("models.py" in f for f in res["source_files"])


def test_read_code_file():
    benchmark_dir = Path("benchmarks/fastapi_nplusone")
    content = read_code_file(benchmark_dir, "routes.py", start_line=1, end_line=20)
    assert "routes.py" in content
    assert "list_user_profiles" in content
    assert "1 |" in content or "01 |" in content or " 1 |" in content


def test_search_codebase():
    benchmark_dir = Path("benchmarks/crypto_insecure")
    matches = search_codebase(benchmark_dir, "hashlib.md5")
    assert len(matches) > 0
    assert any("auth.py" in m["file_path"] for m in matches)
