# nifty-heatmap-core

Shared Yahoo Finance fetch + gainers/losers computation logic for
[nifty-heatmap-web](https://github.com/abhijeetbishayee-drb/nifty-heatmap-web) and
[nifty-heatmap](https://github.com/abhijeetbishayee-drb/nifty-heatmap).

Not published to PyPI. Both consumers pull this in as a git submodule at
`nifty_heatmap_core/` and import it directly (`import nifty_heatmap_core`) — this lets
the Android app's buildozer build bundle it as plain source under `source.dir` without
depending on python-for-android's ability to pip-install a custom package.

Only the data layer lives here: ticker list, Yahoo Finance fetch, short-name
formatting, NSE URL building, and the off-low/off-high gainers/losers calculation.
Rendering (the web page's JS, the Android app's Kivy widgets) stays in each consumer.
