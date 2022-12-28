from mo_files import File
from mo_logs import Log
from mo_threads.multiprocess import Command

# RELOCATE ALL .svn DIRECTORIES POINT TO LOCAL svn SERVER
# ENSURE VisualSVN IS INSTALLED
# ENSURE SERVER DIRECTORY HAS BEEN SETUP

code = File("C:/Users/kyle/code")

for d in code.decendants:
    Log.note("{{file}}", file=d.abs_path)
    if d.name == "" and d.extension == "svn":
        Command("relocate", ["svn", "relocate", "https://klahnakoski-39477/", "https://kyle-win10/"], cwd=d.parent)
