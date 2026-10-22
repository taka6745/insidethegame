# Premier League DNA

Every player has a blend. Explore synthetic football events through position-specific playing-style ideas, explainable measurements and evidence.

## Run the prototype

Requires Python 3.10 or newer.

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Select a player, move the match timeline, and switch between the match so far and the last 15 minutes. Inspect the event IDs behind each measurement or download the evidence package.

```bash
python -m unittest discover -s tests -v
```

The app generates English or Spanish insights from evidence. Local mode uses a
calculated summary and needs no Azure credentials. An optional Microsoft connector
selects structured claims, validates them, then renders controlled wording. It has
been tested with simulated responses; live Azure inference remains unverified.
See [Microsoft setup](docs/MICROSOFT_SETUP.md) before enabling paid calls.

## Project vision and development scope

Premier League DNA aims to explain playing-style blends across a team,
using position-specific measurements and references drawn from
Premier League history.

Development begins with central midfielders to establish the analysis
and explainability workflow. The submission target is a broader,
position-aware experience, with additional role groups introduced
as their measurements and reference models are implemented and tested.

Currently implemented: a local experimental explorer for goalkeepers,
centre-backs, full-backs, defensive midfielders (CDM), central midfielders (CM),
attacking midfielders (CAM), wingers and strikers.
Each role has five applicable measurements, three invented archetypes and a
fictional demonstration player. The new role scenarios are separate from the
original notebook dataset; the same player name does not imply the same data.
Goalkeepers use their own measurements and invented reference profiles.

## Interpretation

The dataset is synthetic and the players are fictional. Legend-inspired reference profiles are invented design hypotheses. Scores are independent model outputs, not probabilities, validated historical comparisons or player-quality rankings. Activity dimensions overlap. The ten-sequence display threshold is provisional.

The original exploration is in `notebooks/01_midfield_style_prototype.ipynb` and
its reusable calculations are preserved in `pl_dna/engine.py`. The expanded role
scenarios and calculations are in `pl_dna/roles.py`; the interface is in `app.py`.
These are independent action scenarios, not a possession-consistent simulation
of a complete match. See [build checkpoints](docs/BUILD_PLAN.md) and
[acceptance criteria](docs/ACCEPTANCE.md) for remaining scope and limitations.
