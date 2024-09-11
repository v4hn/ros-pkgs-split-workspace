#!/usr/bin/env python
# authored 2024 by Michael 'v4hn' Goerner

from workspace import Workspace
from typing import Dict, Set, List, NamedTuple
from copy import deepcopy
import sys

def stages(ws):
    ws = deepcopy(ws)
    while ws.repositories:
        # find all repository without dependencies
        stage = [r for r in ws.repositories.values() if not r.build_depends]

        if not stage:
            print("ERROR: cyclic dependencies detected. Remaining repositories:\n", ", ".join([r.name for r in ws.repositories]))
            return

        yield stage

        # remove them from the workspace
        for r in stage:
            del ws.repositories[r.name]
        # remove the dependencies from the remaining repositories
        for r in ws.repositories.values():
            r.build_depends.difference_update([r.name for r in stage])
            r.exec_depends.difference_update([r.name for r in stage])

if __name__ == '__main__':
    ws = Workspace(sys.argv[1] if len(sys.argv) > 1 else ".")

    for i, stage in enumerate(stages(ws)):
        stage_sum = sum(len(r.packages) for r in stage)
        print(f"Stage {i}: ({stage_sum} packages / {len(stage)} repositories) {', '.join(r.name for r in stage)}")
