#!/usr/bin/env python
# authored 2023 by Michael 'v4hn' Goerner

import catkin_pkg.packages
import sys
import os
import subprocess
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

    def columnize(self, entries, columns= 0 ):
        if columns == 0:
            columns = os.get_terminal_size().columns-1
        super().columnize(list(entries), columns)

    def __init__(self, ws):
        if ws.endswith('/'):
            ws = ws[:len(ws)-1]
        self.ws = ws
        cut_prefix = 0 if ws == "." else len(ws)+1

        self.Pkg = namedtuple('Pkg', ['path', 'pkg', 'repository'])

        # index of all packages in workspace
        self.pkgs = {pkg['name']: self.Pkg(path, pkg, get_repository(Path(ws)/path)[cut_prefix:]) for (path, pkg) in catkin_pkg.packages.find_packages(ws).items()}

        # list of unselected repository names
        self.remaining = set([p.repository for p in self.pkgs.values()])

        # selected repository names
        self.selection = set()

        # keep last action around to support undo
        self.Command = namedtuple('Command', ['name', 'pkgs', 'repos'], defaults=["", [], []])
        self.last_command = self.Command()

        super().__init__(completekey='tab')
        self.do_list("")

    def precmd(self, line):
        if line == 'EOF':
            sys.exit(0)
        return line

    def complete_inspect(self, text, line, begidx, endidx):
        return [p for p in self.pkgs if p.startswith(text)]

    def do_inspect(self, pkg_name):
        "Inspect a package showing its dependencies and repository"
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
        header = f"others in repository {pkg.repository}"
        print(header + "\n" + ("-" * len(header)))
        self.columnize(list(set(siblings).difference([pkg_name])))
        print()

    def do_list(self, line):
        "List all packages in the workspace"
        self.columnize(self.pkgs.keys())
        print(f'{len(self.pkgs)} packages in workspace')

    def complete_add(self, text, line, begidx, endidx):
        return [p for p in self.pkgs.keys() if p.startswith(text) and self.pkgs[p].repository in self.remaining]

    def do_add(self, pkg):
        "Add repository of <package> and all dependencies of the repository to the selection"
        repo = self.pkgs[pkg].repository
        if repo in self.selection:
            print(f"'{repo}' containing package {pkg} was already added")
            return

        pkg_deps = set()
        for sibling in [n for (n, p) in self.pkgs.items() if p.repository == repo]:
            self.collect_dependencies(sibling, pkg_deps)
        repos = set([self.pkgs[p].repository for p in pkg_deps]).union([repo])

        new_repos = sorted(repos.difference(self.selection))
        self.selection.update(new_repos)
        self.remaining.difference_update(new_repos)

        self.last_command = self.Command('add', pkgs= [], repos = new_repos)
        self.columnize(new_repos)
        print(f"added {len(new_repos)} repositories to selection")

    def complete_drop(self, text, line, begidx, endidx):
        return [p for p in self.selection if p.startswith(text)]

    def do_drop(self, repository):
        "Drop <repository> and all inverse dependencies from the selection"
        if repository not in self.selection:
            print(f"{repository} is not selected")
            return

        self.selection.remove(repository)
        self.remaining.add(repository)
        print("TODO: drop all downstream dependencies, otherwise state is inconsistent")

        self.last_command = self.Command('drop', pkgs=[], repos=[repository])
        print(f"dropped repository {repository}")

    def do_undo(self, line):
        "Undo last add or drop command"
        if self.last_command.name == '':
            print(f"there is no command to undo")
        print(f"undo {self.last_command.name}: ", end='')
        if self.last_command.name == 'add':
            self.selection = self.selection.difference(self.last_command.repos)
            self.remaining.update(self.last_command.repos)
            print(f"removed {len(self.last_command.repos)} repositories from selection again.")
        elif self.last_command.name == 'drop':
            self.remaining = self.remaining.difference(self.last_command.repos)
            self.selection.update(self.last_command.repos)
            print(f"added {len(self.last_command.repos)} repositories to selection again.")
        else:
            print(f"TODO: undo does not support '{self.last_command.name}'. Ignoring command.")
            return
        self.last_command = self.Command()

    def do_selection(self, line):
        "print information on current selection"
        selected_pkgs = [n for (n, p) in self.pkgs.items() if p.repository in self.selection]
        self.columnize(sorted(selected_pkgs))
        print(f"{len(selected_pkgs)} packages selected\n")

        self.columnize(sorted(list(self.selection)))
        print(f"{len(self.selection)} repositories selected")

    # TODO: forget repositories in selection
    # TODO: allow selection of explicitly parallel groups

    def do_export(self, line):
        "export selection to <argument>.repos file"
        with open(f'{line}.repos', 'w') as file:
            file.write("repositories:\n")
            ws= Path(self.ws)
            for repository in self.selection:
                version = subprocess.run(
                    ['git', 'symbolic-ref', '--short', 'HEAD'],
                    stdout=subprocess.PIPE,
                    cwd=ws/repository,
                    text=True,
                    ).stdout.strip()
                remote = subprocess.run(
                    'git for-each-ref --format="%(upstream:remotename)" "$(git symbolic-ref -q HEAD)"',
                    shell=True,
                    stdout=subprocess.PIPE,
                    cwd=ws/repository,
                    text=True,
                    ).stdout.strip()
                url = subprocess.run(
                    ['git', 'remote', 'get-url', remote],
                    stdout=subprocess.PIPE,
                    cwd=ws/repository,
                    text=True
                    ).stdout.strip()
                file.write(
                    f"  {repository}:\n"
                    f"    type: git\n"
                    f"    url: {url}\n"
                    f"    version: {version}\n"
                )
            print(f"wrote selection to file {line}.repos")

    def do_remaining(self, line):
        "print information on all unselected repositories/packages"
        remaining_pkgs = [n for (n, p) in self.pkgs.items() if p.repository in self.remaining]
        self.columnize(sorted(remaining_pkgs))
        print(f"{len(remaining_pkgs)} packages remaining\n")

        self.columnize(sorted(self.remaining))
        print(f"{len(self.remaining)} repositories remaining")

    def collect_dependencies(self, pkg, deps):
        pkg_deps = set()
        pkg_deps.update([d.name for d in self.pkgs[pkg].pkg['build_depends'] if d.name in self.pkgs])
        pkg_deps.update([d.name for d in self.pkgs[pkg].pkg['exec_depends'] if d.name in self.pkgs])
        deps.update(pkg_deps)
        for d in pkg_deps:
            if d not in deps:
                deps.update(self.collect_dependencies(d, deps))
        return deps

    def find_all_pkg_in_repository(self, pkg):
        return [n for (n,p) in self.pkgs.items() if p.repository == pkg.repository]


if __name__ == '__main__':
    Interface(sys.argv[1] if len(sys.argv) > 1 else ".").cmdloop()
