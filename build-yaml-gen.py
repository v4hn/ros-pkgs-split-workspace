#!/usr/bin/env python

def workers():
  yield 1
  yield 10
  yield 5

workers = [1, 10] + [5] * (17-2)

print("""name: build

on:
  workflow_dispatch:
  push:

# TODO: this is incomplete and needs manual editing after generation
jobs:""")

for i, workers in enumerate(workers):
    for j in range(workers):
        print(f"  stage{i}-worker{j}:\n"
              f"    uses: ./.github/workflows/worker.yaml\n"
              f"    if: success() || failure()") # TODO: skip if there is no work scheduled for this worker
        if i > 0:
            print(f"    needs: stage{i-1}")
        print(f"    with:\n"
              f"      worker: stage{i}-worker{j}")
        if i > 0:
            print(f"      depends: stage{i-1}")
    print(f"  stage{i}:\n"
            f"    uses: ./.github/workflows/aggregate-debs.yaml\n"
            f"    if: always() && !cancelled()\n"
            f"    needs: [{', '.join([f'stage{i}-worker{j}' for j in range(workers)])}]\n"
            f"    with:\n"
            f"      stage: {i}")
