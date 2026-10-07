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

    def resolve_safe_path(self, relative_path: str | Path) -> Path:
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

    _resolve_safe_path = resolve_safe_path

    def read_note_detailed(
        self, relative_path: str, max_lines: int = 200
    ) -> tuple[NoteFrontmatter, str, int, bool]:
        """Read and parse note frontmatter and body with line-budget metrics.

        Returns:
            (frontmatter, truncated_body, total_lines, is_clamped)
        """
        target = self.resolve_safe_path(relative_path)
        if not target.is_file():
            raise FileNotFoundError(f"Note not found: {relative_path}")

        content = target.read_text(encoding="utf-8")
        frontmatter, full_body = parse_frontmatter(content)

        lines = full_body.splitlines(keepends=True)
        total_lines = len(lines)
        clamped = total_lines > max_lines
        body = "".join(lines[:max_lines]) if clamped else full_body

        return frontmatter, body, total_lines, clamped

    def read_note(self, relative_path: str, max_lines: int = 200) -> tuple[NoteFrontmatter, str]:
        """Read and parse note frontmatter and body, truncating body reading to max_lines."""
        frontmatter, body, _, _ = self.read_note_detailed(relative_path, max_lines=max_lines)
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
        target = self.resolve_safe_path(relative_path)
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
        target_val = category_folder.value
        if target_val == ProtectedFolder.NOTES.value and not (self.root_dir / target_val).exists():
            if (self.root_dir / ProtectedFolder.KNOWLEDGE.value).exists():
                target_val = ProtectedFolder.KNOWLEDGE.value
        folder_path = self.root_dir / target_val
        if not folder_path.exists():
            return []

        return sorted(
            str(path.relative_to(folder_path)).replace("\\", "/")
            for path in folder_path.rglob("*")
            if path.is_file()
        )

    def search_notes(
        self,
        query: str,
        limit: int = 5,
        folder: ProtectedFolder = ProtectedFolder.NOTES,
    ) -> list[tuple[str, str]]:
        """Search markdown notes in designated folder matching query against title, tags, or body.

        Returns:
            List of (relative_path, snippet) tuples.
        """
        target_val = folder.value
        if target_val == ProtectedFolder.NOTES.value and not (self.root_dir / target_val).exists():
            if (self.root_dir / ProtectedFolder.KNOWLEDGE.value).exists():
                target_val = ProtectedFolder.KNOWLEDGE.value
        folder_path = self.root_dir / target_val
        if not folder_path.exists():
            return []

        matches: list[tuple[str, str]] = []
        q = query.lower()

        for file_path in sorted(folder_path.rglob("*.md")):
            if len(matches) >= limit:
                break

            try:
                raw_text = file_path.read_text(encoding="utf-8")
            except Exception:
                continue

            # Fast filter: skip full parsing if query substring not in file
            if q not in raw_text.lower():
                continue

            try:
                fm, body = parse_frontmatter(raw_text)
            except Exception:
                continue

            rel_path = str(file_path.relative_to(self.root_dir)).replace("\\", "/")
            matched = False
            snippet = ""

            for line in body.splitlines():
                if q in line.lower():
                    matched = True
                    snippet = line.strip()
                    break

            if not matched and q in fm.title.lower():
                matched = True
                snippet = fm.title

            if not matched:
                for tag in fm.tags:
                    if q in tag.lower():
                        matched = True
                        snippet = f"Tag: {tag}"
                        break

            if matched:
                matches.append((rel_path, snippet))

        return matches

    def graduate_inbox(
        self, collision_resolution: str = "rename"
    ) -> GraduationReport:
        """Scan 00_Inbox/ and graduate valid notes into 01_Notes/{category}/.

        Args:
            collision_resolution: Strategy when destination note exists.
                'rename' (default): safely appends _1, _2 suffix without data loss.
                'fail': quarantine note in 00_Inbox/ with explicit failure reason.
                'overwrite': replace existing file.
        """
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
            try:
                content = file_path.read_text(encoding="utf-8")
            except Exception as exc:
                failures.append(
                    GraduationFailure(filename=file_path.name, reasons=[f"Cannot read file: {exc}"])
                )
                continue

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

            clean_category = fm.category.strip().replace("\\", "/").strip("/")
            cat_parts = [p for p in clean_category.split("/") if p]
            if not cat_parts:
                reasons.append("Category must not be empty")
            elif any(p.lower() in protected_names for p in cat_parts):
                reasons.append(f"Category '{clean_category}' points to a protected folder")
            elif ".." in cat_parts or any(c in clean_category for c in (":", "\x00")):
                reasons.append(f"Category '{clean_category}' contains invalid path characters")
            elif len(cat_parts) > 2:
                reasons.append(f"Category '{clean_category}' exceeds maximum depth of 2 folders")

            # Verify destination folder does not escape 01_Knowledge or 01_Notes
            target_folder = (
                ProtectedFolder.KNOWLEDGE.value
                if (self.root_dir / ProtectedFolder.KNOWLEDGE.value).exists()
                and not (self.root_dir / ProtectedFolder.NOTES.value).exists()
                else ProtectedFolder.NOTES.value
            )
            notes_root = (self.root_dir / target_folder).resolve()
            dest_dir = (notes_root / clean_category).resolve()
            try:
                dest_dir.relative_to(notes_root)
            except ValueError:
                reasons.append(f"Category '{clean_category}' attempts to escape notes directory")

            dest_file = dest_dir / file_path.name
            try:
                self.resolve_safe_path(dest_file)
            except ValueError as exc:
                reasons.append(f"Security violation for destination: {exc}")

            if dest_file.exists():
                if collision_resolution == "fail":
                    reasons.append(
                        f"Destination file already exists: {clean_category}/{dest_file.name}"
                    )
                elif collision_resolution == "rename":
                    counter = 1
                    stem = file_path.stem
                    suffix = file_path.suffix
                    while dest_file.exists():
                        dest_file = dest_dir / f"{stem}_{counter}{suffix}"
                        counter += 1

            if reasons:
                failures.append(GraduationFailure(filename=file_path.name, reasons=reasons))
            else:
                dest_dir.mkdir(parents=True, exist_ok=True)
                file_path.replace(dest_file)
                graduated_files.append(dest_file.name)

        return GraduationReport(
            graduated_count=len(graduated_files),
            failed_count=len(failures),
            graduated_files=graduated_files,
            failures=failures,
        )


WarehouseStore = WikiStore

