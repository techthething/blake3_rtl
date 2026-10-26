`default_nettype none

// Test wrapper: one tree controller connected to one compression core.
// Used only for testing the tree controller with a real core; in the final
// design, blake3_top does this job and shares the core with the chunk controller.

module blake3_tree_top #(
    parameter int STACK_DEPTH = 8
) (
    // clock and reset
    input   logic           clk,
    input   logic           rst_n,

    // hash settings (fixed for a whole message)
    input   logic [255:0]   key,
    input   logic [7:0]     base_flags,

    // chunk value input (from the test, standing in for the chunk controller)
    input   logic           chunk_cv_valid,
    input   logic [255:0]   chunk_cv,
    input   logic           chunk_cv_last,

    // final outputs
    output  logic           root_valid,
    output  logic [255:0]   root_out
);

    // wires between the tree controller and the core
    logic           core_in_valid;
    logic           core_in_ready;
    logic [255:0]   core_cv_in;
    logic [511:0]   core_block_in;
    logic [63:0]    core_counter;
    logic [6:0]     core_block_len;
    logic [7:0]     core_flags;
    logic           core_out_valid;
    logic [511:0]   core_out;

    blake3_tree #(
        .STACK_DEPTH    (STACK_DEPTH)
    ) u_tree (
        .clk            (clk),
        .rst_n          (rst_n),

        .key            (key),
        .base_flags     (base_flags),

        .core_in_valid  (core_in_valid),
        .core_in_ready  (core_in_ready),
        .core_cv_in     (core_cv_in),
        .core_block_in  (core_block_in),
        .core_counter   (core_counter),
        .core_block_len (core_block_len),
        .core_flags     (core_flags),

        .core_out_valid (core_out_valid),
        .core_out       (core_out),

        .chunk_cv_valid (chunk_cv_valid),
        .chunk_cv       (chunk_cv),
        .chunk_cv_last  (chunk_cv_last),

        .root_valid     (root_valid),
        .root_out       (root_out)
    );

    blake3_compress u_core (
        .clk            (clk),
        .rst_n          (rst_n),

        .in_valid       (core_in_valid),
        .in_ready       (core_in_ready),
        .cv_in          (core_cv_in),
        .block_in       (core_block_in),
        .counter        (core_counter),
        .block_len      (core_block_len),
        .flags          (core_flags),

        .out_valid      (core_out_valid),
        .out            (core_out)
    );

endmodule

`default_nettype wire