# mo-deploy
More Deployment!  Deploy the mo-* familiy of packages to pypi

### Nomenclature

* **module** - a Python file, or directory
* **package** - Some number of modules together on pypi
* **project** - Code for some purpose, probably found on Github, maybe the source for a package 

## Overview

All packages are version-controlled using two systems; Git and SVN. The Git is used to track the official branches for the packages, while SVN tracks the `dev` branch across multiple projects that vendored the package source code.

Most packages are developed in the projects they are used: Packages are included in a project to keep the project simple, and the package is enhanced as the project grows. This happens across multiple projects and packages.

### Example

[`mo-dots`](https://pypi.org/project/mo-dots/) is a common-used package used in many projects. [Its source code](https://github.com/klahnakoski/mo-dots) is on Github.