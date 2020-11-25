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

requirements.txt: pyproject.toml
	poetry export -f requirements.txt --without-hashes -o requirements.txt
	echo '--extra-index-url https://__token__:'"${GITLAB_PYPI_TOKEN}"'@gitlab.com/api/v4/projects/13882298/packages/pypi/simple/\n' > requirements.txt

bundle_dist:
	-rm -rf dist/
	poetry install --no-root
	pybabel compile -d $(PACKAGE)/locale -D $(PACKAGE) || true
	poetry build --format sdist
	tar -zxvf dist/*.tar.gz -C dist

bundle_deb: bundle_dist requirements.txt
	-rm -rf dist/*/env
	cd dist/* && \
		python -m venv env && \
		. env/bin/activate && \
		pip install -U poetry pip wheel setuptools && \
		pip install -r requirements.txt && \
		cp setup_old.py setup.py && \
		debuild --preserve-env -us -uc

include utils/utils.mk
.PHONY: check coverage
