"""Composition root. The demo never imports the user backend or its fixtures."""
import os
from demo_etl.adapters.recording import RecordingSource
from demo_etl.repositories.history import HistoryRepository
from demo_etl.repositories.stats import StatsRepository
from demo_etl.routes.http import create_app
from demo_etl.services.match import MatchService


def from_env():
    history = HistoryRepository(os.environ['ETL_HISTORY_DATABASE_URL'])
    stats = StatsRepository(os.environ['ETL_STATS_DATABASE_URL'])
    history.initialize()
    stats.initialize()
    path = os.environ.get('DEMO_RECORDING_PATH')
    source = RecordingSource(path) if path else None
    if source:
        history.save_recording(source)
    return create_app(MatchService(history,stats,source))
