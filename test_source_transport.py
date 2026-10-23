import os
import http.client
import threading
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import source_transport as transport
from import_broker import allowed, Server, Handler


class TransportTests(unittest.TestCase):
    def test_exact_policy_and_shared_broker(self):
        for url in transport.API_URLS:
            transport.validate(url)
            self.assertTrue(allowed(url))
        for url in ['https://example.com/', 'https://api.github.com/repos/curl/curl/releases/latest?token=x', 'https://archive.ics.uci.edu/api/dataset?id=1', 'https://www.cisa.gov:444/sites/default/files/feeds/known_exploited_vulnerabilities.json', 'https://user:secret@www.cisa.gov/x', 'https://api.github.com/repos/curl/curl/releases/latest#fragment', 'https://github.com/curl/curl']:
            with self.assertRaises(ValueError): transport.validate(url)
            self.assertFalse(allowed(url))

    def test_worker_deadline_and_credential_free_environment(self):
        url = next(iter(transport.API_URLS))
        with patch.dict(os.environ, {'SECRET': 'never-inherit', 'LAB_CONTAINER': '0'}), patch.object(transport.subprocess, 'run', side_effect=subprocess.TimeoutExpired('worker', 25)) as run:
            with self.assertRaises(subprocess.TimeoutExpired): transport.fetch(url, 100)
        arguments = run.call_args.kwargs
        self.assertEqual(arguments['timeout'], 25)
        self.assertNotIn('SECRET', arguments['env'])
        self.assertNotIn('HOME', arguments['env'])
        self.assertIn('-I', run.call_args.args[0])

    def test_output_and_bound_checks(self):
        url = next(iter(transport.API_URLS))
        with patch.dict(os.environ, {'LAB_CONTAINER': '0'}), patch.object(transport.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, stdout=b'ab')):
            self.assertEqual(transport.fetch(url, 2), b'ab')
            with self.assertRaises(ValueError): transport.fetch(url, 1)
        for bound in [True, 0, 25_000_001]:
            with self.assertRaises(ValueError): transport.fetch(url, bound)

    def test_actual_worker_rejects_url_before_network(self):
        path = Path(__file__).with_name('source_fetch_worker.py')
        result = subprocess.run([sys.executable, '-I', str(path)], input=b'{"url":"https://example.com/","bound":1}', capture_output=True, timeout=5, env={'PATH': '/usr/bin:/bin'})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b'')
        self.assertEqual(result.stderr, b'')

    def test_broker_auth_and_capacity(self):
        try:server = Server(('127.0.0.1', 0), Handler)
        except PermissionError as error:raise unittest.SkipTest('Sandbox forbids local listening sockets: '+str(error)) from error
        server.token = 'test-only'
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection(*server.server_address, timeout=2)
            connection.request('POST', '/fetch', body=b'not-json', headers={'Content-Length': '8'})
            response = connection.getresponse()
            self.assertEqual(response.status, 401)
            response.read()
            connection.close()
            # Reserve both slots to deterministically verify admission fails closed.
            self.assertTrue(server.slots.acquire(timeout=2))
            self.assertTrue(server.slots.acquire(timeout=2))
            try:
                connection = http.client.HTTPConnection(*server.server_address, timeout=2)
                connection.request('POST', '/fetch', body=b'{}')
                self.assertEqual(connection.getresponse().status, 503)
                connection.close()
            finally:
                server.slots.release()
                server.slots.release()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_redirect_revalidates(self):
        with self.assertRaises(ValueError):
            transport.Redirects().redirect_request(None, None, 302, '', {}, 'https://example.com/')


if __name__ == '__main__': unittest.main()
