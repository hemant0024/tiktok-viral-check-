# Superseded

`daily.json` ran ads and UGC in one graph. It is kept only for reference.

Do not import it alongside `ads.json` / `ugc.json`: both would write RADAR
snapshots for the same videos on the same day, and duplicated snapshots corrupt
the velocity history the whole viral signal is built on.

Use `../ugc.json` and `../ads.json`.
