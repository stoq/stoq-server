PACKAGE="stoqserver"

check: check-source-all
	./runtests.py stoqserver/lib/test
	pytest -v tests

coverage: check-source-all
	./runtests.py stoqserver/lib/test --with-xcoverage --with-xunit \
	              --cover-package=$(PACKAGE) --cover-erase
	pytest -vvv tests --cov=stoqserver --cov-report=term-missing --quick
	utils/validatecoverage.py coverage.xml && \
	git show|utils/diff-coverage coverage.xml


flask:
	./bin/stoqserver flask

include utils/utils.mk
.PHONY: check coverage
