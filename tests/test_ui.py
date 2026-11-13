import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
from test_playlist import PlaylistFixture, A, URL

class UITests(PlaylistFixture, unittest.TestCase):
    def test_gui_reports_downloader_result(self):
        zenity=self.base/'zenity'
        zenity.write_text('''#!/usr/bin/env python3
import os,sys,pathlib
with open(os.environ['UI_CALLS'],'a') as f: f.write(sys.argv[1]+'\\n')
if '--entry' in sys.argv: print(os.environ['UI_URL'])
if '--progress' in sys.argv: sys.stdin.read()
if '--question' in sys.argv: sys.exit(1)
''')
        zenity.chmod(0o755)
        calls=self.base/'ui_calls'
        for fail in [False,True]:
            with self.subTest(fail=fail):
                self.set_fixture([A],fail=[A] if fail else [])
                calls.write_text('')
                destination=self.base/('fail' if fail else 'ok')
                with patch.dict(os.environ,{'PATH':str(self.base)+':'+os.environ['PATH'],
                      'UI_CALLS':str(calls),'UI_URL':URL,'YTMUSIC_OUTPUT_DIR':str(destination)}):
                    result=subprocess.run(['bash','ytmusic-rip-ui.sh'],capture_output=True,text=True,timeout=30)
                self.assertEqual(result.returncode,1 if fail else 0,result.stderr)
                self.assertIn('--error' if fail else '--question',calls.read_text().splitlines())
