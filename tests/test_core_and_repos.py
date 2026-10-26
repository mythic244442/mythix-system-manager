"""Unit tests for mythix-system-manager core helpers and repository parsers."""
import tempfile
import unittest
from pathlib import Path
from system_manager import core
from system_manager.pages.repos import ReposMixin


class DummyRepos(ReposMixin):
    def __init__(self):
        self.logs = []
    def _plog(self, msg):
        self.logs.append(msg)


class TestCoreAndRepos(unittest.TestCase):
    def test_human_size(self):
        self.assertEqual(core.human_size(512), "512.0 B")
        self.assertEqual(core.human_size(2048), "2.0 KB")
        self.assertEqual(core.human_size(5 * 1024 * 1024), "5.0 MB")

    def test_safe_expand_path_uses_user_home(self):
        expanded = core.safe_expand_path("~/.cache/thumbnails")
        self.assertEqual(expanded, core.USER_HOME / ".cache" / "thumbnails")

    def test_mint_and_debian_release_maps(self):
        self.assertEqual(core.mint_release_index("21.3"), 3)
        self.assertEqual(core.mint_release_index("22.3"), 7)
        self.assertIsNone(core.mint_release_index("99.9"))
        self.assertEqual(core.DEBIAN_NEXT_CODENAME["bookworm"], "trixie")
        self.assertEqual(core.DEBIAN_NEXT_CODENAME["trixie"], "forky")

    def test_atomic_write_and_backup(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            orig_backup = core.BACKUP_ROOT
            core.BACKUP_ROOT = tmp_path / "backups"
            try:
                target = tmp_path / "sample.conf"
                target.write_text("initial=1\n", encoding="utf-8")
                backup = core.write_text_with_backup(target, "initial=2\n", label="test")
                self.assertEqual(target.read_text(encoding="utf-8"), "initial=2\n")
                self.assertIsNotNone(backup)
                self.assertTrue(backup.exists())
                self.assertEqual(backup.read_text(encoding="utf-8"), "initial=1\n")
            finally:
                core.BACKUP_ROOT = orig_backup

    def test_parse_repo_line(self):
        r = DummyRepos()
        parsed = r._parse_repo_line(
            "deb [arch=amd64 signed-by=/usr/share/keyrings/foo.gpg] https://deb.debian.org/debian trixie main contrib non-free-firmware",
            "/etc/apt/sources.list",
            1,
        )
        self.assertIsNotNone(parsed)
        self.assertTrue(parsed["enabled"])
        self.assertEqual(parsed["type"], "deb")
        self.assertEqual(parsed["url"], "https://deb.debian.org/debian")
        self.assertEqual(parsed["suite"], "trixie")
        self.assertEqual(parsed["comps"], "main contrib non-free-firmware")

        disabled = r._parse_repo_line(
            "# deb http://packages.linuxmint.com zena main upstream import",
            "/etc/apt/sources.list.d/official-package-repositories.list",
            2,
        )
        self.assertIsNotNone(disabled)
        self.assertFalse(disabled["enabled"])
        self.assertEqual(disabled["suite"], "zena")

    def test_parse_and_toggle_deb822_sources(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            orig_backup = core.BACKUP_ROOT
            core.BACKUP_ROOT = tmp_path / "backups"
            try:
                src_file = tmp_path / "debian.sources"
                src_file.write_text(
                    "Types: deb deb-src\n"
                    "URIs: http://deb.debian.org/debian\n"
                    "Suites: trixie trixie-updates\n"
                    "Components: main contrib non-free-firmware\n"
                    "Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg\n",
                    encoding="utf-8",
                )
                r = DummyRepos()
                stanzas = r._parse_deb822_file(str(src_file))
                self.assertEqual(len(stanzas), 1)
                self.assertTrue(stanzas[0]["enabled"])
                self.assertEqual(stanzas[0]["suite"], "trixie trixie-updates")

                # Disable stanza
                r._deb822_set_enabled(stanzas[0], enable=True)
                stanzas_after = r._parse_deb822_file(str(src_file))
                self.assertFalse(stanzas_after[0]["enabled"])

                # Re-enable stanza
                r._deb822_set_enabled(stanzas_after[0], enable=False)
                stanzas_reenabled = r._parse_deb822_file(str(src_file))
                self.assertTrue(stanzas_reenabled[0]["enabled"])
            finally:
                core.BACKUP_ROOT = orig_backup


if __name__ == "__main__":
    unittest.main()
