import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import ytmusic_playlist as music

A, B = 'aaaaaaaaaaa', 'bbbbbbbbbbb'
URL = 'https://music.youtube.com/playlist?list=PL0123456789abc'

class PlaylistFixture:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'music'
        self.root.mkdir()
        self.sample = self.base / 'sample.mp3'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        'sine=frequency=440:duration=0.1', str(self.sample)], check=True)
        self.fixture = self.base / 'fixture.json'
        self.calls = self.base / 'calls'
        self.fake = self.base / 'yt-dlp'
        self.fake.write_text('''#!/usr/bin/env python3
import json, os, sys, pathlib, shutil
args=sys.argv[1:]
data=json.loads(pathlib.Path(os.environ['FIXTURE']).read_text())
if data.get('stderr'): print(data['stderr'],file=sys.stderr)
if '--flat-playlist' in args:
    print(json.dumps({'title':data.get('title','Prueba'), 'entries':[{'id':v, 'title':v} for v in data['ids']]}))
    sys.exit(data.get('manifest_exit', 0))
v=args[-1].split('v=')[-1]
with open(os.environ['CALLS'], 'a') as f: f.write(v+'\\n')
if v in data.get('fail', []): sys.exit(7)
out=pathlib.Path(args[args.index('--output')+1].replace('%(title)s','Artist - Song').replace('%(id)s',v).replace('%(ext)s','mp3'))
out.parent.mkdir(parents=True, exist_ok=True)
shutil.copyfile(os.environ['SAMPLE'],out)
sys.exit(data.get('postprocess_exit',0))
''')
        self.fake.chmod(0o755)
        self.env = patch.dict(os.environ, {'YTMUSIC_YT_DLP': str(self.fake),
            'YTMUSIC_RUN_SANITIZER':'0', 'YTMUSIC_COOKIES_BROWSER':'none',
            'YTMUSIC_ITEM_DELAY':'0', 'YTMUSIC_RETRY_SLEEP':'0', 'YTMUSIC_RETRY_COUNT':'1',
            'FIXTURE':str(self.fixture), 'CALLS':str(self.calls), 'SAMPLE':str(self.sample)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.set_fixture([A, B, A])

    def set_fixture(self, ids, **kw):
        self.fixture.write_text(json.dumps(dict(ids=ids, **kw)))

    def existing(self, name):
        p = self.root / 'otra' / name
        p.parent.mkdir(exist_ok=True)
        p.write_bytes(self.sample.read_bytes())
        return p


class PlaylistTests(PlaylistFixture, unittest.TestCase):
    def test_cross_folder_duplicate_order_and_idempotence(self):
        existing = self.existing('Incubus - Drive-' + A + '.mp3')
        result = music.run_playlist(URL, self.root)
        self.assertEqual((result['new'], result['reused'], result['failed']), (1, 1, 0))
        m3u = Path(result['m3u'])
        paths = [(m3u.parent / x).resolve() for x in m3u.read_text().splitlines() if not x.startswith('#')]
        self.assertEqual(paths[0], existing)
        self.assertEqual(paths[2], existing)
        self.assertEqual(len(paths), 3)
        self.assertEqual(self.calls.read_text().splitlines(), [B])
        again = music.run_playlist(URL, self.root)
        self.assertEqual((again['new'], again['reused']), (0, 2))
        self.assertEqual(self.calls.read_text().splitlines(), [B])

    def test_partial_and_retry_only_missing(self):
        self.set_fixture([A, B, A], fail=[B])
        result = music.run_playlist(URL, self.root)
        self.assertFalse(result['complete'])
        self.assertEqual(result['failed_ids'], [B])
        self.assertNotEqual(result['exit_code'], 0)
        self.assertEqual(len(Path(result['m3u']).read_text().splitlines()), 3)
        self.set_fixture([A, B, A])
        again = music.run_playlist(URL, self.root)
        self.assertTrue(again['complete'])
        self.assertEqual(self.calls.read_text().splitlines(), [A, B, B])

    def test_empty_corrupt_partial_and_unverifiable_not_reused(self):
        self.existing('track__' + A + '.mp3.part')
        self.existing('Artist - Song.mp3')
        self.existing('zero-' + A + '.mp3').write_bytes(b'')
        self.existing('corrupt-' + A + '.mp3').write_bytes(b'not audio')
        self.set_fixture([A])
        self.assertEqual(music.run_playlist(URL, self.root)['new'], 1)

    def test_corrupt_destination_does_not_block_replacement(self):
        self.set_fixture([A])
        folder=self.root/'Prueba-PL0123456789abc'; folder.mkdir()
        for name in ['Artist - Song__'+A+'.mp3','audio__'+A+'.mp3']:
            (folder/name).write_bytes(b'broken')
        result=music.run_playlist(URL,self.root)
        self.assertEqual(result['new'],1)
        self.assertEqual(result['exit_code'],0)

    def test_metadata_only_no_audio_download(self):
        r = music.run_playlist(URL, self.root, metadata_only=True)
        self.assertFalse(self.calls.exists())
        self.assertTrue(Path(r['manifest']).is_file())
        self.assertEqual(Path(r['manifest']).read_text().splitlines()[0], 'index\tvideo_id\ttitle\turl')

    def test_manifest_failure_propagates(self):
        self.set_fixture([A], manifest_exit=5)
        with self.assertRaises(music.PlaylistError):
            music.run_playlist(URL, self.root)
        self.assertFalse(self.calls.exists())

    def test_lock_prevents_concurrent_writes(self):
        with music.library_lock(self.root):
            with self.assertRaises(music.PlaylistError):
                music.run_playlist(URL, self.root)

    def test_preserve_audio_after_postprocessor_failure(self):
        self.set_fixture([A], postprocess_exit=7)
        first=music.run_playlist(URL, self.root)
        self.assertEqual(first['new'], 1)
        self.assertNotEqual(first['exit_code'], 0)
        self.assertTrue(first['complete'])
        second=music.run_playlist(URL, self.root)
        self.assertEqual(second['new'], 0)
        self.assertEqual(self.calls.read_text().splitlines(), [A])

    def test_unicode_long_title(self):
        self.set_fixture([A], title='🎵' * 80)
        result=music.run_playlist(URL, self.root)
        self.assertTrue(Path(result['m3u']).is_file())
        self.assertLessEqual(len(Path(result['m3u']).name.encode()), 255)

    def test_sanitized_names_keep_exact_id(self):
        for name in ['01_Track__'+A+'.mp3', 'Artist - Track-'+A+'.mp3']:
            self.assertEqual(music.filename_id(Path(name)), A)
        self.assertIsNone(music.filename_id(Path('Artist - Track-'+A+'x.mp3')))

if __name__ == '__main__': unittest.main()

class CLITests(PlaylistFixture, unittest.TestCase):
    def test_shell_playlist_interface_and_result(self):
        report = self.base / 'result.json'
        with patch.dict(os.environ, {'YTMUSIC_RESULT_FILE':str(report)}):
            done = subprocess.run(['bash', 'ytmusic-rip.sh', URL, str(self.root)], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(report.read_text())['new'], 2)

    def test_single_download_error_returns_nonzero(self):
        self.set_fixture([A], fail=[A])
        done = subprocess.run(['bash', 'ytmusic-rip.sh', 'https://www.youtube.com/watch?v='+A,
                               str(self.root)], capture_output=True, text=True)
        self.assertNotEqual(done.returncode, 0)

class MetadataTests(PlaylistFixture, unittest.TestCase):
    def test_existing_file_with_verified_provenance_tag(self):
        from mutagen.id3 import ID3, WOAS
        file=self.existing('Audio antiguo.mp3')
        tags=ID3(file); tags.add(WOAS(url='https://www.youtube.com/watch?v='+A)); tags.save(file)
        self.set_fixture([A])
        result=music.run_playlist(URL, self.root)
        self.assertEqual((result['new'],result['reused']), (0,1))
        self.assertFalse(self.calls.exists())

    def test_sanitizer_real_rename_and_m3u_final_path(self):
        import sys
        self.set_fixture([A])
        with patch.dict(os.environ, {'YTMUSIC_RUN_SANITIZER':'1',
                'YTMUSIC_SANITIZER_PYTHON':sys.executable, 'YTMUSIC_SANITIZER_ARGS':'--rename'}):
            result=music.run_playlist(URL, self.root)
        self.assertEqual(result['exit_code'],0)
        m3u=Path(result['m3u'])
        audio=m3u.parent/m3u.read_text().splitlines()[1]
        self.assertTrue(audio.is_file())
        self.assertTrue(audio.name.endswith('-'+A+'.mp3'))
        from mutagen.easyid3 import EasyID3
        self.assertEqual(EasyID3(audio)['artist'], ['Artist'])
