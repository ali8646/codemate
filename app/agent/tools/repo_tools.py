import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional
import git


EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "node_modules",
    ".idea",
    ".vscode",
    ".pytest_cache",
    "dist",
    "build",
    ".eggs",
}

SOURCE_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".sql",
    ".yaml",
    ".yml",
    ".json",
    ".toml",
    ".env.example",
    "Dockerfile",
}


def prepare_repo_workspace(repo_target: str, branch: Optional[str] = "main") -> Path:
    """
    Clones a remote GitHub repository or resolves a local repository path.
    Returns the absolute Path to the repository on disk.
    """
    # Check if target is a local directory
    local_path = Path(repo_target).expanduser().resolve()
    if local_path.is_dir():
        return local_path

    # Otherwise clone from remote URL (shallow clone for performance)
    target_dir = Path(tempfile.mkdtemp(prefix="codemate_repo_"))
    try:
        git.Repo.clone_from(
            url=repo_target,
            to_path=target_dir,
            branch=branch,
            depth=1,
            single_branch=True,
        )
        return target_dir
    except Exception as e:
        # Fallback to cloning without branch specifier if specified branch doesn't exist
        try:
            if target_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=True)
            git.Repo.clone_from(
                url=repo_target,
                to_path=target_dir,
                depth=1,
            )
            return target_dir
        except Exception as inner_e:
            if target_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=True)
            raise RuntimeError(f"Failed to clone repository {repo_target}: {inner_e}") from e


def cleanup_repo_workspace(repo_path: Path) -> None:
    """Safely cleans up cloned temporary workspaces."""
    if "codemate_repo_" in str(repo_path) and repo_path.exists():
        shutil.rmtree(repo_path, ignore_errors=True)


def inspect_repo_structure(repo_path: Path, max_depth: int = 4) -> Dict:
    """
    Inspects and summarizes the file tree and identified tech stack in a repository.
    """
    repo_path = repo_path.resolve()
    tree_lines = []
    source_files: List[str] = []
    config_files: List[str] = []

    for root, dirs, files in os.walk(repo_path):
        # Exclude unwanted directories
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS and not d.startswith(".")]
        
        rel_root = Path(root).relative_to(repo_path)
        depth = len(rel_root.parts)
        if depth > max_depth:
            continue

        indent = "  " * depth
        if rel_root != Path("."):
            tree_lines.append(f"{indent}📁 {rel_root.name}/")

        file_indent = "  " * (depth + 1)
        for f in files:
            if f.startswith(".") and f not in {".env.example", ".gitignore"}:
                continue
            
            file_path = Path(root) / f
            rel_file_path = str(file_path.relative_to(repo_path))
            ext = file_path.suffix.lower()

            if ext in {".txt", ".toml", ".json", ".yaml", ".yml"} or f in {"Dockerfile", "Makefile"}:
                config_files.append(rel_file_path)

            if ext in SOURCE_EXTENSIONS or f == "Dockerfile":
                source_files.append(rel_file_path)
                tree_lines.append(f"{file_indent}📄 {f}")

    return {
        "file_tree": "\n".join(tree_lines[:200]),  # Limit tree representation size
        "total_source_files": len(source_files),
        "source_files": source_files,
        "config_files": config_files,
    }


def read_code_file(
    repo_path: Path,
    relative_path: str,
    start_line: int = 1,
    end_line: Optional[int] = None,
    max_lines: int = 300,
) -> str:
    """
    Reads a file from the repository with 1-based line numbers.
    Safely enforces boundary checking to prevent directory traversal.
    """
    full_path = (repo_path / relative_path).resolve()
    
    # Path traversal protection
    if not str(full_path).startswith(str(repo_path.resolve())):
        raise PermissionError(f"Access denied: {relative_path} is outside the repository.")

    if not full_path.is_file():
        return f"Error: File '{relative_path}' not found."

    try:
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as e:
        return f"Error reading file '{relative_path}': {e}"

    total_lines = len(lines)
    actual_start = max(1, start_line)
    actual_end = min(total_lines, end_line or (actual_start + max_lines - 1))

    numbered_lines = [
        f"{idx:4d} | {lines[idx - 1].rstrip()}"
        for idx in range(actual_start, actual_end + 1)
    ]

    header = f"=== File: {relative_path} (Lines {actual_start}-{actual_end} of {total_lines}) ===\n"
    return header + "\n".join(numbered_lines)


def search_codebase(
    repo_path: Path,
    pattern: str,
    is_regex: bool = False,
    max_results: int = 30,
) -> List[Dict]:
    """
    Searches source files across the repository for a given regex or literal pattern.
    Returns matched files with line numbers and preview snippets.
    """
    results = []
    flags = re.IGNORECASE
    compiled_regex = None

    if is_regex:
        try:
            compiled_regex = re.compile(pattern, flags)
        except re.error as e:
            return [{"error": f"Invalid regex pattern: {e}"}]
    else:
        pattern_lower = pattern.lower()

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS and not d.startswith(".")]

        for file_name in files:
            file_path = Path(root) / file_name
            ext = file_path.suffix.lower()
            if ext not in SOURCE_EXTENSIONS and file_name != "Dockerfile":
                continue

            rel_path = str(file_path.relative_to(repo_path))
            try:
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    for line_num, line in enumerate(f, start=1):
                        matched = False
                        if compiled_regex:
                            if compiled_regex.search(line):
                                matched = True
                        else:
                            if pattern_lower in line.lower():
                                matched = True

                        if matched:
                            results.append({
                                "file_path": rel_path,
                                "line_number": line_num,
                                "line_content": line.strip()[:200],
                            })
                            if len(results) >= max_results:
                                return results
            except Exception:
                continue

    return results
