#
# Running `make dev` will set up links for development using symlink to the library source
# Running `make install` will compile a release and install it properly as a release
#

LIBNAME=native_codec_impl
ROOT=$(shell pwd)
PIP=pip3
PY=python3

#.PHONY: compile
#compile:
#	cargo build && \
#	ln -fs $(ROOT)/target/debug/lib$(LIBNAME).so $(ROOT)/target/debug/$(LIBNAME).so
# && cargo build --release

.PHONY: clearterminal
clearterminal:
	clear && printf '\e[3J'

.PHONY: test
test: clearterminal
	for f in $(shell ls test/*_test.py); do \
		echo "RUNNING $$f"; \
		$(PY) $$f || exit 1; \
	done

.PHONY: clearterminal dtest
dtest: compile
	PYTHONPATH=$(ROOT):$(ROOT)/target/debug gdb --args python3 test/etf_decode_test.py

.PHONY: docs
docs:
	rm -rf $(ROOT)/docs; \
	cd docs-src && \
	$(MAKE) html && \
	mv -f $(ROOT)/docs-src/build/html $(ROOT)/docs && \
	touch $(ROOT)/docs/.nojekyll

#
# Installing for development, and for release
#
.PHONY: install dev requirements
requirements:
	$(PIP) install -r requirements.txt
dev: requirements
	$(PY) setup.py develop

install: requirements
	$(PY) setup.py install
