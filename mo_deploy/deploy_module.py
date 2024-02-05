# encoding: utf-8
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Author: Kyle Lahnakoski (kyle@lahnakoski.com)
#
from mo_deploy.module import NO_VERSION, FIRST_VERSION
from mo_dots import Data
from pyLibrary.meta import cache


class DeployModule:

    def __init__(self, graph, deploy):
        self.graph = graph
        self.deploy = deploy
        self.name = "__deploy__"
        self.package_name = "__deploy__"
        self.version = FIRST_VERSION

    def setup(self):
        pass

    def last_deploy(self):
        return NO_VERSION

    def get_current_requirements(self, current_requires):
        return [Data(name=d) for d in self.deploy]

    def get_next_requirements(self, current_requires):
        return Data()

    def get_setup_version(self):
        return FIRST_VERSION

    def get_version(self):
        return FIRST_VERSION, ""

    @cache()
    def get_old_dependencies(self, version):
        return [{"name": d, "version": self.graph.modules[d].last_deploy()} for d in self.deploy]

    def please_upgrade(self):
        return True

    def __str__(self):
        return "__deploy__"

    def clean_branches(self):
        pass

