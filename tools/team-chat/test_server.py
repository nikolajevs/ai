import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import server


class RoomTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data = patch.object(server, 'DATA', Path(self.temp.name))
        self.data.start()
        self.state = patch.object(server, 'STATE', {'messages': [], 'busy': False, 'active': None})
        self.state.start()

    def tearDown(self):
        self.state.stop()
        self.data.stop()
        self.temp.cleanup()

    def test_shared_history_and_persistence(self):
        server.add('user', 'Как считаем ток?')
        seen = []
        def answer(agent, prompt):
            seen.append((agent, prompt))
            return 'Ответ ' + agent
        with patch.object(server, 'run_agent', side_effect=answer):
            server.respond('both')
        self.assertIn('Ответ codex', seen[1][1])
        self.assertNotIn('Ответ claude', seen[0][1])
        history = json.loads((server.DATA/'history.json').read_text(encoding='utf-8'))
        self.assertEqual([m['role'] for m in history], ['user', 'codex', 'claude'])
        self.assertFalse(server.STATE['busy'])

    def test_failure_does_not_block_other_participant(self):
        with patch.object(server, 'run_agent', side_effect=[RuntimeError('No login'), 'Работаю']):
            server.respond('both')
        self.assertEqual([m['role'] for m in server.STATE['messages']], ['system', 'claude'])
        self.assertFalse(server.STATE['busy'])

    def test_history_not_silently_truncated(self):
        with self.assertRaises(ValueError):
            server.prompt_for('codex', [{'role':'user','text':'x'*230_000}])

    def test_http_auth_origin_and_busy(self):
        http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        with patch.object(server, 'PORT', http.server_port):
            thread = threading.Thread(target=http.serve_forever, daemon=True)
            thread.start()
            url = f'http://127.0.0.1:{http.server_port}'
            try:
                with self.assertRaises(HTTPError) as error:
                    urlopen(url+'/api/state')
                self.assertEqual(error.exception.code, 403)
                error.exception.close()
                headers = {'Authorization': 'Bearer '+server.TOKEN, 'Content-Type':'application/json'}
                req = Request(url+'/api/state', headers={**headers, 'Origin':'https://example.org'})
                with self.assertRaises(HTTPError) as error:
                    urlopen(req)
                self.assertEqual(error.exception.code, 403)
                error.exception.close()
                req = Request(url+'/api/state', headers=headers)
                with urlopen(req) as response:
                    self.assertEqual(response.status, 200)
                server.STATE['busy'] = True
                req = Request(url+'/api/message', data=b'{"text":"hello"}', headers=headers)
                with self.assertRaises(HTTPError) as error:
                    urlopen(req)
                self.assertEqual(error.exception.code, 409)
                error.exception.close()
            finally:
                http.shutdown()
                http.server_close()


if __name__ == '__main__':
    unittest.main()
