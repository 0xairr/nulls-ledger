# Memory Card Ledger

**https://0xairr.github.io/nulls-ledger/**

A fan-made tracker for the [NULLS](https://nulls.world) memory cards. It logs every
« memory card unlocked » the team hands out on X (who earned it, for what, and when), every side
quest and how fast it was solved, and the NULLS LIST count. It's styled after the PS1 memory card
screen their art keeps returning to: each winner's avatar becomes a 16x16 save icon.

Made by [@0xAirr](https://x.com/0xAirr). Unofficial and not affiliated with nulls. Everything comes from public posts by
[@nullsxyz](https://x.com/nullsxyz) and [@nullslist](https://x.com/nullslist).

## How it works
- `collect.py` (standard library only) reads @nullsxyz's posts and replies through the public
  [FxTwitter](https://github.com/FixTweet/FxTwitter) API, back to Nov 11 2026 when the cards were
  announced. For each award it loads the post that earned it and sorts it into side quest, build,
  art or post. A quest is solved by the first award given to a reply under it, and the solve time is
  that reply's timestamp minus the quest's.
- `.github/workflows/collect.yml` runs the tests, then the collector, every ~10 minutes, and commits
  `ledger.json` only when something changed. It's incremental: anything that fails to load (FxTwitter
  is flaky from datacenter IPs) is retried on the next run instead of being skipped.
- `index.html` is the whole site: no build step. It reads `ledger.json` from the repo (so updates show
  within minutes without a Pages rebuild) and falls back to the copy next to it.

Card colors aren't public (only the winner sees theirs), so blocks are colored by what the card was
earned for. Awards made outside X replies (DMs, for example) can't be seen.

## Run it yourself
```
python3 test_collect.py   # offline tests
python3 collect.py        # updates ledger.json
python3 -m http.server    # then open http://localhost:8000
```
