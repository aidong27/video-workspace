from pathlib import Path
import os
import subprocess
import unittest


class ProductionBackupScriptTests(unittest.TestCase):
    def test_backup_script_is_syntax_checked_bounded_and_complete(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "ops" / "production-backup"
        content = script.read_text(encoding="utf-8")

        self.assertTrue(os.access(script, os.X_OK))
        subprocess.run(["bash", "-n", str(script)], check=True)
        self.assertIn("systemctl show --property=ActiveState --value", content)
        self.assertIn("must have ActiveState=inactive", content)
        self.assertIn("shutil.disk_usage", content)
        self.assertIn("insufficient backup space", content)
        self.assertNotIn("--exclude='./var'", content)
        self.assertIn("archive_host_directory /etc/nginx nginx-config.tar.gz", content)
        self.assertIn(
            "archive_host_directory /etc/cloudflared cloudflared-config.tar.gz",
            content,
        )
        self.assertIn("video-caption-cert-renew.service", content)
        self.assertIn("video-caption-cert-renew.timer", content)
        self.assertIn("archive_host_directory /etc/letsencrypt", content)
        self.assertIn("required host configuration is missing", content)
        self.assertIn("resolve_env_path AUTH_DB_PATH", content)
        self.assertIn("resolve_env_path ASR_USAGE_DB_PATH", content)
        self.assertIn("resolve_env_path JOB_STATE_DB_PATH", content)
        self.assertIn('backup_sqlite "${auth_db_path}" auth.db', content)
        self.assertIn('backup_sqlite "${usage_db_path}" cloud-usage.db', content)
        self.assertIn('backup_sqlite "${job_db_path}" jobs.db', content)
        self.assertIn('destination.execute("PRAGMA quick_check")', content)
        self.assertIn("sha256sum --check --quiet SHA256SUMS", content)
        self.assertNotIn("rm -", content)
        self.assertNotIn("git reset", content)
        self.assertNotIn("source ${APP_DIR}/.env", content)


if __name__ == "__main__":
    unittest.main()
