import os
from pathlib import Path
import subprocess
import tempfile
import unittest

class ActivationTests(unittest.TestCase):
    def test_restart_or_worker_failure_restores_receiver(self):
        for failure in ['restart', 'enable', 'none']:
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root=Path(directory); backup=root/'backup'; backup.mkdir()
                original=root/'receiver.py'; original.write_text('new receiver')
                dropin=root/'music.conf'; dropin.write_text('new dropin')
                (backup/'server-check-telegram.py').write_text('old receiver')
                calls=root/'calls'
                systemctl=root/'systemctl'
                systemctl.write_text('''#!/usr/bin/env python3
import os,sys,pathlib
p=pathlib.Path(os.environ['CALLS'])
old=p.read_text() if p.exists() else ''
args=' '.join(sys.argv[1:])
p.write_text(old+args+'\\n')
if sys.argv[1]==os.environ['FAIL'] and args not in old.splitlines(): sys.exit(1)
''')
                systemctl.chmod(0o755)
                sleep=root/'sleep'; sleep.write_text('#!/bin/sh\nexit 0\n'); sleep.chmod(0o755)
                env=dict(os.environ,PATH=str(root)+':'+os.environ['PATH'], CALLS=str(calls),FAIL=failure)
                result=subprocess.run(['bash','-c', 'set -e; source deploy/activate.sh; activate_services "$1" "$2" "$3"',
                    'test',str(original),str(dropin),str(backup)],env=env,capture_output=True,text=True)
                if failure=='none':
                    self.assertEqual(result.returncode,0,result.stderr)
                    self.assertEqual(original.read_text(),'new receiver')
                else:
                    self.assertNotEqual(result.returncode,0)
                    self.assertEqual(original.read_text(),'old receiver',result.stderr)
                    self.assertFalse(dropin.exists())
                    self.assertIn('restart server-check-telegram.service',calls.read_text())
