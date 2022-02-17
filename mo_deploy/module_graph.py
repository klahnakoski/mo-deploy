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

from toposort import toposort

import mo_math
from mo_deploy.module import Module, SETUPTOOLS
from mo_deploy.utils import Requirement, TODAY
from mo_dots import listwrap
from mo_files import File
from mo_http import http
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

            for req in m.get_current_requirements([
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
        self.todo = self._sorted(set(
            m.name
            for m in deploy_dependencies
            if m.can_upgrade() or m.last_deploy() < m.get_version()[0]
        ) | set(deploy))

        # ASSIGN next_version IN CASE IT IS REQUIRED
        # IF b DEPENDS ON a THEN version(b)>=version(a)
        # next_version(a) > version(a)
        max_minor_version = max(int(v.minor) for v in versions.values() if v != None)
        self.next_minor_version = max_minor_version + 1

        version_bump = {t.name: t for t in self.todo}
        self._next_version = {}
        for m in self.todo:
            # THE SETUPTOOLS FILE MAY SUGGEST A HIGHER MAJOR VERSION
            proposed_version = Version(
                File(m.directory / SETUPTOOLS).read_json().version
            )
            self._next_version[m.name] = Version((
                max(m.version.major, proposed_version.major),
                self.next_minor_version,
                TODAY,
            ))

        is_upgrading = set(self._next_version.keys())

        def scan(module: Module, version: Version, new_version: Version, ancestor_upgrading):
            """
            LOG THE module:version FOR EVERYTHING IN THE DEPENDENCIES
            Markup modules that need incidental upgrade
            * modules between two upgrades
            * modules version conflict must upgrade (added to self._next_version)

            return if child is upgrading
            """
            reqs = module.get_old_dependencies(version)
            any_decendant_upgrading = False

            for req in reqs:
                req_name, req_version = req["name"], req["version"]
                # Log.note(
                #     "{{module}}=={{version}} requires {{req_name}}=={{req_version}}",
                #     module=module.name,
                #     version=version,
                #     req_name=req_name,
                #     req_version=req_version,
                # )
                managed_req = self.modules.get(req_name)
                if not req_version:
                    curr_version = self.versions.setdefault(req_name, self.get_pypi_version(req_name))
                    req_version = curr_version
                else:
                    curr_version = self.versions.setdefault(req_name, req_version)

                req_new_version = Version((
                    mo_math.max(curr_version.major, managed_req.get_version()[0].major if managed_req else None),
                    self.next_minor_version,
                    TODAY,
                ))

                if module.name not in is_upgrading:
                    if curr_version < req_version:
                        is_upgrading.add(module.name)
                        self._next_version[req_name] = req_new_version
                        Log.error("not done")
                    elif req_version < curr_version:
                        # THERE IS A CONFLICT SOMEWHERE IN THE DEPENDENCY TREE
                        is_upgrading.add(module.name)
                        self._next_version[module.name] = Version((
                            module.version.major,
                            self.next_minor_version,
                            TODAY,
                        ))
                        Log.error("not done")

                if managed_req:
                    decendant_upgrading = scan(managed_req, curr_version, req_new_version, ancestor_upgrading or module.name in is_upgrading)
                    any_decendant_upgrading |= decendant_upgrading
                    if module.name not in is_upgrading and decendant_upgrading and ancestor_upgrading:
                        is_upgrading.add(module.name)
                        if new_version is None:
                            Log.error("do not know how to handle")
                        self._next_version[module.name] = new_version
                        Log.error("not done")

            return any_decendant_upgrading or module.name in is_upgrading

        while True:
            try:
                for t in self.todo:
                    scan(t, self._next_version[t.name], None, True)
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
                for k, v in self.versions.items()
                if k not in self._next_version
            },
        )
        additional = self._next_version.keys() - version_bump.keys()
        if additional:
            Log.note(
                "No change, but requires version bump {{modules}}", modules=additional,
            )

        self.todo = self._sorted(self._next_version.keys())

        if self._next_version:
            Log.alert("Updating: {{modules}}", modules=[(m.name, self._next_version[m.name]) for m in self.todo])

    def get_pypi_version(self, module_name):
        result = http.get_json(f"https://pypi.org/pypi/{module_name}/json")
        return max(Version(v) for v in result.releases.keys())

    def get_next_version(self, module_name):
        return self._next_version[module_name]

    def get_version(self, module_name):
        return self._next_version.get(module_name, self.versions[module_name])

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
