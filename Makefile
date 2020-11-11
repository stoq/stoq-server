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

bundle_dist:
	-rm -rf dist/
	poetry install --no-root
	pybabel compile -d $(PACKAGE)/locale -D $(PACKAGE) || true
	poetry build --format sdist
	tar -zxvf dist/*.tar.gz -C dist

bundle_deb: bundle_dist
	-rm -rf dist/*/env
	cd dist/* && \
		python -m venv env && \
		. env/bin/activate && \
		pip install -U poetry pip wheel setuptools && \
		poetry export -f requirements.txt --without-hashes | cut -d '@' -f 2 > requirements.txt && \
		pip install -r requirements.txt && \
		cp setup_old.py setup.py && \
		debuild --preserve-env -us -uc

include utils/utils.mk
.PHONY: check coverage
