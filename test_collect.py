"""Offline tests for collect.py (network faked). Run: python test_collect.py"""
import unittest
from unittest import mock

import collect as c

T0 = 1794795207  # a fixed "post time"


def post(i, text, ts=T0, who="nullsxyz", reply_to=None, media=False):
    s = {"id": str(i), "text": text, "created_timestamp": ts, "url": f"https://x.com/{who}/status/{i}",
         "author": {"screen_name": who, "name": who, "avatar_url": f"https://pbs.twimg.com/{who}_normal.jpg"}}
    if reply_to:
        s["replying_to"] = {"screen_name": reply_to[0], "status": str(reply_to[1])}
    if media:
        s["media"] = {"all": [{"type": "photo"}]}
    return s


QUEST = post(100, "« ready player 001 · @rhea_finance »\n\n▸ side quest: guess their favorite childhood game \n"
                  "hint: 🌀🥭\n\nfirst correct reply → 1 MEMORY CARD \nplayer 001 bonus → 1 NULLS LIST party invite")


class Parsing(unittest.TestCase):
    def test_quest_fields(self):
        q = c.parse_quest(QUEST)
        self.assertEqual((q["title"], q["prompt"], q["hint"], q["partner"]),
                         ("ready player 001 · @rhea_finance", "guess their favorite childhood game", "🌀🥭", "rhea_finance"))
        self.assertEqual(len(q["rewards"]), 2)

    def test_announcement_is_not_a_quest(self):
        self.assertIsNone(c.QUEST_RE.search("some side quests are worth taking."))

    def test_award_detection(self):
        self.assertTrue(c.is_award(post(1, "@someone « memory card unlocked »")))
        self.assertFalse(c.is_award(post(2, "@someone « 🎶🎶🎶 »")))

    def test_classify(self):
        cases = {
            "quest": post(5, "@nullsxyz @rhea_finance Crash Bandicoot", reply_to=("nullsxyz", 100)),
            "build": post(6, "I ve made a @nullsxyz runner game. Play here: https://nullsrunner.xyz"),
            "art": post(7, "My first fan art for the world of nulls", media=True),
            "post": post(8, "it seems connected to the same team that built zkSNARKS. apply https://nulls.world/apply"),
        }
        for kind, p in cases.items():
            self.assertEqual(c.classify(p, {"100"}), kind, p["text"])
        self.assertEqual(c.classify(post(9, "So I finally sat down and built something. Meet NULLSCADE"), set()), "build")

    def test_mentions_stripped(self):
        self.assertEqual(c.strip_mentions("@nullsxyz @rhea_finance Crash Bandicoot"), "Crash Bandicoot")


class Collect(unittest.TestCase):
    def run_collect(self, feed_pages, statuses, ledger=None, nl=None):
        pages = list(feed_pages)

        def get_json(url, tries=4):
            if "/search" in url:
                return pages.pop(0) if pages else None
            if "/status/" in url:
                return {"status": statuses.get(url.rsplit("/", 1)[1])}
            if "/profile/nullslist" in url:
                return {"results": nl or []}
            return None
        with mock.patch.object(c, "get_json", get_json), mock.patch.object(c.time, "sleep", lambda s: None):
            return c.collect(ledger or {})

    def test_award_resolved_and_quest_solved_with_time(self):
        win = post(101, "@nullsxyz @rhea_finance Crash Bandicoot", ts=T0 + 35, who="vinniedotzec", reply_to=("nullsxyz", 100))
        award = post(102, "@vinniedotzec @rhea_finance « memory card unlocked »", ts=T0 + 140, reply_to=("vinniedotzec", 101))
        nl = [{"text": f"« PLAYER #{n:03d} REGISTERED »\n\n@p{n}, you're on", "created_timestamp": T0 + n}
              for n in [114, 113, 112] + list(range(100, 24, -1))]  # announcing starts at #025; #101-#111 skipped
        L = self.run_collect([{"results": [award, QUEST]}], {"101": win}, nl=nl)
        a = L["awards"][0]
        self.assertEqual((a["winner"], a["for"]["kind"], a["avatar"]), ("vinniedotzec", "quest", "https://pbs.twimg.com/vinniedotzec_200x200.jpg"))
        q = L["quests"][0]
        self.assertEqual((q["solved_by"], q["answer"], q["solve_secs"]), ("vinniedotzec", "Crash Bandicoot", 35))
        # #001-#024 joined before announcements began (counted); #101-#111 were skipped (not counted)
        skipped = list(range(101, 112))
        self.assertEqual((L["list"]["count"], L["list"]["newest"], L["list"]["skipped"], L["list"]["latest"]),
                         (114 - len(skipped), 114, skipped, "p114"))
        self.assertEqual(L["scanned_to"], "102")

    def test_failed_page_does_not_advance_scan_point(self):
        """A flaky FxTwitter page must not mark unseen history as scanned."""
        cursor_page = {"results": [post(300, "hi", ts=T0)], "cursor": {"bottom": "x"}}
        L = self.run_collect([cursor_page, None], {}, ledger={"scanned_to": "5"})
        self.assertEqual(L["scanned_to"], "5")

    def test_unresolved_award_retried_next_run_even_if_no_longer_in_feed(self):
        award = post(202, "@a « memory card unlocked »", reply_to=("a", 201))
        L1 = self.run_collect([{"results": [award]}], {"201": None})
        self.assertIsNone(L1["awards"][0]["for"])
        self.assertEqual(L1["scanned_to"], "202")  # scan point moved past it...
        newer = post(203, "gm all", ts=T0 + 9)
        L2 = self.run_collect([{"results": [newer, award]}], {"201": post(201, "gm", who="a")}, ledger=L1)
        self.assertEqual(L2["awards"][0]["for"]["text"], "gm")  # ...but it still gets resolved
        L3 = self.run_collect([{"results": [post(204, "later", ts=T0 + 99)]}], {}, ledger={**L1, "scanned_to": "203"})
        self.assertIsNone(L3["awards"][0]["for"])  # fetch fails again -> still pending, not dropped


if __name__ == "__main__":
    unittest.main(verbosity=2)
