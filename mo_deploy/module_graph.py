# encoding: utf-8
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Author: Kyle Lahnakoski (kyle@lahnakoski.com)
#
from __future__ import division
from __future__ import unicode_literals

from mo_dots import coalesce
from toposort import toposort

from mo_deploy.module import Module
from mo_logs import Log
from mo_math import UNION


class ModuleGraph(object):

    def __init__(self, module_directories):
        graph = self.graph = {}
        versions = self.versions = {}

        self.modules = {
            m.name: m
            for d in module_directories
            for m in [Module(d, self)]
        }

        for m in self.modules.values():
            module_name = m.name
            # FIND DEPENDENCIES FOR EACH MODULE
            graph[module_name] = set()
            versions[module_name] = m.get_version()[0]

            for req in m.get_requirements():
                graph[module_name].add(req.name)
        self.toposort = list(toposort(graph))

        # WHAT MODULES NEED UPDATE?
        candidates_for_update = [
            m
            for m in self.modules.values()
            if m.can_upgrade() or m.last_deploy() < m.get_version()[0]
        ]

        Log.alert("Changed modules: {{modules}}", modules=[c.name for c in candidates_for_update])

        self.todo = self.get_dependencies(candidates_for_update)
        self.todo_names = set(t.name for t in self.todo)

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
        # RETURN THEM IN CANONICAL ORDER
        return [
            self.modules[module]
            for batch in self.toposort
            for module in sorted(batch)
            if module in candidates
        ]

