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

        # index of all repositories in workspace
        self.repositories = set([p.repository for p in self.pkgs.values()])
        # list of unselected repository names
        self.remaining = self.repositories.copy()
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

    def complete_rdeps(self, text, line, begidx, endidx):
        return [p for p in self.pkgs if p.startswith(text)]

    def do_rdeps(self, pkg_name):
        "List reverse dependencies of package"
        if pkg_name not in self.pkgs:
            print(f"package '{pkg_name}' is not known")
            return

        pkg = self.pkgs[pkg_name]

        print("reverse dependencies\n"
              "--------------------")

        rdeps = set()
        self.collect_reverse_dependencies(pkg_name, rdeps)
        self.columnize(list(rdeps))
        print()

    def complete_ls(self, text, line, begidx, endidx):
        return self.complete_list(text, line, begidx, endidx)

    def do_ls(self, line):
        "Alias for `list`"
        self.do_list(line)

    def complete_list(self, text, line, begidx, endidx):
        return [t for t in ("packages", "repositories") if t.startswith(text)]

    def do_list(self, line):
        """
        `list <p,r>` List all packages or repositories in the workspace
        Defaults to list packages
        """
        if line.startswith('r'):
            self.columnize(self.repositories)
            print(f'{len(self.repositories)} repositories in workspace')
        else:
            self.columnize(self.pkgs.keys())
            print(f'{len(self.pkgs)} packages in workspace')

    def complete_add(self, text, line, begidx, endidx):
        return [p for p in self.pkgs.keys() if p.startswith(text) and self.pkgs[p].repository in self.remaining]

    def do_add(self, pkg):
        "Add repository of <package> and all dependencies of the repository to the selection"
        try:
            repo = self.pkgs[pkg].repository
        except KeyError:
            print(f"Package '{pkg}' does not exist in workspace")
            return
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
        "Drop <repository> and all reverse dependencies from the selection"
        if repository not in self.selection:
            print(f"{repository} is not selected")
            return

        pkgs = [n for (n,p) in self.pkgs.items() if p.repository == repository]
        rdeps = set()
        for p in pkgs:
            self.collect_reverse_dependencies(p, rdeps)
        repos = set(self.pkgs[p].repository for p in rdeps)
        repos.add(repository)
        repos_to_drop = repos.intersection(self.selection)

        self.selection.difference_update(repos_to_drop)
        self.remaining.update(repos_to_drop)

        self.last_command = self.Command('drop', pkgs=[], repos=repos_to_drop)
        print(f"dropped {repository} and {len(repos_to_drop)-1} other reverse dependent repositories")

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
            print(f"undo does not support '{self.last_command.name}'. Ignoring command.")
            return
        self.last_command = self.Command()

    def do_selection(self, line):
        "print information on current selection"
        selected_pkgs = [n for (n, p) in self.pkgs.items() if p.repository in self.selection]
        self.columnize(sorted(selected_pkgs))
        print(f"{len(selected_pkgs)} packages selected\n")

        self.columnize(sorted(list(self.selection)))
        print(f"{len(self.selection)} repositories selected")

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

    def do_drop_selection(self, line):
        "drop current selection from list. TODO: Currently irreversible"
        print(f"forgetting {len(self.selection)} repositories (and all contained packages)")
        self.pkgs = {n:p for (n,p) in self.pkgs.items() if p.repository not in self.selection}
        self.selection = set()
        self.last_command = self.Command()

    def do_remaining(self, line):
        "print information on all unselected repositories/packages"
        remaining_pkgs = [n for (n, p) in self.pkgs.items() if p.repository in self.remaining]
        self.columnize(sorted(remaining_pkgs))
        print(f"{len(remaining_pkgs)} packages remaining\n")

        self.columnize(sorted(self.remaining))
        print(f"{len(self.remaining)} repositories remaining")

    def collect_reverse_dependencies(self, pkg, rdeps):
        pkg_rdeps = set(
                name for (name,p) in self.pkgs.items()
                if (pkg in (d.name for d in p.pkg['build_depends']))
                or (pkg in (d.name for d in p.pkg['exec_depends']))
                )
        for d in pkg_rdeps:
            if d not in rdeps:
                rdeps.add(d)
                self.collect_reverse_dependencies(d, rdeps)

    def collect_dependencies(self, pkg, deps):
        if pkg in deps:
            return
        deps.add(pkg)
        pkg_deps = set()
        pkg_deps.update([d.name for d in self.pkgs[pkg].pkg['build_depends'] if d.name in self.pkgs])
        pkg_deps.update([d.name for d in self.pkgs[pkg].pkg['exec_depends'] if d.name in self.pkgs])
        for d in pkg_deps:
            self.collect_dependencies(d, deps)

    def find_all_pkg_in_repository(self, pkg):
        return [n for (n,p) in self.pkgs.items() if p.repository == pkg.repository]


if __name__ == '__main__':
    interface = Interface(sys.argv[1] if len(sys.argv) > 1 else ".")
    while True:
        try:
            interface.cmdloop()
            break
        except KeyboardInterrupt:
            print("^C")
            continue
        except EOFError:
            print("^D")
            break
