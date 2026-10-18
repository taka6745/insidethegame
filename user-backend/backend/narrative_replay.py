"""Explicit development catch-up; uses the same durable framing service as live ingress."""
import asyncio
import os

from .adapters.narratives import NarrativeHistory
from .narrative_factory import create_narrative_service
from .store import Store


async def main():
    store = Store(os.environ['ACCOUNTS_DATABASE_URL'], os.environ['MATCH_APP_DATABASE_URL'])
    service = create_narrative_service(store, os.getenv('MATCH_ID', 'synthetic-demo'))
    await service.initialize()
    count = await NarrativeHistory(os.environ['NARRATIVE_GRAPHQL_URL']).replay(service)
    print(f'Processed {count} neutral narratives; reconnect viewers for refreshed snapshots.')


if __name__ == '__main__':
    asyncio.run(main())
