# encoding: utf-8
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Author: Kyle Lahnakoski (kyle@lahnakoski.com)
#
from __future__ import division, unicode_literals

from mo_deploy.module import Module
from mo_deploy.module_graph import ModuleGraph
from mo_dots import coalesce, listwrap
from mo_future import input
from mo_logs import Log, constants, startup


def main():
    try:
        settings = startup.read_settings()
        constants.set(settings.constants)
        Log.start(settings.debug)

        # SET Module VARIABLES (IN general)
        for k, v in settings.general.items():
            setattr(Module, k, v)

        graph = ModuleGraph(listwrap(settings.managed), settings.deploy)

        # python -m pip install --upgrade setuptools wheel
        # python -m pip install --user --upgrade twine

        if not graph.todo:
            Log.alert("No modules need to deploy")
            return
        input("Press <Enter> to continue ...")
        for m in graph.todo:
            Log.alert("DEPLOY {{module|upper}}", module=m.name)
            m.deploy()

    except Exception as e:
        Log.warning("Problem with deploy", cause=e)
    finally:
        Log.stop()


if __name__ == "__main__":
    main()
