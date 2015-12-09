PACKAGE="stoqserver"

check: check-source-all
	echo "FIXME enable this when we have tests"
	#cd data/webrtc && npm test

include utils/utils.mk
.PHONY: check
