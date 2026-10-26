`default_nettype none

module blake3_arbiter_top (
    // clock and reset
    input   logic           clk,
    input   logic           rst_n,

    // chunk side (driven by the test, standing in for the chunk controller)
    input   logic           chunk_in_valid,
    output  logic           chunk_in_ready,
    input   logic [255:0]   chunk_cv_in,
    input   logic [511:0]   chunk_block_in,
    input   logic [63:0]    chunk_counter,
    input   logic [6:0]     chunk_block_len,
    input   logic [7:0]     chunk_flags,
    output  logic           chunk_out_valid,
    output  logic [511:0]   chunk_out,

    // tree side (driven by the test, standing in for the tree controller)
    input   logic           tree_in_valid,
    output  logic           tree_in_ready,
    input   logic [255:0]   tree_cv_in,
    input   logic [511:0]   tree_block_in,
    input   logic [63:0]    tree_counter,
    input   logic [6:0]     tree_block_len,
    input   logic [7:0]     tree_flags,
    output  logic           tree_out_valid,
    output  logic [511:0]   tree_out
);

    // wires between the arbiter and the core
    logic           core_in_valid;
    logic           core_in_ready;
    logic [255:0]   core_cv_in;
    logic [511:0]   core_block_in;
    logic [63:0]    core_counter;
    logic [6:0]     core_block_len;
    logic [7:0]     core_flags;
    logic           core_out_valid;
    logic [511:0]   core_out;

    blake3_arbiter u_arb (
        .clk              (clk),
        .rst_n            (rst_n),

        .chunk_in_valid   (chunk_in_valid),
        .chunk_in_ready   (chunk_in_ready),
        .chunk_cv_in      (chunk_cv_in),
        .chunk_block_in   (chunk_block_in),
        .chunk_counter    (chunk_counter),
        .chunk_block_len  (chunk_block_len),
        .chunk_flags      (chunk_flags),
        .chunk_out_valid  (chunk_out_valid),
        .chunk_out        (chunk_out),

        .tree_in_valid    (tree_in_valid),
        .tree_in_ready    (tree_in_ready),
        .tree_cv_in       (tree_cv_in),
        .tree_block_in    (tree_block_in),
        .tree_counter     (tree_counter),
        .tree_block_len   (tree_block_len),
        .tree_flags       (tree_flags),
        .tree_out_valid   (tree_out_valid),
        .tree_out         (tree_out),

        .core_in_valid    (core_in_valid),
        .core_in_ready    (core_in_ready),
        .core_cv_in       (core_cv_in),
        .core_block_in    (core_block_in),
        .core_counter     (core_counter),
        .core_block_len   (core_block_len),
        .core_flags       (core_flags),
        .core_out_valid   (core_out_valid),
        .core_out         (core_out)
    );

    blake3_compress u_core (
        .clk              (clk),
        .rst_n            (rst_n),

        .in_valid         (core_in_valid),
        .in_ready         (core_in_ready),
        .cv_in            (core_cv_in),
        .block_in         (core_block_in),
        .counter          (core_counter),
        .block_len        (core_block_len),
        .flags            (core_flags),

        .out_valid        (core_out_valid),
        .out              (core_out)
    );

endmodule

`default_nettype wire