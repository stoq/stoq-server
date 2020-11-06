PACKAGE="stoqserver"

check: lint
	./runtests.py stoqserver/lib/test
	pytest -v tests

coverage: lint
	./runtests.py stoqserver/lib/test --with-xcoverage --with-xunit \
	              --cover-package=$(PACKAGE) --cover-erase
	pytest -vvv tests --cov=stoqserver --cov-report=term-missing --quick --cov-append && \
	coverage xml --omit "/tests/api/resources/*.py"
	utils/validatecoverage.py coverage.xml && \
	git show|utils/diff-coverage coverage.xml

flask:
	./bin/stoqserver flask

lint:
	pyflakes stoqserver tests
	pycodestyle stoqserver tests

test:
	python runtests.py stoqserver/lib/test
	pytest -vvv

include utils/utils.mk
.PHONY: check coverage
