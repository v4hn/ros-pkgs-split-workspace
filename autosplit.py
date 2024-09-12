#!/usr/bin/env python
# authored 2024 by Michael 'v4hn' Goerner

from workspace import Workspace
from typing import Dict, Set, List, NamedTuple
from copy import deepcopy
import numpy as np
import binpacking
import sys

def stages(ws):
    ws = deepcopy(ws)
    while ws.repositories:
        if "setup_files" in ws.repositories or "ros_environment" in ws.repositories:
            # these two are special because they are needed for the build environment
            stage = [ws.repositories["setup_files"], ws.repositories["ros_environment"]]
        else:
            # find all repository without dependencies
            stage = [r for r in ws.repositories.values() if not r.build_depends and not r.exec_depends]

        # TODO: deal with cycles by merging them into the same job
        if not stage:
            print("ERROR: cyclic dependencies detected. Remaining repositories:\n", ", ".join([r for r in ws.repositories]))
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

    stage_workers = [1, 20] + [5] * 100

    # TODO: split eigenpy (and pinocchio) into separate jobs with less threads
    for i, (stage, workers) in enumerate(zip(stages(ws), stage_workers)):
        stage_sum = sum(len(r.packages) for r in stage)
        jobs = binpacking.to_constant_bin_number({r.name:len(r.packages) for r in stage}, workers)
        jobs = [j for j in jobs if j]
        print(f"- Stage {i}\n"
              f"  - {stage_sum} packages\n"
              f"  - {len(stage)} repositories\n"
              f"  - job load: " + ", ".join([str(np.sum([p for p in j.values()])) for j in jobs]))
        for j in jobs:
            print(f"    - {', '.join(f'{r}({p})' for r, p in j.items())}")
