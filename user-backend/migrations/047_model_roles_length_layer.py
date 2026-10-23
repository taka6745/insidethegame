"""Model per role and a length layer.

- `backend_config` row `models`: the model per engine and backend role, switched live under /dev/config/models.
  Empty deployments keep each service's own setting; an existing row (a /dev/ edit) is kept.
- Audience `length` layer (Standard, Brief) next to team and style, in every template and match catalogue that
  lacks it. Existing buckets keep their ids and select Standard, so viewers and profiles resolve as before; a Brief
  twin of each is added disabled (enable it in /dev/ to generate it). The author reads the option's description
  through the bucket framing, like every other layer.
"""
from psycopg.types.json import Jsonb

ROLE = {'deployment': '', 'effort': ''}
# writer and questions are the gpt-6.1-sol deployments (Terraform); luna and mini are the live alternatives.
MODELS = {'deployments': ['writer', 'questions', 'gpt-6-luna', 'gpt-5-mini'],
          'engine': {role: ROLE for role in ('summary', 'compression', 'analyst', 'author')},
          'backend': {role: ROLE for role in ('questions', 'follow_planner', 'replay')}}

LENGTH = {'id': 'length', 'description': 'How long each update should be.', 'options': [
    {'id': 'standard', 'label': 'Standard', 'description': 'The usual length for this audience.', 'in_label': False},
    {'id': 'brief', 'label': 'Brief', 'description': 'Wants the shortest version that still makes the point.'}]}


def with_length(document):
    """The document with the length layer and Brief twins, or None when it already has one."""
    if any(layer['id'] == 'length' for layer in document['layers']):
        return None
    standard = [{**b, 'selections': {**b['selections'], 'length': 'standard'}} for b in document['buckets']]
    taken = {b['id'] for b in standard}
    brief = [{'id': f"{b['id']}:brief", 'selections': {**b['selections'], 'length': 'brief'}, 'enabled': False}
             for b in standard if f"{b['id']}:brief" not in taken]
    return {**document, 'layers': [*document['layers'], LENGTH], 'buckets': (standard + brief)[:48]}


def migrate(conn):
    conn.execute("INSERT INTO backend_config (name, document) VALUES ('models', %s) ON CONFLICT DO NOTHING",
                 (Jsonb(MODELS),))
    for table, key in (('audience_templates', 'fixture'), ('audience_catalog', 'match_id')):
        for row in conn.execute(f'SELECT {key} AS id, document FROM {table}').fetchall():
            if (document := with_length(row['document'])) is not None:
                conn.execute(f'UPDATE {table} SET document = %s, revision = revision + 1 WHERE {key} = %s',
                             (Jsonb(document), row['id']))
