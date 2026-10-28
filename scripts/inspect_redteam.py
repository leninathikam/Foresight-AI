"""Print a compact breakdown of a red-team report (escapes, soft-issue kinds, attacker usage)."""

from __future__ import annotations

import json
import sys
from collections import Counter

from foresight.artifacts import REPORTS_DIR


def main(name: str) -> None:
    rt = json.loads((REPORTS_DIR / f"{name}.json").read_text(encoding="utf-8"))
    print(f"== {name}: {rt.get('label')}")
    for a in rt["attackers"]:
        print(a["attacker"], json.dumps(a["usage"]))
    for who in [a["attacker"] for a in rt["attackers"]] + ["random_fuzz"]:
        recs = [r for r in rt["records"] if r["attacker"] == who]
        soft = [r for r in recs if r["outcome"] == "soft_escape"]
        kinds = Counter(tuple(r["soft_issues"]) for r in soft)
        cases = Counter(r["case"].split("@")[0] for r in soft)
        print(f"-- {who}: soft kinds {dict(kinds)} by case {dict(cases)}")
    for r in rt["records"]:
        if r["outcome"] == "hard_escape":
            print("HARD", r["attacker"], r["case"], r["round"], r["tactic"], r.get("action"))
            print("     verdict", r["verdict"], "warnings", r["warnings"])
            print("     audit", json.dumps(r["audit"]))
            print("     claim", r["expected_weakness"][:300])


if __name__ == "__main__":
    for n in sys.argv[1:] or ["redteam_v1", "redteam"]:
        main(n)
