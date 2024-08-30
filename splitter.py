#!/usr/bin/env python
# authored 2023 by Michael 'v4hn' Goerner

import catkin_pkg.packages
import sys
import os
import subprocess
import cmd
from collections import namedtuple
from copy import deepcopy
from pathlib import Path
from typing import Dict, Set, List

def get_repository(path):
    '''
    returns path to root of git repository containing path
    '''
    while not (path / '.git').is_dir():
        path = path.parent
    return path.as_posix()

def get_git_info(path):
    def call(cmd):
        return subprocess.run(
            cmd.split(" "),
            stdout=subprocess.PIPE,
            cwd=path,
            text=True
            ).stdout.strip()
    version = call('git symbolic-ref --short HEAD')
    long_ref = call('git symbolic-ref -q HEAD')
    remote = call(f'git for-each-ref --format=%(upstream:remotename) {long_ref}')
    url = call(f'git remote get-url {remote}')
    if not remote:
        print(f"ERROR: no remote found for {path}")
    return url, version

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

        # index of all packages in workspace
        self.Pkg = namedtuple('Pkg', ['path', 'pkg', 'repository'])
        self.pkgs = {
            pkg['name']: self.Pkg(path, pkg, get_repository(Path(ws)/path)[cut_prefix:])
            for (path, pkg) in catkin_pkg.packages.find_packages(ws).items()
        }

        # index of all repositories in workspace
        self.Repository = namedtuple('Repository', ['name', 'path', 'packages', 'build_depends', 'exec_depends'])
        self.repos= {}
        repository_names = set([p.repository for p in self.pkgs.values()])
        for name in repository_names:
            pkgs = [p for p in self.pkgs.values() if p.repository == name]
            self.repos[name] = self.Repository(
                name,
                get_repository(Path(pkgs[0].path)),
                [pkg for pkg in self.pkgs.values() if pkg.repository == name],
                set([self.pkgs[d.name].repository for pkg in pkgs for d in pkg.pkg['build_depends'] if d.name in self.pkgs]).difference([name]),
                set([self.pkgs[d.name].repository for pkg in pkgs for d in pkg.pkg['exec_depends'] if d.name in self.pkgs]).difference([name])
                )

        # map of build groups (multiple repositories build together)
        self.groups = {'loose': repository_names}
        # TODO: read them from *.repos in the folder

        # keep history around to support undo
        self.Frame = namedtuple('Frame', ['command', 'groups'])
        self.history = []

        super().__init__(completekey='tab')
        self.do_list("")

    def push_frame(self, cmd):
        '''
        push group state to history stack / has to be called *before* applying modification
        '''
        self.history.append(self.Frame(cmd, deepcopy(self.groups)))

    def do_undo(self, line):
        if len(self.history) == 0:
            print ("nothing to undo")
            return

        print(f"undoing `{self.history[-1].command}`")
        self.groups = self.history[-1].groups
        self.history.pop()

    def do_hist(self, line):
        for i,frame in enumerate(self.history[::-1]):
            print(f"({i:02}) {frame.command}")

    def precmd(self, line):
        if line == 'EOF':
            sys.exit(0)
        return line

    def complete_ls(self, text, line, begidx, endidx):
        return self.complete_list(text, line, begidx, endidx)

    def do_ls(self, line):
        "Alias for `list`"
        self.do_list(line)

    def complete_list(self, text, line, begidx, endidx):
        return [g for g in self.groups.keys() if g.startswith(text)]

    def do_list(self, line):
        """
        `list [group]` List all repositories in the workspace/target group
        """

        if line == '':
            groups = self.groups.keys()
        else:
            if line not in self.groups:
                print(f"group '{line}' does not exist")
                return
            groups = [line]

        for g in groups:
            print(f"group {g}:\n")
            print(f'{len(self.groups[g])} repositories:')
            self.columnize(self.groups[g])
            pkgs = set([p.pkg['name'] for p in self.pkgs.values() if p.repository in self.groups[g]])
            print(f'\n{len(pkgs)} packages:')
            self.columnize(pkgs)
            print()

    def do_groups(self, line):
        '''
        list all groups with statistics
        '''
        for g in self.groups:
            print(f"{g}: {len(self.groups[g])} repositories / {len([p for r in self.groups[g] for p in self.repos[r].packages])} packages")

    def complete_pkg(self, text, line, begidx, endidx):
        return [p for p in self.pkgs if p.startswith(text)]

    def do_pkg(self, pkg_name):
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

    def complete_repo(self, text, line, begidx, endidx):
        return [r for r in self.repos if r.startswith(text)]

    def do_repo(self, repo_name):
        '''
        Inspect a repository showing its packages and dependencies
        '''
        if repo_name not in self.repos:
            print(f"repository '{repo_name}' is not known")
            return

        repo = self.repos[repo_name]

        print("group\n"
              "-----")
        print(next(g for g in self.groups if repo_name in self.groups[g]))

        print("\npackages\n"
              "--------")
        self.columnize([p.pkg['name'] for p in repo.packages])
        print()

        print("build_depend repositories\n"
                "------------------")
        self.columnize(repo.build_depends)
        print("\nexec_depend repositories\n"
                "-----------------")
        self.columnize(repo.exec_depends)

        print("\ndirect rdeps\n"
                "------------")
        rdeps = [r for r in self.repos if repo_name in self.repos[r].build_depends.union(self.repos[r].exec_depends)]
        self.columnize(rdeps)

    def complete_group(self, text, line, begidx, endidx):
        return [g for g in self.groups if g.startswith(text)]

    def do_group(self, group):
        '''
        Inspect group
        '''

        if group not in self.groups:
            print(f"group '{group}' is not known")
            return

        print("repositories of group\n"
              "---------------------")

        self.columnize(self.groups[group])

        repo_deps = [(dep, repo) for repo in self.groups[group] for dep in self.repos[repo].build_depends.union(self.repos[repo].exec_depends)]
        group_deps = {g : (dep, repo) for g in self.groups if g != group for repo,dep in repo_deps if repo in self.groups[g]}
        print("\ndependencies\n"
              "------------")

        for d in set(group_deps):
            print(f"{d} (e.g., {group_deps[d][0]} depends on {group_deps[d][1]})")

    def do_create(self, group):
        '''
        create a new group
        '''
        if group in self.groups:
            print(f"group '{group}' already exists")
            return

        self.push_frame(f"create {group}")

        self.groups[group] = set()
        print(f"Created group '{group}'")

    def complete_remove(self, text, line, begidx, endidx):
        return [g for g in self.groups if g.startswith(text) and g != 'loose']

    def do_remove(self, group):
        '''
        remove a group
        '''
        if group not in self.groups:
            print(f"group '{group}' does not exist")

        self.groups['loose'].update(self.groups[group])
        del self.groups[group]
        print(f"group '{group}' removed (repositories loose again)")

    def complete_rename(self, text, line, begidx, endidx):
        return self.complete_group(text, line, begidx, endidx)

    def do_rename(self, line):
        '''
        rename a group
        '''

        old, new = line.split(" ")

        if old not in self.groups:
            print(f"group '{old}' does not exist")
            return

        self.push_frame(f"rename {old} {new}")

        self.groups[new] = self.groups[old]
        del self.groups[old]
        print(f"group '{old}' renamed to '{new}'")

    def complete_mv(self, text, line, begidx, endidx):
        return self.complete_move(text, line, begidx, endidx)

    def do_mv(self, line):
        "Alias for `list`"
        self.do_move(line)

    def complete_move(self, text, line, begidx, endidx):
        if len(line.split(" ")) == 2:
            return self.complete_repo(text, line, begidx, endidx)
        else:
            return self.complete_group(text, line, begidx, endidx)

    def do_move(self, line):
        '''
        `move <repo> <group>` to move a repository from anywhere to <group>
        Maintain dependency hierarchy - possibly moving other packages along
        '''
        repo, new_group = line.split(" ")

        if new_group not in self.groups:
            print(f"group '{new_group}' is not known")
            return

        if repo not in self.repos:
            print(f"repository '{repo}' is not known")
            return

        if repo in self.groups[new_group]:
            print(f"repository '{repo}' already in group '{new_group}'")
            return

        self.push_frame(f"move {repo} {new_group}")

        old_group = next(g for g in self.groups if repo in self.groups[g])

        if old_group == 'loose':
            repos = [repo]
            rdeps = [r for r in self.repos if repo in self.repos[r].build_depends.union(self.repos[r].exec_depends)]
            for r in rdeps:
                self.groups[new_group].add(r)



        self.groups[old_group].remove(repo)
        self.groups[new_group].add(repo)

        print(f"moved {repo} to {new_group}")

    def do_export(self, line):
        '''
        export groups to .repos files
        '''
        for group in self.groups:
            with open(f'{group}.repos', 'w') as file:
                file.write("repositories:\n")
                ws= Path(self.ws)
                for repository in self.groups[group]:
                    url, version = get_git_info(ws/repository)
                    file.write(
                        f"  {repository}:\n"
                        f"    type: git\n"
                        f"    url: {url}\n"
                        f"    version: {version}\n"
                    )
                print(f"wrote selection to file {group}.repos")

        with open('repos_dependencies.txt', 'w') as file:
            for group in self.groups:
                repo_deps = [dep for repo in self.groups[group] for dep in self.repos[repo].build_depends.union(self.repos[repo].exec_depends)]
                group_deps = {g for g in self.groups if g != group for repo in repo_deps if repo in self.groups[g]}
                for d in group_deps:
                    file.write(f"{d} (e.g., {group_deps[d][0]} depends on {group_deps[d][1]})\n")
        print("wrote dependencies to repos_dependencies.txt")

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
