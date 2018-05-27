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

from toposort import toposort

from mo_deploy.module import Module
from mo_math import UNION


class ModuleGraph(object):

    def __init__(self, module_directories):
        graph = self.graph = {}
        limits = self.limits = {}  # MAP FROM MODULE NAME TO (MAP FROM REQUIREMENT NAME TO LIMITS)
        version = self.version = {}

        self.modules = {
            m.name: m
            for d in module_directories
            for m in [Module(d, self)]
        }

        for m in self.modules.values():
            module_name = m.name
            # FIND DEPENDENCIES FOR EACH MODULE
            graph[module_name] = set()
            limits[module_name] = {}
            version[module_name]= m.get_version()[0]

            for req in m.get_requirements():
                # EXPECTING
                limits[module_name][req.name] = req.type, req.version
                graph[module_name].add(req.name)
        self.toposort = list(toposort(graph))

        # WHAT MODULES NEED UPDATE?
        self.todo = self._sorted(self.get_dependencies(m for m in self.modules.values() if m.can_upgrade() or m.last_deploy() < m.get_version()[0]))

        if not self.todo:
            self.next_version = max(v for m, v in version.items())
        else:
            # ASSIGN next_version IN CASE IT IS REQUIRED
            # IF b DEPENDS ON a THEN version(b)>=version(a)
            # next_version(a) > version(a)
            max_version = max(v for m, v in version.items())
            self.next_version = max_version + 1

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

