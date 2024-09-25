#!/usr/bin/env python

import em

required_stages = 19
#first_stages = [1, 10]
#workers = first_stages + [5] * (required_stages - len(first_stages))
first_stages = [1]
workers = first_stages + [10] * (required_stages - len(first_stages))

template = R"""name: build

on:
  workflow_dispatch:
  push:

env:
  AGG: /home/runner/apt_repo_dependencies
  DISTRIBUTION: ubuntu

jobs:
  stage-1:
    runs-on: ubuntu-24.04
    outputs:
      workers: ${{ steps.worker.outputs.workers }}
    steps:
      - name: Check out the repo
        uses: actions/checkout@@v4
      - name: Clone sources
        run: |
          echo 'Acquire::Retries "20";'                  | sudo tee -a /etc/apt/apt.conf.d/80-retries
          echo 'Acquire::Retries::Delay::Maximum "300";' | sudo tee -a /etc/apt/apt.conf.d/80-retries
          echo 'Debug::Acquire::Retries "true";'         | sudo tee -a /etc/apt/apt.conf.d/80-retries
          sudo add-apt-repository -y ppa:v-launchpad-jochen-sprickerhof-de/ros
          sudo apt update
          DEBIAN_FRONTEND=noninteractive sudo apt install -y vcstool catkin
          mkdir src
          vcs import -w 5 --recursive --shallow --input sources.repos src
      - name: Extract rosdep keys
        run: |
          for PKG in $(catkin_topological_order --only-names); do
            printf "%s:\n  %s:\n  - %s\n" "$PKG" "${{ env.DISTRIBUTION }}" "ros-one-$(printf '%s' "$PKG" | tr '_' '-')" | tee -a local.yaml
          done
      - name: List used workers
        id: worker
        run: |
          cat jobs.yaml
          echo "workers=$(cat jobs.yaml | sed -n '/^stage.*:$/ p' | tr -d '\n')" >> $GITHUB_OUTPUT
      - name: Prepare meta data cache
        run: |
          mkdir -p ${{ env.AGG }}
          mv local.yaml ${{ env.AGG }}/local.yaml
          cp sources.repos ${{ env.AGG }}/sources_specified.repos
          mkdir -p ${{ env.AGG }}/.github/workflows
          cp .github/workflows/sync-unstable.yaml ${{ env.AGG }}/.github/workflows/sync-unstable.yaml
      - name: Store meta data cache
        uses: actions/cache/save@@v4
        with:
          path: ${{ env.AGG }}
          key: apt-repo-stage-1-${{ github.sha }}-${{ github.run_id }}-${{ github.run_attempt }}
@[for i, workers in stages]@[for j in range(workers)]
  stage@i-worker@j:
    uses: ./.github/workflows/worker.yaml
    if: (always() && !cancelled()) && contains( needs.stage-1.outputs.workers, 'stage@i-worker@j' )
    needs: stage@(i-1)
    with:
      worker: stage@i-worker@j
      depends: stage@(i-1)@[end for]
  stage@i:
    uses: ./.github/workflows/aggregate-debs.yaml
    if: always() && !cancelled()
    needs: [@[for j in range(workers)]stage@(i)-worker@j, @[end for]]
    with:
      stage: @i
@[end for]
  deploy:
    needs: stage@last_stage
    if: always() && !cancelled()
    runs-on: ubuntu-24.04
    env:
      ROS_DISTRO: one
      DEB_DISTRO: jammy
    steps:
      - name: get apt packages from last job
        uses: actions/cache/restore@@v4
        with:
          path: ${{ env.AGG }}
          key: apt-repo-stage@last_stage-${{ github.sha }}-${{ github.run_id }}-${{ github.run_attempt }}
          restore-keys: |
            apt-repo-stage@last_stage-${{ github.sha }}-${{ github.run_id }}
      - name: move packages to repo
        run: |
          mv ${{ env.AGG }} /home/runner/apt_repo
      - uses: v4hn/ros-deb-builder-action/deploy@@roso-noble
        with:
          BRANCH: ${{ env.DEB_DISTRO }}-${{ env.ROS_DISTRO }}-unstable
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          SQUASH_HISTORY: true
"""


print(em.expand(template, stages=enumerate(workers), last_stage=required_stages-1), end='')
