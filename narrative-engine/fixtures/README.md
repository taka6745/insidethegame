# Recorded-match commentary

**144 manually authored narratives:** twelve video minutes × three team perspectives × four viewer styles. Every version is distinct, short and grounded in the committed synthetic Chelsea–United recording. This is a demo fixture, not runtime LLM output or an actual Premier League result.

- `commentary-text.json`: editable authored prose. Order is home/away/neutral, each simple/casual/experienced/analytical.
- `grf-narratives.json`: bound output with recording hash, observed release cursor, exact evidence and approved stat IDs.
- `../tools/bind_commentary.py`: binds reviewed text to an ETL canonical export. It requires the exact hash that was reviewed and does not create prose.

The recorded result is Chelsea 0–4 Manchester United. Fernandes, Dalot and Mainoo are identified scorers; the second United scorer is unknown and remains unnamed. Names are illustrative simulator slots, with generic abilities. The fixture and tests deliberately avoid inventing cards, corners, xG or shot-on-target classifications.

The runtime returns only enabled audience combinations and already-observed minutes. The final narrative waits for the full-time clock, even when the last event has already arrived. A changed recording or corrected prefix suppresses stale prose. Before rebinding a new match, review **all** prose against its event evidence; the binder cannot validate natural-language claims.
