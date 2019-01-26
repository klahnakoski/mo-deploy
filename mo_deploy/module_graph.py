# encoding: utf-8
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Author: Kyle Lahnakoski (kyle@lahnakoski.com)
#
from __future__ import division, unicode_literals

from toposort import toposort

from mo_deploy.module import Module
from mo_deploy.utils import Requirement
from mo_dots import listwrap
from mo_logs import Log
from mo_math import UNION
from mo_threads import Lock
from mo_threads.threads import AllThread


class ModuleGraph(object):

    def __init__(self, module_directories, deploy):
        graph = self.graph = {}
        versions = self.versions = {}

        self.modules = {
            m.name: m
            for d in module_directories
            for m in [Module(d, self)]
        }

        graph_lock = Lock()

        def info(m, please_stop):
            module_name = m.name
            # FIND DEPENDENCIES FOR EACH MODULE
            graph[module_name] = set()
            versions[module_name] = m.get_version()[0]

            for req in m.get_requirements([Requirement(k, ">=", v) for k, v in versions.items()]):
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
                prev = dependencies
                for d in list(dependencies):
                    dependencies |= graph[d]
            return dependencies

        # CALCULATE ALL DEPENDENCIES FOR EACH
        for m in list(graph.keys()):
            graph[m] = closure(m)
        deploy_dependencies = [self.modules[d] for d in closure(deploy)]

        Log.note("Required modules {{modules}}", modules=[m.name for m in deploy_dependencies])

        # PREFETCH SOM MODULE STATUS
        def pre_fetch_state(d, please_stop):
            d.can_upgrade()
            d.last_deploy()

        with AllThread() as a:
            for d in deploy_dependencies:
                a.run(d.name, pre_fetch_state, d)

        # WHAT MODULES NEED UPDATE?
        self.todo_names = [
            m.name
            for m in deploy_dependencies
            if any(
                d.can_upgrade() or d.last_deploy() < d.get_version()[0]
                for x in graph[m.name]
                for d in [self.modules[x]]
            )
        ]
        self.todo = self._sorted(self.todo_names)
        self.todo_names = [t.name for t in self.todo]


        if not self.todo:
            self.next_version = max(versions.values())
        else:
            # ASSIGN next_version IN CASE IT IS REQUIRED
            # IF b DEPENDS ON a THEN version(b)>=version(a)
            # next_version(a) > version(a)
            max_version = max(v for v in versions.values() if v != None)
            self.next_version = max_version + 1

            Log.alert("Updating: {{modules}}", modules=self.todo_names)

    def get_version(self, module_name):
        if module_name in self.todo_names:
            return self.next_version
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
            dependencies = UNION([dependencies] + [set(m for r in reqs if r in dependencies) for m, reqs in self.graph.items()])

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

