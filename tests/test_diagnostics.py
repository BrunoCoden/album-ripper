import contextlib
import io
import json
import unittest
from test_playlist import PlaylistFixture, A, URL
from test_queue import QueueFixture
import ytmusic_playlist as music

class DownloadDiagnosticsTests(PlaylistFixture, unittest.TestCase):
    def test_unavailable_reason_reaches_result_and_log_without_secret_output(self):
        self.set_fixture([A], fail=[A], stderr='ERROR: [youtube] '+A+': Video unavailable. This video is not available\nCookie: PRIVATE_COOKIE_VALUE\n')
        log=io.StringIO()
        with contextlib.redirect_stdout(log):
            result=music.run_playlist(URL,self.root)
        self.assertTrue(any('no disponible' in error.lower() and A in error for error in result['errors']))
        self.assertIn('no disponible',log.getvalue().lower())
        self.assertNotIn('PRIVATE_COOKIE_VALUE',log.getvalue()+json.dumps(result))
        self.assertEqual(result['failed_ids'],[A])

    def test_manifest_error_explains_cause(self):
        self.set_fixture([A], manifest_exit=1, stderr='ERROR: HTTP Error 429: Too Many Requests')
        with self.assertRaisesRegex(music.PlaylistError, '429'):
            music.run_playlist(URL,self.root)

    def test_reason_classification_does_not_infer_unavailable_reason(self):
        cases=[('Video unavailable. This video is not available','no disponible'),
               ('Private video. Sign in if you have access','privado'),
               ('This video is not available in your country','país'),
               ('Sign in to confirm you’re not a bot','autenticación'),
               ('HTTP Error 403: Forbidden','403'),
               ('HTTP Error 429: Too Many Requests','429'),
               ('No space left on device','espacio'),
               ('Permission denied','permisos'),
               ('Connection timed out','tiempo'),
               ('unrecognized message with SECRET','código 7')]
        for raw,expected in cases:
            with self.subTest(raw=raw):
                reason=music.download_failure_reason(raw,7)
                self.assertIn(expected,reason)
                self.assertNotIn('SECRET',reason)

class TelegramDiagnosticsTests(QueueFixture, unittest.TestCase):
    def test_existing_bot_receives_names_and_reasons_for_four_failures(self):
        errors=[title+' ['+str(i)+']: YouTube informa que el video no está disponible.'
                for i,title in enumerate(['Tema uno','Tema dos','Tema tres','Tema cuatro'])]
        (self.spool/'results/1.json').write_text(json.dumps(dict(new=0,reused=48,failed=4,
                failed_ids=['a','b','c','d'],errors=errors,exit_code=1,complete=False)))
        self.bridge.deliver_results()
        for title in ['Tema uno','Tema dos','Tema tres','Tema cuatro']:
            self.assertIn(title,self.api.messages[-1])
        self.assertIn('no está disponible',self.api.messages[-1])
