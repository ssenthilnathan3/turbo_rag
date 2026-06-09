from setuptools import setup, find_packages

with open("requirements.txt") as f:
	install_requires = f.read().strip().split("\n")

# get version from __version__ variable in turbo_rag/__init__.py
from turbo_rag import __version__ as version

setup(
	name="turbo_rag",
	version=version,
	description="Turbo-fast RAG for Frappe using TurboVec",
	author="automationbot@agnikul.in",
	author_email="automationbot@agnikul.in",
	packages=find_packages(),
	zip_safe=False,
	include_package_data=True,
	install_requires=install_requires
)
