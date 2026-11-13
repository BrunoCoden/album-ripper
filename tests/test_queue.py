import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from ytmusic_playlist import PlaylistError, normalize_url
from ytmusic_queue import MusicBridge
from ytmusic_worker import check_library, process_one

class FakeAPI:
    def __init__(self): self.messages = []
    def send(self, text): self.messages.append(text)

class QueueFixture:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.spool = self.base / 'spool'
        for name in ['pending','running','results']:
            (self.spool / name).mkdir(parents=True)
        self.api = FakeAPI()
        self.bridge = MusicBridge(self.api, self.spool)
        self.url = 'https://music.youtube.com/playlist?list=PL0123456789abc'


class QueueTests(QueueFixture, unittest.TestCase):
    def test_url_validation(self):
        self.assertEqual(normalize_url(self.url), 'https://www.youtube.com/playlist?list=PL0123456789abc')
        for value in ['http://music.youtube.com/playlist?list=PL0123456789abc',
                      self.url+' '+self.url, self.url+'&list=PLother0000000',
                      'https://music.youtube.com.evil/playlist?list=PL0123456789abc',
                      'https://user@music.youtube.com/playlist?list=PL0123456789abc',
                      'https://music.youtube.com:444/playlist?list=PL0123456789abc',
                      'https://music.youtube.com/playlist?list=../../etc',
                      'https://music.youtube.com/playlist?list=', 'https://youtu.be/aaaaaaaaaaa']:
            with self.subTest(value=value), self.assertRaises(PlaylistError): normalize_url(value)

    def test_enqueue_persist_and_deliver(self):
        self.assertTrue(self.bridge.consume(self.url, 123))
        job = json.loads((self.spool/'pending/123.json').read_text())
        self.assertEqual(job['url'], normalize_url(self.url))
        self.assertNotIn('BOT_TOKEN', job)
        self.assertIn('recibida', self.api.messages[-1].lower())
        (self.spool/'results/123.json').write_text(json.dumps({'new':1,'reused':2,'failed':1,
            'failed_ids':['aaaaaaaaaaa'], 'complete':False,'exit_code':1,'errors':[]}))
        MusicBridge(self.api, self.spool).deliver_results()
        self.assertIn('Nuevos: 1', self.api.messages[-1])
        self.assertIn('parcial', self.api.messages[-1])
        self.assertFalse((self.spool/'results/123.json').exists())

    def test_invalid_url_does_not_queue(self):
        self.bridge.consume('/musica https://evil.invalid/?list=PL0123456789abc', 1)
        self.assertEqual(list((self.spool/'pending').iterdir()), [])
        self.assertIn('inválido', self.api.messages[-1])

    def test_missing_library_no_creation(self):
        root = self.base/'absent'
        with self.assertRaises(PlaylistError): check_library(root, self.base, 'uuid')
        self.assertFalse(root.exists())

    def test_wrong_mount_aborts(self):
        root = self.base/'music'; root.mkdir()
        response = {'filesystems':[{'target':'/','uuid':'wrong'}]}
        with patch('ytmusic_worker.mount_info', return_value=response), self.assertRaises(PlaylistError):
            check_library(root, self.base, 'expected')
        self.assertEqual(list(root.iterdir()), [])

    def test_systemd_library_bind_mount_same_disk_is_accepted(self):
        root = self.base/'music'; root.mkdir()
        def info(path):
            return {'filesystems':[{'target':str(path), 'uuid':'expected'}]}
        with patch('ytmusic_worker.mount_info', side_effect=info):
            check_library(root, self.base, 'expected')

    def test_permission_failure_aborts(self):
        root = self.base/'music'; root.mkdir()
        response = {'filesystems':[{'target':str(self.base),'uuid':'expected'}]}
        with patch('ytmusic_worker.mount_info', return_value=response), patch('ytmusic_worker.os.access', return_value=False):
            with self.assertRaises(PlaylistError): check_library(root, self.base, 'expected')
        self.assertEqual(list(root.iterdir()), [])

    def test_worker_checks_before_invoking_downloader(self):
        self.bridge.consume(self.url, 1)
        config = {'library':str(self.base/'missing'), 'mount':str(self.base), 'uuid':'expected',
                  'script':'/does/not/exist', 'spool':str(self.spool)}
        with patch('ytmusic_worker.subprocess.run') as run:
            self.assertTrue(process_one(config))
            run.assert_not_called()
        result=json.loads((self.spool/'results/1.json').read_text())
        self.assertNotEqual(result['exit_code'],0)
        self.assertIn('biblioteca', result['errors'][0])

