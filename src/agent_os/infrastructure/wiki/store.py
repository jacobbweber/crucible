"""WikiStore filesystem storage engine and vault manager."""

from pathlib import Path

from agent_os.domain.wiki import (
    GraduationFailure,
    GraduationReport,
    NoteFrontmatter,
    ProtectedFolder,
)
from agent_os.infrastructure.wiki.frontmatter import parse_frontmatter, serialize_note


class WikiStore:
    """Manages the 4-folder wiki vault filesystem."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir.resolve()

    def init_vault(self) -> None:
        """Idempotently initialize all protected vault directories."""
        for folder in ProtectedFolder:
            (self.root_dir / folder.value).mkdir(parents=True, exist_ok=True)

        templates_dir = self.root_dir / ProtectedFolder.RESOURCES.value / "templates"
        templates_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_safe_path(self, relative_path: str | Path) -> Path:
        """Enforce strict path confinement within the vault root.

        Raises:
            ValueError: If path traversal attempts to escape vault root.
        """
        resolved = (self.root_dir / Path(relative_path)).resolve()
        try:
            resolved.relative_to(self.root_dir)
        except ValueError as exc:
            raise ValueError(
                f"Path traversal detected: {relative_path} attempts to escape vault root"
            ) from exc
        return resolved

    def read_note(self, relative_path: str, max_lines: int = 200) -> tuple[NoteFrontmatter, str]:
        """Read and parse note frontmatter and body, truncating body reading to max_lines."""
        target = self._resolve_safe_path(relative_path)
        if not target.is_file():
            raise FileNotFoundError(f"Note not found: {relative_path}")

        content = target.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(content)

        lines = body.splitlines(keepends=True)
        if len(lines) > max_lines:
            body = "".join(lines[:max_lines])

        return frontmatter, body

    def write_note(
        self,
        relative_path: str,
        frontmatter: NoteFrontmatter,
        body: str,
        overwrite: bool = False,
    ) -> Path:
        """Write note atomically with serialized frontmatter.

        Raises:
            ValueError: If attempting to overwrite a protected root directory.
            FileExistsError: If file exists and overwrite is False.
        """
        target = self._resolve_safe_path(relative_path)
        protected_roots = {self.root_dir} | {
            (self.root_dir / folder.value).resolve() for folder in ProtectedFolder
        }

        if target in protected_roots:
            raise ValueError(f"Cannot overwrite protected directory: {relative_path}")

        if target.exists() and not overwrite:
            raise FileExistsError(f"Note already exists: {relative_path}")

        target.parent.mkdir(parents=True, exist_ok=True)
        serialized_content = serialize_note(frontmatter, body)

        temp_file = target.with_suffix(f"{target.suffix}.tmp")
        temp_file.write_text(serialized_content, encoding="utf-8")
        temp_file.replace(target)
        return target

    def list_category(self, category_folder: ProtectedFolder) -> list[str]:
        """Return relative file paths within the designated protected root."""
        folder_path = self.root_dir / category_folder.value
        if not folder_path.exists():
            return []

        return sorted(
            str(path.relative_to(folder_path)).replace("\\", "/")
            for path in folder_path.rglob("*")
            if path.is_file()
        )

    def graduate_inbox(self) -> GraduationReport:
        """Scan 00_Inbox/ and graduate valid notes into 01_Notes/{category}/."""
        inbox_dir = self.root_dir / ProtectedFolder.INBOX.value
        if not inbox_dir.exists():
            return GraduationReport(
                graduated_count=0,
                failed_count=0,
                graduated_files=[],
                failures=[],
            )

        graduated_files: list[str] = []
        failures: list[GraduationFailure] = []
        protected_names = {folder.value.lower() for folder in ProtectedFolder} | {
            folder.name.lower() for folder in ProtectedFolder
        }

        for file_path in sorted(inbox_dir.glob("*.md")):
            reasons: list[str] = []
            content = file_path.read_text(encoding="utf-8")

            try:
                fm, _ = parse_frontmatter(content)
            except Exception as exc:
                failures.append(
                    GraduationFailure(
                        filename=file_path.name,
                        reasons=[f"Invalid frontmatter: {exc}"],
                    )
                )
                continue

            if not fm.title.strip():
                reasons.append("Title must not be empty")

            if not fm.tags:
                reasons.append("Tags must not be empty")

            clean_category = fm.category.strip()
            if not clean_category:
                reasons.append("Category must not be empty")
            elif clean_category.lower() in protected_names:
                reasons.append(f"Category '{clean_category}' points to a protected folder")
            elif ".." in clean_category or "/" in clean_category or "\\" in clean_category:
                reasons.append(f"Category '{clean_category}' contains invalid path characters")

            if reasons:
                failures.append(GraduationFailure(filename=file_path.name, reasons=reasons))
            else:
                dest_dir = self.root_dir / ProtectedFolder.NOTES.value / clean_category
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest_file = dest_dir / file_path.name
                file_path.replace(dest_file)
                graduated_files.append(file_path.name)

        return GraduationReport(
            graduated_count=len(graduated_files),
            failed_count=len(failures),
            graduated_files=graduated_files,
            failures=failures,
        )
