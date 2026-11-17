# tb/Makefile - runs the cocotb tests for one module with Icarus Verilog.
#
# Pick the module with TEST (from the tb folder, with the .venv activated):
#   make TEST=g          G function
#   make TEST=compress   compression core
#   make TEST=chunk      chunk controller + core (via the test wrapper)
#   make TEST=tree       tree controller + core (via the test wrapper)
#   make TEST=arbiter    arbiter + core (via the test wrapper)
#   make TEST=top        the full accelerator: real BLAKE3 hashes of whole messages
#   make regress         all of the above, one after another
#
# Each test builds in its own folder (sim_build_<name>), so switching
# between tests never reuses a build from a different module.

PROJ := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
RTL  := $(PROJ)/rtl

TEST ?= top

SIM ?= icarus
TOPLEVEL_LANG = verilog

# Turn on SystemVerilog support in Icarus
COMPILE_ARGS += -g2012

# Let the RTL find blake3_assert.svh
COMPILE_ARGS += -I$(RTL)

ifeq ($(TEST),g)
    VERILOG_SOURCES     = $(RTL)/blake3_g.sv
    COCOTB_TOPLEVEL     = blake3_g
    COCOTB_TEST_MODULES = test_g
else ifeq ($(TEST),compress)
    VERILOG_SOURCES     = $(RTL)/blake3_g.sv $(RTL)/blake3_compress.sv
    COCOTB_TOPLEVEL     = blake3_compress
    COCOTB_TEST_MODULES = test_compress
else ifeq ($(TEST),chunk)
    VERILOG_SOURCES     = $(RTL)/blake3_g.sv $(RTL)/blake3_compress.sv \
                          $(RTL)/blake3_chunk.sv $(RTL)/blake3_chunk_top.sv
    COCOTB_TOPLEVEL     = blake3_chunk_top
    COCOTB_TEST_MODULES = test_chunk
else ifeq ($(TEST),tree)
    VERILOG_SOURCES     = $(RTL)/blake3_g.sv $(RTL)/blake3_compress.sv \
                          $(RTL)/blake3_tree.sv $(RTL)/blake3_tree_top.sv
    COCOTB_TOPLEVEL     = blake3_tree_top
    COCOTB_TEST_MODULES = test_tree
else ifeq ($(TEST),arbiter)
    VERILOG_SOURCES     = $(RTL)/blake3_g.sv $(RTL)/blake3_compress.sv \
                          $(RTL)/blake3_arbiter.sv $(RTL)/blake3_arbiter_top.sv
    COCOTB_TOPLEVEL     = blake3_arbiter_top
    COCOTB_TEST_MODULES = test_arbiter
else ifeq ($(TEST),top)
    VERILOG_SOURCES     = $(RTL)/blake3_g.sv $(RTL)/blake3_compress.sv \
                          $(RTL)/blake3_chunk.sv $(RTL)/blake3_tree.sv \
                          $(RTL)/blake3_arbiter.sv $(RTL)/blake3_top.sv
    COCOTB_TOPLEVEL     = blake3_top
    COCOTB_TEST_MODULES = test_top
else
    $(error Unknown TEST '$(TEST)'. Use one of: g, compress, chunk, tree, arbiter, top)
endif

# Separate build folder per test
SIM_BUILD = sim_build_$(TEST)

# Lets the tests do:  from blake3 import ...
export PYTHONPATH := $(PROJ):$(PYTHONPATH)

include $(shell cocotb-config --makefiles)/Makefile.sim

# Run every test, one module at a time
.PHONY: regress
regress:
	$(MAKE) TEST=g
	$(MAKE) TEST=compress
	$(MAKE) TEST=chunk
	$(MAKE) TEST=tree
	$(MAKE) TEST=arbiter
	$(MAKE) TEST=top