class ExistingBotTests(QueueFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        spec=importlib.util.spec_from_file_location('health_bot', 'deploy/server-check-telegram.py')
        self.module=importlib.util.module_from_spec(spec); spec.loader.exec_module(self.module)
        self.running=threading.Event(); self.release=threading.Event()
        self.addCleanup(self.release.set)
        def health(): self.running.set(); self.release.wait(5)
        self.bot=self.module.CommandBot(self.api, 42, 'mybot', self.base/'offset', health, music=self.bridge)

    def update(self, text, sender=42, chat=42, kind='private', uid=1):
        return {'update_id':uid, 'message': {'date':int(time.time()),'text':text,
                'chat':{'id':chat,'type':kind},'from':{'id':sender,'is_bot':False}}}

    def test_unauthorized_and_group_not_queued(self):
        self.bot.consume(self.update(self.url, sender=7))
        self.bot.consume(self.update(self.url, kind='group', uid=2))
        self.assertEqual(list((self.spool/'pending').iterdir()), [])
        self.assertEqual(self.api.messages, [])

    def test_health_stays_available_and_music_queues_during_health(self):
        self.bot.consume(self.update('/salud'))
        self.assertTrue(self.running.wait(1))
        self.bot.consume(self.update(self.url, uid=2))
        self.assertTrue((self.spool/'pending/2.json').exists())
        self.bot.consume(self.update('/ayuda', uid=3))
        self.assertIn('/salud', self.api.messages[-1])
        self.assertIn('/musica', self.api.messages[-1])

class WorkerExecutionTests(QueueFixture, unittest.TestCase):
    def test_worker_resume_uses_argv_and_excludes_token(self):
        root = self.base/'music'; root.mkdir()
        script=self.base/'download script'
        script.write_text('''#!/usr/bin/env python3
import json,os,pathlib,sys
assert len(sys.argv)==3
assert sys.argv[1].startswith('https://www.youtube.com/playlist?list=')
assert pathlib.Path(sys.argv[2]).is_dir()
assert 'BOT_TOKEN' not in os.environ
pathlib.Path(os.environ['YTMUSIC_RESULT_FILE']).write_text(json.dumps(dict(new=1,reused=1,failed=0,failed_ids=[],complete=True,exit_code=0,errors=[],m3u='test.m3u')))
''')
        script.chmod(0o755)
        self.bridge.consume(self.url, 123)
        (self.spool/'pending/123.json').rename(self.spool/'running/123.json')
        config={'library':str(root),'mount':str(self.base),'uuid':'expected',
                'script':str(script),'spool':str(self.spool)}
        mount={'filesystems':[{'target':str(self.base),'uuid':'expected'}]}
        with patch('ytmusic_worker.mount_info', return_value=mount), patch.dict(os.environ, {'BOT_TOKEN':'SECRET'}):
            self.assertTrue(process_one(config))
        result=json.loads((self.spool/'results/123.json').read_text())
        self.assertEqual(result['exit_code'],0)
        self.assertEqual(result['new'],1)
        self.assertFalse((self.spool/'running/123.json').exists())
        self.assertFalse(process_one(config))

    @unittest.skipIf(os.geteuid()==0, 'Real permission test requires an unprivileged user')
    def test_real_permissions_fail_without_creating_files(self):
        root=self.base/'music'; root.mkdir(); root.chmod(0o555)
        mount={'filesystems':[{'target':str(self.base),'uuid':'expected'}]}
        try:
            with patch('ytmusic_worker.mount_info', return_value=mount), self.assertRaises(PlaylistError):
                check_library(root, self.base, 'expected')
            self.assertEqual(list(root.iterdir()), [])
        finally:
            root.chmod(0o755)
