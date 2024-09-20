#!/usr/bin/env python

required_stages = 18
first_stages = [1, 10]
workers = first_stages + [5] * (required_stages - len(first_stages))

print("""name: build

on:
  workflow_dispatch:
  push:

env:
  AGG: /home/runner/apt_repo_dependencies
  DISTRIBUTION: ubuntu

jobs:
  stage-1:
    runs-on: ubuntu-22.04
    outputs:
      workers: ${{ steps.worker.outputs.workers }}
    steps:
      - name: Check out the repo
        uses: actions/checkout@v4
      - name: Clone sources
        run: |
          sudo add-apt-repository -y ppa:v-launchpad-jochen-sprickerhof-de/sbuild
          sudo apt update
          DEBIAN_FRONTEND=noninteractive sudo apt install -y vcstool catkin
          mkdir src
          vcs import --recursive --shallow --input sources.repos src
      - name: Extract rosdep keys
        run: |
          for PKG in $(catkin_topological_order --only-names); do
            printf "%s:\\n  %s:\\n  - %s\\n" "$PKG" "${{ env.DISTRIBUTION }}" "ros-one-$(printf '%s' "$PKG" | tr '_' '-')" | tee -a local.yaml
          done
      - name: List used workers
        id: worker
        run: |
          cat jobs.yaml
          echo "workers=$(cat jobs.yaml | sed -n '/^stage.*:$/ p' | tr -d '\\n')" >> $GITHUB_OUTPUT
      - name: Prepare meta data cache
        run: |
          mkdir -p ${{ env.AGG }}
          mv local.yaml ${{ env.AGG }}/local.yaml
          cp sources.repos ${{ env.AGG }}/sources_specified.repos
      - name: Store meta data cache
        uses: actions/cache/save@v4
        with:
          path: ${{ env.AGG }}
          key: apt-repo-stage-1-${{ github.sha }}-${{ github.run_id }}-${{ github.run_attempt }}
""", end='')

for i, workers in enumerate(workers):
    for j in range(workers):
        print(f"  stage{i}-worker{j}:\n"
              f"    uses: ./.github/workflows/worker.yaml\n"
              f"    if: (always() && !cancelled()) && contains( needs.stage-1.outputs.workers, 'stage{i}-worker{j}' )\n"
              f"    needs: stage{i-1}\n"
              f"    with:\n"
              f"      worker: stage{i}-worker{j}\n"
              f"      depends: stage{i-1}")
    print(f"  stage{i}:\n"
            f"    uses: ./.github/workflows/aggregate-debs.yaml\n"
            f"    if: always() && !cancelled()\n"
            f"    needs: [{', '.join([f'stage{i}-worker{j}' for j in range(workers)])}]\n"
            f"    with:\n"
            f"      stage: {i}")

print(f"""  deploy:
    needs: stage{i}
    if: always() && !cancelled()
    runs-on: ubuntu-22.04
    env:
      ROS_DISTRO: one
      DEB_DISTRO: jammy
    steps:
      - name: get apt packages from last job
        uses: actions/cache/restore@v4
        with:
          path: ${{ env.AGG }}
          key: apt-repo-stage{i}-${{ github.sha }}-${{ github.run_id }}-${{ github.run_attempt }}
          restore-keys: |
            apt-repo-stage{i}-${{ github.sha }}-${{ github.run_id }}
      - name: move packages to repo
        run: |
          mkdir -p /home/runner/apt_repo
          mv ${{ env.AGG }}/* /home/runner/apt_repo/
      - uses: v4hn/ros-deb-builder-action/deploy@rosotest
        with:
          BRANCH: ${{ env.DEB_DISTRO }}-${{ env.ROS_DISTRO }}-unstable
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          SQUASH_HISTORY: true""")
