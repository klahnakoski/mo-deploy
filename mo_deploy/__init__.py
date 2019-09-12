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

        Module.git = coalesce(settings.git, Module.git)
        Module.svn = coalesce(settings.svn, Module.svn)
        Module.pip = coalesce(settings.pip, Module.pip)
        Module.twine = coalesce(settings.twine, Module.twine)
        Module.python = coalesce(settings.python, Module.python)

        graph = ModuleGraph(listwrap(settings.managed), settings.deploy)

        if not graph.todo:
            Log.note("No modules need to deploy")
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
