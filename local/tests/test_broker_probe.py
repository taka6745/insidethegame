"""The probe precondition is read-only, including a replay started mid-check."""
import sys
import unittest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from broker_probe import require_idle_replay


class BrokerProbeGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_idle_and_finished_replay_are_allowed_without_writes(self):
        for status in ('ready', 'finished'):
            with self.subTest(status=status):
                requests = []
                def handler(request):
                    requests.append((request.method, request.url.path))
                    return httpx.Response(200, json={'status': status})
                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                    await require_idle_replay(client, 'http://backend/')
                self.assertEqual(requests, [('GET', '/lab/state')])

    async def test_replay_started_during_probe_fails_explicitly(self):
        states = iter(('ready', 'running'))
        requests = []
        def handler(request):
            requests.append(request.method)
            return httpx.Response(200, json={'status': next(states)})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await require_idle_replay(client, 'http://backend')
            with self.assertRaisesRegex(RuntimeError, 'require an idle replay'):
                await require_idle_replay(client, 'http://backend')
        self.assertEqual(requests, ['GET', 'GET'])

    async def test_unreachable_state_is_not_assumed_idle(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(503))) as client:
            with self.assertRaises(httpx.HTTPStatusError):
                await require_idle_replay(client, 'http://backend')


if __name__ == '__main__':
    unittest.main()
