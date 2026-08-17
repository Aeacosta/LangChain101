import difflib


class XTPFileComparer:
    """Compare two XTP program files and expose their content and unified diff."""

    def __init__(self, path_a: str, path_b: str) -> None:
        self.path_a = path_a
        self.path_b = path_b
        self._lines_a: list[str] = []
        self._lines_b: list[str] = []
        self._diff: list[str] = []
        self._load()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Read both files and compute the unified diff."""
        with (
            open(self.path_a, "r", encoding="utf-8") as fa,
            open(self.path_b, "r", encoding="utf-8") as fb,
        ):
            self._lines_a = fa.readlines()
            self._lines_b = fb.readlines()

        self._diff = list(
            difflib.unified_diff(
                self._lines_a,
                self._lines_b,
                fromfile=self.path_a,
                tofile=self.path_b,
                lineterm="",
            )
        )

    # ------------------------------------------------------------------
    # Public views
    # ------------------------------------------------------------------

    @property
    def view_a(self) -> str:
        """Full text content of the first XTP file."""
        return "".join(self._lines_a)

    @property
    def view_b(self) -> str:
        """Full text content of the second XTP file."""
        return "".join(self._lines_b)

    @property
    def diff_view(self) -> str:
        """Unified diff between file A and file B."""
        return "\n".join(self._diff)

    def print_diff(self) -> None:
        """Print the unified diff to stdout."""
        for line in self._diff:
            print(line)


if __name__ == "__main__":
    comparer = XTPFileComparer(
        path_a=r"Programas/Commercial_Standard.xtp",
        path_b=r"Programas/Production_Standard.xtp",
    )
