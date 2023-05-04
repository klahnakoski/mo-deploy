# encoding: utf-8
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Author: Kyle Lahnakoski (kyle@lahnakoski.com)
#
from mo_deploy.module import Module
from mo_deploy.module_graph import ModuleGraph
from mo_dots import listwrap, from_data
from mo_files import File
from mo_logs import Log, constants, startup
from mo_threads import Command
from pyLibrary.utils import Version


def main():
    try:
        settings = startup.read_settings()
        constants.set(settings.constants)
        Log.start(settings.debug)

        # ENSURE python HAS latest
        python = settings.general.python
        latest = Version("0")
        for version, path in python.items():
            # THIS TAKES A LONG TIME, SO WE DO NOT BOTHER JOINING
            Command(
                "upgrade setuptools",
                [path, "-m", "pip", "install", "--upgrade", "setuptools"],
                cwd=File("."),
                debug=True
            )

            version = Version(version)
            if version > latest:
                python.latest = path
                latest = version

        # INSTALL PACKAGING TOOLS
        Command(
            "packaging tools", [python.latest, "-m", "pip", "install", "wheel"], cwd=File("."), debug=True
        ).join(raise_on_error=True)

        # SET Module VARIABLES (IN general)
        for k, v in settings.general.items():
            setattr(Module, k, from_data(v))

        graph = ModuleGraph(listwrap(settings.managed), settings.deploy, latest)

        # python -m pip install --upgrade setuptools wheel
        # python -m pip install --user --upgrade twine

        if not graph.todo:
            Log.alert("No modules need to deploy")
            return
        input("Press <Enter> to continue ...")
        for m in graph.todo:
            Log.alert("DEPLOY {{module|upper}} - {{version}}", module=m.name, version=graph.get_next_version(m.name))
            m.deploy()

    except Exception as e:
        Log.warning("Problem with deploy", cause=e)
    finally:
        Log.stop()


if __name__ == "__main__":
    main()
