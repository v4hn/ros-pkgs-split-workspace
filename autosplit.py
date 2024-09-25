#!/usr/bin/env python
# authored 2024 by Michael 'v4hn' Goerner

from workspace import Workspace
from typing import Dict, Set, List, NamedTuple
from copy import deepcopy
import numpy as np
import binpacking
import sys

SBUILD_OPTIONS = {
    # limit to fewer jobs as free github runners run out of memory with defaults (determined by trial and error)
    "eigenpy": "$dpkg_buildpackage_user_options = ['--jobs=3'];",
    # This entry here entails ompl will run in an isolated job as it's the stage1 bottleneck
    "ompl": "",
}

def stages(ws):
    ws = deepcopy(ws)
    while ws.repositories:
        if "setup_files" in ws.repositories or "ros_environment" in ws.repositories:
            # these two are special because they are needed for the build environment
            stage = [ws.repositories["setup_files"], ws.repositories["ros_environment"]]
        else:
            # find all repositories without build dependencies
            stage = [r for r in ws.repositories.values()
                     if not r.build_depends and not r.test_depends and not r.exec_depends
                     and (not r.bonded or not any(ws.repositories[br].build_depends.union(ws.repositories[br].test_depends, ws.repositories[br].exec_depends) for br in r.bonded))]

        if not stage:
            print("ERROR: unbonded cyclic dependencies detected. Remaining repositories:", file=sys.stderr)
            for r in ws.repositories.values():
                print(f"{r.name}: {r.build_depends} / {r.test_depends} / {r.exec_depends}", file=sys.stderr)
            return

        yield stage

        for r in stage:
            ws.drop_repository(r.name)

if __name__ == '__main__':
    ws = Workspace(sys.argv[1] if len(sys.argv) > 1 else ".")

    def nr_of_workers():
        '''
        defines the number of workers to use for each stage in an infinite generator
        '''
        yield 1 # built requirements cannot be parallelized
        #yield 10 # the first stage contains many independent packages, but eigenpy/ompl delay it anyway
        while True: # do not excessively parallelize (though github allows 20 and possibly throttles)
            #yield 5
            yield 10

    for i, (stage, workers) in enumerate(zip(stages(ws), nr_of_workers())):
        # repositories with special sbuild options are run in isolation
        # TODO: would fail with bonded repositories, but there are no cases of this yet
        extra_jobs = [[repo.name] for repo in stage if repo.name in SBUILD_OPTIONS]

        # "regular" repositories to be assigned to workers
        repos = [repo for repo in stage if repo.name not in SBUILD_OPTIONS]

        # group bonded repositories together in tasks
        tasks = dict()
        while repos:
            # select first repository and its bonds
            repo = repos[0]
            if repo.bonded:
                tasks[repo.name] = [ws.repositories[br] for br in repo.bonded]
            else:
                tasks[repo.name] = [repo]

            # remove all selected repositories from repos
            for r in tasks[repo.name]:
                repos.pop(next(i for i, rr in enumerate(repos) if rr.name == r.name))

        # TODO: record the actual compute time of stages and use it as costs instead of package count
        # TODO: reduce used jobs by merging them to fill current maximum cost of any job
        costs = {t : sum(len(r.packages) for r in tasks[t]) for t in tasks}
        jobs = binpacking.to_constant_bin_number(costs, workers-len(extra_jobs))

        jobs = [[repo.name for task in job for repo in tasks[task]] for job in jobs if job]

        # write out jobs to yaml
        for ji, job in enumerate(jobs+extra_jobs):
            repos_yaml = '[{}]'.format(', '.join(f'"{repo}"' for repo in job))
            print(f"stage{i}-worker{ji}:\n"
                    f"  repositories: {len(job)}\n"
                    f"  packages: {sum([len(ws.repositories[repo].packages) for repo in job])}\n"
                    f"  jobs: {repos_yaml}\n"
                    , end= '')
            if next(iter(job)) in SBUILD_OPTIONS:
                print(f'  sbuild_options: "{SBUILD_OPTIONS[next(iter(job))]}"')
