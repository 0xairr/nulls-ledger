# Memory Card Ledger

**https://0xairr.github.io/nulls-ledger/**

A fan-made tracker for the [NULLS](https://nulls.world) memory cards and the NULLS LIST. Styled
after the PS1 memory card screen their art keeps returning to, where every player's avatar becomes
a 16x16 save icon:

- **Memory card 1:** every « memory card unlocked » the team hands out on X: who earned it, for
  what (side quest, build, art, post) and when.
- **Memory card 2:** every side quest, its hint, who solved it and how fast.
- **Memory card 3:** every player on the NULLS LIST, by number, with a dot on players who also
  hold a memory card.

Made by [@0xAirr](https://x.com/0xAirr). Unofficial and not affiliated with nulls. Everything comes from public posts by
[@nullsxyz](https://x.com/nullsxyz) and [@nullslist](https://x.com/nullslist).

## How it works
- `collect.py` (standard library only) reads @nullsxyz's posts and replies through the public
  [FxTwitter](https://github.com/FixTweet/FxTwitter) API, back to Nov 11 2026 when the cards were
  announced. For each award it loads the post that earned it and sorts it into side quest, build,
  art or post. A quest is solved by the first award given to a reply under it, and the solve time is
  that reply's timestamp minus the quest's.
- **The NULLS LIST** comes from @nullslist's « PLAYER #N REGISTERED » posts. Neither the highest
  number nor the number of posts is the player count: @nullslist only began announcing at #024
  (Oct 29; #001-#023 got in before it existed, shown as "?") and skipped #099. So the count is the
  newest number minus the numbers skipped since announcing began (#114 newest -> 113 players). New
  players appear at the top, so each run reads page 1 and merges; it only pages back on a first
  run or a gap, because FxTwitter's deeper pages often 404 from GitHub's servers.
- **Avatars:** card winners' avatars are reused; others are looked up, at most 30 per run, one
  try each. A handle that fails 3 runs (renamed or suspended) keeps a nulls silhouette.
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
