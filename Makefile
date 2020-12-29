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

flask-gunicorn:
	gunicorn stoqserver.gunicorn -w 1 -b localhost:6971 -k gevent --access-logfile -

lint:
	pyflakes stoqserver tests
	pycodestyle stoqserver tests

test:
	python runtests.py stoqserver/lib/test
	pytest -vvv

bundle_dist: requirements.txt
	-rm -rf dist/
	# workaround to generate wheel from stoq-plugin-link source
	# https://gitlab.com/stoqtech/private/stoq-plugin-link/-/blob/master/.gitlab-ci.yml#L75
	pip install -U kiwi-gtk
	poetry install --no-root
	pybabel compile -d $(PACKAGE)/locale -D $(PACKAGE) || true
	cp data/udev/bundle-10-stoq.rules data/udev/10-stoq.rules
	poetry build --format sdist
	tar -zxvf dist/*.tar.gz -C dist

bundle_deb: bundle_dist requirements.txt
	-rm -rf dist/*/env
	cd dist/* && \
		python -m venv env && \
		. env/bin/activate && \
		pip install -U kiwi-gtk && \
		pip install -U pip==20.3.3 wheel setuptools==51.1.2 && \
		pip install -U poetry && \
		pip install -r requirements.txt && \
		cp setup_old.py setup.py && \
		debuild --preserve-env -us -uc

include utils/utils.mk
.PHONY: check coverage
