#!/usr/bin/env python3
"""CLI for the Baseten speech hooks — offline/config checks only.

    python3 -m tank_speech --status            # redacted config status
    python3 -m tank_speech --route "go get the shoe"   # parser preview

No network is attempted and nothing is sent to hardware. Live STT needs
a deployed Baseten streaming model + BASETEN_API_KEY (see README.md);
until then --status honestly reports disabled.
"""

import argparse
import json

from tank_speech.baseten_client import SpeechConfig
from tank_speech.session import SpeechSession, route_transcript


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--route", default="", help="route one transcript (offline)")
    args = ap.parse_args(argv)
    if args.route:
        print(json.dumps(route_transcript(args.route), indent=1))
        return 0
    sess = SpeechSession(SpeechConfig.from_env())
    print(json.dumps(sess.status(), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
