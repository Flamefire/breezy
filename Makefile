DEBUGGER ?= 
BZR ?= $(shell which bzr)
PYTHON ?= $(shell which python)
SETUP ?= ./setup.py
CTAGS ?= ctags
PYLINT ?= pylint
TESTS ?= 
DESTDIR ?= 

all:: build 

build::
	$(SETUP) build

install::
ifneq ($(DESTDIR),)
	$(SETUP) install --root "$(DESTDIR)"
else
	$(SETUP) install
endif

clean::
	$(SETUP) clean

TMP_PLUGINS_DIR = $(shell pwd)/.plugins

$(TMP_PLUGINS_DIR):
	mkdir -p $@

$(TMP_PLUGINS_DIR)/rebase: $(TMP_PLUGINS_DIR)
	ln -sf .. $@

check:: $(TMP_PLUGINS_DIR)/rebase/
	BZR_PLUGIN_PATH=$(TMP_PLUGINS_DIR) $(DEBUGGER) $(PYTHON) $(BZR) selftest $(TEST_OPTIONS) --starting-with=bzrlib.plugins.rebase $(TESTS)

check-verbose::
	$(MAKE) check TEST_OPTIONS=-v

check-one::
	$(MAKE) check TEST_OPTIONS=--one

show-plugins::
	BZR_PLUGIN_PATH=$(TMP_PLUGINS_DIR) $(BZR) plugins

lint::
	$(PYLINT) -f parseable *.py */*.py

tags::
	$(CTAGS) -R .

ctags:: tags
