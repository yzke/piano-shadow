import unittest
from pathlib import Path
from unittest.mock import patch

from transcription import TranscriptionWorker


class TranscriptionBridgeTests(unittest.TestCase):
    def test_pythonw_bridge_uses_console_python(self):
        executable = Path(r"C:\Example\Scripts\pythonw.exe")
        with patch.object(Path, "exists", return_value=True):
            self.assertEqual(
                TranscriptionWorker._bridge_python_executable(executable),
                Path(r"C:\Example\Scripts\python.exe"),
            )

    def test_console_python_bridge_is_preserved(self):
        executable = Path(r"C:\Example\Scripts\python.exe")
        self.assertEqual(
            TranscriptionWorker._bridge_python_executable(executable),
            executable,
        )
