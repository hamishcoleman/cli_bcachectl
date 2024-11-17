
# Just the packages needed to run lint and test
PACKAGES+=flake8
PACKAGES+=python3-pytest

PYTHON=$(wildcard *.py)

all:
	@echo Pure Python package - nothing to build

build-dep:
	sudo apt-get install $(PACKAGES)

test:
	pytest-3 $(PYTHON)

lint:
	flake8
