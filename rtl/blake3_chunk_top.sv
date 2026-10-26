`default_nettype none

module blake3_chunk_top (
    // clock and reset
    input   logic           clk,
    input   logic           rst_n,

    // block input (from the block source)
    input   logic           blk_valid,
    output  logic           blk_ready,
    input   logic [511:0]   blk_data,
    input   logic [6:0]     blk_len,
    input   logic           blk_last,
    input   logic           blk_root,
    input   logic [63:0]    chunk_index,

    // hash settings (fixed for a whole message)
    input   logic [255:0]   key,
    input   logic [7:0]     base_flags,

    // chunk value output
    output  logic           cv_valid,
    output  logic [255:0]   cv_out
);

    // wires between the chunk controller and the core
    logic           core_in_valid;
    logic           core_in_ready;
    logic [255:0]   core_cv_in;
    logic [511:0]   core_block_in;
    logic [63:0]    core_counter;
    logic [6:0]     core_block_len;
    logic [7:0]     core_flags;
    logic           core_out_valid;
    logic [511:0]   core_out;

    blake3_chunk u_chunk (
        .clk            (clk),
        .rst_n          (rst_n),

        .blk_valid      (blk_valid),
        .blk_ready      (blk_ready),
        .blk_data       (blk_data),
        .blk_len        (blk_len),
        .blk_last       (blk_last),
        .blk_root       (blk_root),
        .chunk_index    (chunk_index),

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

        .cv_valid       (cv_valid),
        .cv_out         (cv_out)
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