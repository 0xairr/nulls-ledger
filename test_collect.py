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
    def run_collect(self, feed_pages, statuses, ledger=None, nl=None, list_down=False, nl_pages=None):
        pages = list(feed_pages)
        nl_pages = list(nl_pages) if nl_pages is not None else None
        self.lookups, self.list_reads = [], 0

        def get_json(url, tries=4):
            if "/search" in url:
                return pages.pop(0) if pages else None
            if "/status/" in url:
                return {"status": statuses.get(url.rsplit("/", 1)[1])}
            if "/profile/nullslist/statuses" in url:
                self.list_reads += 1
                if nl_pages is not None:
                    return nl_pages.pop(0) if nl_pages else None
                return None if list_down else {"results": nl or []}
            if "/profile/" in url:  # avatar lookup
                who = url.rsplit("/", 1)[1]
                self.lookups.append(who)
                if getattr(self, "dead", False):
                    return None  # a renamed / suspended account: FxTwitter 404s
                return {"user": {"avatar_url": f"https://pbs.twimg.com/{who}_normal.jpg"}}
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

    def test_every_player_listed_avatars_reused_and_capped(self):
        win = post(101, "@nullsxyz Crash Bandicoot", ts=T0 + 35, who="vinniedotzec", reply_to=("nullsxyz", 100))
        award = post(102, "@vinniedotzec « memory card unlocked »", ts=T0 + 140, reply_to=("vinniedotzec", 101))
        nl = [{"text": f"« PLAYER #{n:03d} REGISTERED »\n\n@{h}, you're on", "created_timestamp": T0 + n,
               "url": f"https://x.com/nullslist/status/{n}"} for n, h in ((26, "vinniedotzec"), (25, "p25"), (24, "p24"))]
        with mock.patch.object(c, "AVATARS_PER_RUN", 1):
            L1 = self.run_collect([{"results": [award, QUEST]}], {"101": win}, nl=nl)
            self.assertEqual([p["no"] for p in L1["players"]], [24, 25, 26])
            self.assertEqual(self.lookups, ["p24"])  # winner's avatar reused; cap of 1 lookup per run
            self.assertEqual([bool(p["avatar"]) for p in L1["players"]], [True, False, True])
            L2 = self.run_collect([{"results": []}], {}, ledger=L1, nl=nl)
            self.assertEqual(self.lookups, ["p25"])  # next run fills the rest, keeps the ones it has
            self.assertTrue(all(p["avatar"] for p in L2["players"]))

    def test_dead_handles_are_given_up_after_a_few_runs(self):
        nl = [{"text": "« PLAYER #024 REGISTERED »\n\n@gone, you're on", "created_timestamp": T0}]
        L = {}
        with mock.patch.object(c, "AVATARS_PER_RUN", 5):
            for run in range(c.AVATAR_GIVE_UP + 2):
                self.dead = True
                L = self.run_collect([{"results": []}], {}, ledger=L, nl=nl)
                if run < c.AVATAR_GIVE_UP:
                    self.assertEqual(self.lookups, ["gone"], f"run {run} should still try")
                else:
                    self.assertEqual(self.lookups, [], f"run {run} should have given up")
        self.assertEqual(L["players"][0]["avatar_misses"], c.AVATAR_GIVE_UP)

    def reg(self, *nos):
        return [{"text": f"« PLAYER #{n:03d} REGISTERED »\n\n@p{n}, you're on", "created_timestamp": T0 + n} for n in nos]

    def test_new_players_need_only_the_first_page(self):
        """Steady state: page 1 overlaps known players, so the flaky deeper pages are never read."""
        known = {"players": [{"no": n, "handle": f"p{n}", "avatar": f"https://pbs.twimg.com/p{n}.jpg"} for n in (24, 25, 26)]}
        page1 = {"results": self.reg(28, 27, 26, 25), "cursor": {"bottom": "more"}}
        L = self.run_collect([{"results": []}], {}, ledger=known, nl_pages=[page1, None])
        self.assertEqual(self.list_reads, 1)
        self.assertEqual([p["no"] for p in L["players"]], [24, 25, 26, 27, 28])
        self.assertEqual(L["players"][0]["avatar"], "https://pbs.twimg.com/p24.jpg")  # kept, not looked up again
        self.assertEqual((L["list"]["count"], L["list"]["newest"]), (28, 28))

    def test_gap_with_failed_deeper_page_keeps_last_good(self):
        """No overlap on page 1 means a gap; if page 2 fails, don't miscount the gap as skipped."""
        known = {"players": [{"no": 24, "handle": "p24"}], "list": {"count": 24}}
        page1 = {"results": self.reg(40, 39), "cursor": {"bottom": "more"}}
        L = self.run_collect([{"results": []}], {}, ledger=known, nl_pages=[page1, None])
        self.assertEqual((L["players"], L["list"]), (known["players"], known["list"]))

    def test_list_fetch_failure_keeps_last_good_players(self):
        prev = {"players": [{"no": 24, "handle": "p24", "avatar": None}], "list": {"count": 24}}
        L = self.run_collect([{"results": []}], {}, ledger=prev, list_down=True)
        self.assertEqual((L["players"], L["list"]), (prev["players"], prev["list"]))

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
