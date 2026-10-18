"""Integration probes share the demo narrative cursor and require an idle replay."""


async def require_idle_replay(http, backend_url):
    response = await http.get(backend_url.rstrip('/') + '/lab/state')
    response.raise_for_status()
    if response.json()['status'] == 'running':
        raise RuntimeError(
            'Broker integration probes require an idle replay. Wait for the match to finish '
            'and run the probes serially. This check does not stop or reset the viewer.'
        )
