"""A Brief bucket viewers can pick: `neutral:simple:brief` is enabled wherever it exists (templates and match
catalogues), and the Brief option's description asks for one sentence under 20 words so the author keeps it short.
Other Brief twins stay disabled (enable them in /dev/; each enabled bucket is another narrative per step)."""
from psycopg.types.json import Jsonb

BRIEF = 'neutral:simple:brief'
DESCRIPTION = 'One sentence, under 20 words: the point only, no scene-setting.'


def with_brief(document):
    layers = [{**layer, 'options': [{**o, 'description': DESCRIPTION} if o['id'] == 'brief' else o
                                    for o in layer['options']]} if layer['id'] == 'length' else layer
              for layer in document.get('layers', [])]
    buckets = [{**b, 'enabled': True} if b['id'] == BRIEF else b for b in document.get('buckets', [])]
    changed = {**document, 'layers': layers, 'buckets': buckets}
    return None if changed == document else changed


def migrate(conn):
    for table, key in (('audience_templates', 'fixture'), ('audience_catalog', 'match_id')):
        for row in conn.execute(f'SELECT {key} AS id, document FROM {table}').fetchall():
            if (document := with_brief(row['document'])) is not None:
                conn.execute(f'UPDATE {table} SET document = %s, revision = revision + 1 WHERE {key} = %s',
                             (Jsonb(document), row['id']))
