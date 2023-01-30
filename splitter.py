#!/usr/bin/env python
# authored 2023 by Michael 'v4hn' Goerner

import catkin_pkg.packages
import sys
import cmd
from collections import namedtuple
from pathlib import Path

def get_repository(path):
    while not (path / '.git').is_dir():
        path = path.parent
    return path.as_posix()

class Interface(cmd.Cmd):
    intro = ''
    prompt = '# '

    def columnize(self, entries):
        super().columnize(list(entries), 150)

    def __init__(self, ws):
        if ws.endswith('/'):
            ws = ws[:len(ws)-1]
        self.ws = ws
        Pkg = namedtuple('Pkg', ['path', 'pkg', 'repository'])
        self.pkgs = {pkg['name']: Pkg(path, pkg, get_repository(Path(ws)/path)[len(ws)+1:]) for (path, pkg) in catkin_pkg.packages.find_packages(ws).items()}

        self.remaining = set([p.repository for p in self.pkgs.values()])
        self.selection = set()
        self.last_added_repos = [] # undo last add

        super().__init__(completekey='tab')

    def precmd(self, line):
        if line == 'EOF':
            sys.exit(0)
        return line

    def complete_inspect(self, text, line, begidx, endidx):
        return [p for p in self.pkgs if p.startswith(text)]

    def do_inspect(self, pkg_name):
        if pkg_name not in self.pkgs:
            print(f"package '{pkg_name}' is not known")
            return

        pkg = self.pkgs[pkg_name]

        exec_deps = [d.name for d in pkg.pkg['exec_depends'] if d.name in self.pkgs]
        print("exec deps\n"
              "---------")
        self.columnize(exec_deps)
        print()

        build_deps = [d.name for d in pkg.pkg['build_depends'] if d.name in self.pkgs]
        print("build deps\n"
              "----------")
        self.columnize(build_deps)
        print()

        siblings = self.find_all_pkg_in_repository(pkg)
        print(f"others in repository {pkg.repository}\n"
              "--------------------")
        self.columnize(list(set(siblings).difference([pkg_name])))
        print()

    def do_list(self, line):
        print("TODO: only show unselected")
        self.columnize(self.pkgs.keys())
        print(f'\n{len(self.pkgs)} packages in workspace')

    def complete_add(self, text, line, begidx, endidx):
        return [p for p in self.pkgs.keys() if p.startswith(text)]

    def do_add(self, pkg):
        repo = self.pkgs[pkg].repository
        if repo in self.selection:
            print(f"'{repo}' containing package {pkg} was already added")
            return

        pkg_deps = set()
        for sibling in [n for (n, p) in self.pkgs.items() if p.repository == repo]:
            pkg_deps.update(self.collect_dependencies(sibling))
        repos = set([self.pkgs[p].repository for p in pkg_deps]).union([repo])

        new_repos = sorted(repos.difference(self.selection))
        self.selection.update(new_repos)
        self.remaining.difference_update(new_repos)

        self.last_added_repos = new_repos
        self.columnize(new_repos)
        print(f"\nadded {len(new_repos)} repositories to selection")

    def complete_drop(self, text, line, begidx, endidx):
        return [p for p in self.selection if p.startswith(text)]

    def do_drop(self, repository):
        if repository not in self.selection:
            print(f"{repository} is not selected")
            return

        self.selection.remove(repository)
        self.remaining.add(repository)
        print("TODO: drop all downstream dependencies, otherwise state is inconsistent")

    def do_undo(self, line):
        print("TODO: undo drop as well")
        self.selection = self.selection.difference(self.last_added_repos)
        print(f"removed {len(self.last_added_repos)} repositories from selection again.")
        self.last_added_repos = []

    def do_selection(self, line):
        selected_pkgs = [n for (n, p) in self.pkgs.items() if p.repository in self.selection]
        self.columnize(sorted(selected_pkgs))
        print(f"\n{len(selected_pkgs)} packages selected\n")

        self.columnize(sorted(list(self.selection)))
        print(f"\n{len(self.selection)} repositories selected")

    # TODO: export selection in repos file

    def do_remaining(self, line):
        remaining_pkgs = [n for (n, p) in self.pkgs.items() if p.repository in self.remaining]
        self.columnize(sorted(remaining_pkgs))
        print(f"\n{len(remaining_pkgs)} packages remaining\n")

        self.columnize(sorted(self.remaining))
        print(f"\n{len(self.remaining)} repositories remaining")

    def collect_dependencies(self, pkg):
        deps = set()
        deps.update([d.name for d in self.pkgs[pkg].pkg['build_depends'] if d.name in self.pkgs])
        deps.update([d.name for d in self.pkgs[pkg].pkg['exec_depends'] if d.name in self.pkgs])
        rec_deps = set()
        for d in deps:
            rec_deps.update(self.collect_dependencies(d))
        deps.update(rec_deps)
        return deps

    def find_all_pkg_in_repository(self, pkg):
        return [n for (n,p) in self.pkgs.items() if p.repository == pkg.repository]


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("usage: splitter.py <path to workspace>")
        sys.exit(1)
    Interface(sys.argv[1]).cmdloop()
