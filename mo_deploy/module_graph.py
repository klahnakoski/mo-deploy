# encoding: utf-8
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Author: Kyle Lahnakoski (kyle@lahnakoski.com)
#
from __future__ import division, unicode_literals

from copy import copy
from typing import Dict

from toposort import toposort

from mo_deploy.module import Module, SETUPTOOLS
from mo_deploy.utils import Requirement, TODAY
from mo_dots import listwrap
from mo_files import File
from mo_logs import Log
from mo_logs.exceptions import Except
from mo_math import UNION
from mo_threads import Lock
from mo_threads.threads import AllThread
from mo_times import Timer
from pyLibrary.utils import Version


class ModuleGraph(object):
    def __init__(self, module_directories, deploy):
        graph = self.graph = {}
        versions = self.versions = {}

        self.modules = {
            m.name: m for d in module_directories for m in [Module(d, self)]
        }

        graph_lock = Lock()

        def info(m, please_stop):
            module_name = m.name
            # FIND DEPENDENCIES FOR EACH MODULE
            graph[module_name] = set()
            last_version = m.get_version()[0]
            versions[module_name] = max(
                Version(
                    (m.directory / SETUPTOOLS).read_json(leaves=False).version,
                    prefix="v",
                ),
                last_version,
            )

            for req in m.get_requirements([
                Requirement(k, "==", v) for k, v in versions.items()
            ]):
                with graph_lock:
                    graph[module_name].add(req.name)

        with AllThread() as a:
            for m in self.modules.values():
                a.run(m.name, info, m)

        self.toposort = list(toposort(graph))

        def closure(parents):
            prev = set()
            dependencies = set(listwrap(parents))
            while dependencies - prev:
                prev = copy(dependencies)
                for d in list(dependencies):
                    dependencies |= graph.get(d, set())
            return dependencies

        # CALCULATE ALL DEPENDENCIES FOR EACH
        for m in list(graph.keys()):
            graph[m] = closure(m)

        # WHAT MUST BE DEPLOYED?
        deploy_dependencies = set(
            self.modules[d] for d in closure(deploy) if d in self.modules
        )

        Log.note(
            "Dependencies are {{modules}}",
            modules=[m.name for m in deploy_dependencies],
        )
        # PREFETCH SOME MODULE STATUS
        def pre_fetch_state(d, please_stop):
            d.can_upgrade()
            d.last_deploy()

        with Timer("get modules' status"):
            with AllThread() as a:
                for d in deploy_dependencies:
                    a.run(d.name, pre_fetch_state, d)

        # WHAT MODULES NEED UPDATE?
        self.todo_names = [
            m.name
            for m in deploy_dependencies
            if m.can_upgrade() or m.last_deploy() < m.get_version()[0]
        ]
        self.todo = self._sorted(self.todo_names)
        self.todo_names = [{"name": t.name, "version": t.version} for t in self.todo]

        # ASSIGN next_version IN CASE IT IS REQUIRED
        # IF b DEPENDS ON a THEN version(b)>=version(a)
        # next_version(a) > version(a)
        max_minor_version = max(int(v.minor) for v in versions.values() if v != None)
        self.next_minor_version = max_minor_version + 1

        version_bump = self.todo.copy()
        self._next_version = {}
        for m in version_bump:
            # THE SETUPTOOLS FILE MAY SUGGEST A HIGHER MAJOR VERSION
            proposed_version = Version(File(m.directory / SETUPTOOLS).read_json().version)
            self._next_version[m.name] = Version((
                max(m.version.major, proposed_version.major),
                self.next_minor_version,
                TODAY,
            ))

        def scan(module: Module, version: Version):
            # GET DEPENDENCIES
            reqs = module.get_old_dependencies(version)
            # FOR EACH REQUIREMENT
            for req in reqs:
                req_name = req["name"]
                req_minor_version = req["version"].minor
                # Log.note("{{module}}=={{version}} requires {{req_name}}=={{req_version}}", module=module.name, version=version, req_name=req_name, req_version=req_version)
                req_module = self.modules.get(req_name)
                if not req_module:
                    continue
                next_version = self._next_version.get(req_name)
                if next_version is None:
                    curr_version = self.versions[req_name]
                    self._next_version[req_name] = Version((
                        curr_version.major,
                        req_minor_version,
                        TODAY,
                    ))
                elif next_version.minor > req_minor_version:
                    if module not in version_bump:
                        version_bump.append(module)
                        Log.note("found underlap")
                        raise Exception("not done")
                    req_minor_version = next_version.minor
                elif next_version.minor < req_minor_version:
                    Log.note("found overlap")
                    self._next_version[req_name].minor = req_minor_version
                    raise Exception("not done")

                scan(req_module, req_minor_version)

        while True:
            try:
                for t in version_bump.copy():
                    scan(t, self._next_version[t.name])
            except Exception as cause:
                cause = Except.wrap(cause)
                if "not done" in cause:
                    continue
                Log.error("problem while scanning past versions", cause=cause)
            else:
                break

        Log.note(
            "Using old versions {{versions}}",
            versions={
                k: str(v)
                for k, v in self._next_version.items()
                if k not in set(m.name for m in version_bump)
            },
        )
        additional = [m.name for m in version_bump if m not in self.todo]
        if additional:
            Log.note(
                "No change, but requires version bump {{modules}}", modules=additional,
            )

        # UPGRADE TODO
        self.todo = self._sorted(set(m.name for m in version_bump))
        self.todo_names = [t.name for t in self.todo]

        if self.todo:
            Log.alert("Updating: {{modules}}", modules=self.todo_names)

    def get_next_version(self, module_name):
        return self._next_version[module_name]

    def get_version(self, module_name):
        if module_name in self.todo_names:
            return self._next_version[module_name]
        else:
            return self.versions[module_name]

    def get_dependencies(self, modules):
        """
        RETURN THE MODULES THAT DEPEND ON THIS
        """
        dependencies = set(m.name for m in modules)
        num = 0
        # FIND FIXPOINT
        while num < len(dependencies):
            num = len(dependencies)
            dependencies = UNION(
                [dependencies]
                + [
                    set(m for r in reqs if r in dependencies)
                    for m, reqs in self.graph.items()
                ]
            )

        return self._sorted(dependencies)

    def get_requirements(self, modules):
        """
        RETURN THE MODULES THAT THIS DEPENDS ON
        """
        requirements = set(m.name for m in modules)
        num = 0
        # FIND FIXPOINT
        while num < len(requirements):
            num = len(requirements)
            requirements = UNION(self.graph[d] for d in requirements)

        return self._sorted(requirements)

    def _sorted(self, candidates):
        """
        :param candidates:  list of module name
        :return: modules in canonical topological order
        """
        return [
            self.modules[module]
            for batch in self.toposort
            for module in sorted(batch)
            if module in candidates
        ]
