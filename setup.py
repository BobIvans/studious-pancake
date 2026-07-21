"""setuptools entrypoint for the production package boundary."""

from __future__ import annotations

from setuptools import setup

from scripts.package_boundary import RuntimeBoundaryBuildPy

setup(cmdclass={"build_py": RuntimeBoundaryBuildPy})
