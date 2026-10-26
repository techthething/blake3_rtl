`default_nettype none

// BLAKE3 hash accelerator: top level.
// Takes a message one 64-byte block at a time and outputs its 32-byte hash.
// Connects the chunk controller, tree controller, arbiter, and compression core,
// and works out the chunk bookkeeping (chunk index, end of chunk, root) itself,
// so the outside world only has to send blocks in order and mark the last one.

module blake3_top #(
    parameter int STACK_DEPTH = 8                 // tree stack size: up to 2^STACK_DEPTH chunks per message
) (
    // clock and reset
    input   logic           clk,
    input   logic           rst_n,

    // hash settings (hold steady from a message's first block until its hash_valid)
    input   logic           keyed,                // 1 = keyed hash mode, 0 = plain hash
    input   logic [255:0]   key,                  // the key in keyed mode (ignored in plain mode)

    // message input: one 64-byte block at a time
    input   logic           in_valid,
    output  logic           in_ready,
    input   logic [511:0]   in_data,              // block bytes, zero-padded if partial
    input   logic [6:0]     in_len,               // real bytes in this block: 64, except possibly the message's last block
    input   logic           in_last,              // this is the message's last block

    // hash output
    output  logic           hash_valid,           // high for one cycle when the hash is ready
    output  logic [255:0]   hash_out
);

    // BLAKE3 constants
    localparam logic [255:0] IV = {32'h5BE0CD19, 32'h1F83D9AB, 32'h9B05688C, 32'h510E527F,
                                   32'hA54FF53A, 32'h3C6EF372, 32'hBB67AE85, 32'h6A09E667}; // word 0 in the low bits
    localparam logic [7:0]   KEYED_HASH = 8'd16;

    // ------------------------------------------------------------------
    // Hash settings: plain mode uses the IV as the key and no extra flag
    // ------------------------------------------------------------------
    logic [255:0]   key_words;
    logic [7:0]     base_flags;

    assign key_words  = keyed ? key : IV;
    assign base_flags = keyed ? KEYED_HASH : 8'd0;

    // ------------------------------------------------------------------
    // Block bookkeeping: where this block sits in its chunk and message
    // ------------------------------------------------------------------
    logic [3:0]     blk_cnt_q;      // blocks already accepted in the current chunk (0 to 15)
    logic [63:0]    chunk_idx_q;    // index of the current chunk within the message
    logic           wait_hash_q;    // message's last block accepted: wait for its hash before taking more

    logic           blk_valid;      // block handshake with the chunk controller
    logic           blk_ready;
    logic           blk_last;       // this block ends its chunk
    logic           blk_root;       // this chunk is the whole message
    logic           accept;         // a block is accepted this cycle

    assign blk_last  = in_last || (blk_cnt_q == 4'd15);    // 16th block, or the message ends here
    assign blk_root  = in_last && (chunk_idx_q == 64'd0);  // message ends in its first chunk

    // one message at a time: no new blocks between a message's last block and its hash
    assign blk_valid = in_valid && !wait_hash_q;
    assign in_ready  = blk_ready && !wait_hash_q;
    assign accept    = in_valid && in_ready;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            blk_cnt_q   <= 4'd0;
            chunk_idx_q <= 64'd0;
            wait_hash_q <= 1'b0;
        end else begin
            if (accept) begin
                if (in_last) begin                     // message done: next block starts a new message
                    blk_cnt_q   <= 4'd0;
                    chunk_idx_q <= 64'd0;
                    wait_hash_q <= 1'b1;
                end else if (blk_last) begin           // chunk done: next block starts the next chunk
                    blk_cnt_q   <= 4'd0;
                    chunk_idx_q <= chunk_idx_q + 64'd1;
                end else begin                         // next block of the same chunk
                    blk_cnt_q   <= blk_cnt_q + 4'd1;
                end
            end

            if (hash_valid) begin                      // hash is out: ready for the next message
                wait_hash_q <= 1'b0;
            end
        end
    end

    // ------------------------------------------------------------------
    // Wires between the blocks
    // ------------------------------------------------------------------

    // chunk controller -> tree controller
    logic           cv_valid;
    logic [255:0]   cv_out;
    logic           cv_last;

    // chunk controller <-> arbiter
    logic           chunk_in_valid;
    logic           chunk_in_ready;
    logic [255:0]   chunk_cv_in;
    logic [511:0]   chunk_block_in;
    logic [63:0]    chunk_counter;
    logic [6:0]     chunk_block_len;
    logic [7:0]     chunk_flags;
    logic           chunk_out_valid;
    logic [511:0]   chunk_out;

    // tree controller <-> arbiter
    logic           tree_in_valid;
    logic           tree_in_ready;
    logic [255:0]   tree_cv_in;
    logic [511:0]   tree_block_in;
    logic [63:0]    tree_counter;
    logic [6:0]     tree_block_len;
    logic [7:0]     tree_flags;
    logic           tree_out_valid;
    logic [511:0]   tree_out;

    // arbiter <-> compression core
    logic           core_in_valid;
    logic           core_in_ready;
    logic [255:0]   core_cv_in;
    logic [511:0]   core_block_in;
    logic [63:0]    core_counter;
    logic [6:0]     core_block_len;
    logic [7:0]     core_flags;
    logic           core_out_valid;
    logic [511:0]   core_out;

    // ------------------------------------------------------------------
    // The four blocks
    // ------------------------------------------------------------------

    blake3_chunk u_chunk (
        .clk            (clk),
        .rst_n          (rst_n),

        .blk_valid      (blk_valid),
        .blk_ready      (blk_ready),
        .blk_data       (in_data),
        .blk_len        (in_len),
        .blk_last       (blk_last),
        .blk_root       (blk_root),
        .blk_msg_last   (in_last),
        .chunk_index    (chunk_idx_q),

        .key            (key_words),
        .base_flags     (base_flags),

        .core_in_valid  (chunk_in_valid),
        .core_in_ready  (chunk_in_ready),
        .core_cv_in     (chunk_cv_in),
        .core_block_in  (chunk_block_in),
        .core_counter   (chunk_counter),
        .core_block_len (chunk_block_len),
        .core_flags     (chunk_flags),

        .core_out_valid (chunk_out_valid),
        .core_out       (chunk_out),

        .cv_valid       (cv_valid),
        .cv_out         (cv_out),
        .cv_last        (cv_last)
    );

    blake3_tree #(
        .STACK_DEPTH    (STACK_DEPTH)
    ) u_tree (
        .clk            (clk),
        .rst_n          (rst_n),

        .key            (key_words),
        .base_flags     (base_flags),

        .core_in_valid  (tree_in_valid),
        .core_in_ready  (tree_in_ready),
        .core_cv_in     (tree_cv_in),
        .core_block_in  (tree_block_in),
        .core_counter   (tree_counter),
        .core_block_len (tree_block_len),
        .core_flags     (tree_flags),

        .core_out_valid (tree_out_valid),
        .core_out       (tree_out),

        .chunk_cv_valid (cv_valid),
        .chunk_cv       (cv_out),
        .chunk_cv_last  (cv_last),

        .root_valid     (hash_valid),
        .root_out       (hash_out)
    );

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