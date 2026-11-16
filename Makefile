#
# `make dev` installs the package editable (the native codec is built in
# place); `make install` installs it as a release would.
#

ROOT=$(shell pwd)
PIP=pip3
PY=python3

.PHONY: clearterminal
clearterminal:
	clear && printf '\e[3J'

.PHONY: test
test: clearterminal
	$(PY) -m pytest test

# Regenerate the golden ETF fixtures with the Erlang/OTP on PATH (use OTP 29).
.PHONY: fixtures
fixtures:
	erlc -o test/erl test/erl/gen_fixtures.erl test/erl/otp_vectors.erl
	erl -noshell -pa test/erl -run gen_fixtures main test/fixtures -s init stop

.PHONY: docs
docs:
	$(PY) -m sphinx -W --keep-going -b html docs-src/source docs-src/build/html

#
# Installing for development, and for release
#
.PHONY: install dev
dev:
	$(PIP) install -e . --config-settings editable_mode=compat

install:
	$(PIP) install .

# The checks AGENTS.md requires before a commit.
.PHONY: check
check:
	black --check . && isort --check . && mypy term \
	&& cargo fmt --check && cargo clippy --all-targets -- -D warnings \
	&& cargo test && $(PY) -m pytest test

# The codec benchmark against OTP (release build; see test/bench/run.py).
.PHONY: bench
bench:
	$(PY) test/bench/run.py
