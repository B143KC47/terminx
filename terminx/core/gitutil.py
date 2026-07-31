from pathlib import Path


def git_branch(cwd: Path | None) -> str | None:
    if not cwd or not cwd.exists():
        return None
    try:
        head = cwd / ".git" / "HEAD"
        if head.exists():
            text = head.read_text(encoding="utf-8", errors="ignore").strip()
            if text.startswith("ref: refs/heads/"):
                return text.removeprefix("ref: refs/heads/")
            if len(text) == 40:
                return f"detached {text[:8]}"
            return None
        gitfile = cwd / ".git"
        if gitfile.is_file():
            line = gitfile.read_text(encoding="utf-8", errors="ignore").strip()
            if line.startswith("gitdir:"):
                return git_branch(Path(line.split(":", 1)[1].strip()))
    except Exception:
        return None
    return None
