PACKAGE="stoqserver"

check: check-source-all
	./runtests.py $(PACKAGE)
	echo "FIXME enable this when we have tests"
	#cd data/webrtc && npm test

coverage: check-source-all
	./runtests.py --with-xcoverage --with-xunit \
	              --cover-package=$(PACKAGE) --cover-erase $(PACKAGE)
	echo "FIXME enable this when we have tests"
	#cd data/webrtc && npm test

include utils/utils.mk
.PHONY: check coverage
