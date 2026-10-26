`default_nettype none

module blake3_arbiter (
    // clock and reset
    input   logic           clk,
    input   logic           rst_n,

    // chunk controller side: request in
    input   logic           chunk_in_valid,
    output  logic           chunk_in_ready,
    input   logic [255:0]   chunk_cv_in,
    input   logic [511:0]   chunk_block_in,
    input   logic [63:0]    chunk_counter,
    input   logic [6:0]     chunk_block_len,
    input   logic [7:0]     chunk_flags,

    // chunk controller side: result out
    output  logic           chunk_out_valid,
    output  logic [511:0]   chunk_out,

    // tree controller side: request in
    input   logic           tree_in_valid,
    output  logic           tree_in_ready,
    input   logic [255:0]   tree_cv_in,
    input   logic [511:0]   tree_block_in,
    input   logic [63:0]    tree_counter,
    input   logic [6:0]     tree_block_len,
    input   logic [7:0]     tree_flags,

    // tree controller side: result out
    output  logic           tree_out_valid,
    output  logic [511:0]   tree_out,

    // compression core side: request out
    output  logic           core_in_valid,
    input   logic           core_in_ready,
    output  logic [255:0]   core_cv_in,
    output  logic [511:0]   core_block_in,
    output  logic [63:0]    core_counter,
    output  logic [6:0]     core_block_len,
    output  logic [7:0]     core_flags,

    // compression core side: result back
    input   logic           core_out_valid,
    input   logic [511:0]   core_out
);

    logic grant_tree;   // 1 = the tree controller's request goes to the core this cycle
    logic owner_q;      // whose request is in the core: 1 = tree controller, 0 = chunk controller

    // choose: the tree controller has priority, so it wins whenever it is asking
    assign grant_tree    = tree_in_valid;

    // the core sees a request if either side is asking
    assign core_in_valid = chunk_in_valid || tree_in_valid;

    // forward the chosen side's request to the core
    assign core_cv_in     = grant_tree ? tree_cv_in     : chunk_cv_in;
    assign core_block_in  = grant_tree ? tree_block_in  : chunk_block_in;
    assign core_counter   = grant_tree ? tree_counter   : chunk_counter;
    assign core_block_len = grant_tree ? tree_block_len : chunk_block_len;
    assign core_flags     = grant_tree ? tree_flags     : chunk_flags;

    // ready back: each side is only ready when its request would really be taken
    assign tree_in_ready  = core_in_ready;                      // the tree controller always wins
    assign chunk_in_ready = core_in_ready && !tree_in_valid;    // the chunk controller waits while the tree controller is asking

    // result back: only the side that owns the request sees out_valid
    assign chunk_out_valid = core_out_valid && !owner_q;
    assign tree_out_valid  = core_out_valid &&  owner_q;
    assign chunk_out       = core_out;  // both sides see the data; out_valid says whose it is
    assign tree_out        = core_out;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            owner_q <= 0;
        end else if (core_in_valid && core_in_ready) begin   // the core accepts a request
            owner_q <= grant_tree;                            // remember whose it is
        end
    end

endmodule

`default_nettype wire