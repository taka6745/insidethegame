"""Non-destructive ETL pipeline check: DAB GraphQL answers every entity and narrative-live is readable."""
import json
import time
from urllib.request import Request, urlopen

from azure.servicebus import ServiceBusClient

from settings import ETL_GRAPHQL, SERVICEBUS_CONNECTION

QUERY = '''{ matches(first: 1) { items { matchId } } rawEvents(first: 1) { items { id } }
  keyEvents(first: 1) { items { id } } minuteStats(first: 1) { items { timeMin } }
  matchStatsAsOfs(first: 1) { items { minuteLabel } }
  matchTeams(first: 1) { items { contestantId } } matchPlayers(first: 1) { items { playerId } }
  matchWatermarks(first: 1) { items { seq spadlSeq } } statDefinitions(first: 1) { items { statId } }
  spadlActions(first: 1) { items { actionId typeName finalSeq } }
  possessionSamples(first: 1) { items { sampleId } }
  canonicalEvents(first: 1) { items { seq eventId revision eventType qualifiers } }
  executeStatsAtSeq(matchId: "etl-stream-check", seq: 0) { statId } }'''


def graphql():
    request = Request(ETL_GRAPHQL, json.dumps({'query': QUERY}).encode(), {'Content-Type': 'application/json'})
    with urlopen(request, timeout=10) as response:
        body = json.load(response)
    assert not body.get('errors'), body['errors']
    return {k: len(v if isinstance(v, list) else v['items']) for k, v in body['data'].items()}


def main():
    deadline = time.monotonic() + 120
    while True:  # DAB takes a few seconds to load its schema after start.
        try:
            print('PASS ETL GraphQL (Data API builder 2.1.5):', graphql())
            break
        except Exception:
            if time.monotonic() > deadline:
                raise
            time.sleep(3)
    with ServiceBusClient.from_connection_string(SERVICEBUS_CONNECTION) as client, \
            client.get_subscription_receiver('match-notifications', 'narrative-live') as receiver:
        print(f'PASS narrative-live subscription readable ({len(receiver.peek_messages(max_message_count=10))} peeked)')


if __name__ == '__main__':
    main()
