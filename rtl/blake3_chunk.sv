`default_nettype none

module blake3_chunk (
    // clock and reset
    input   logic           clk,
    input   logic           rst_n,

    // block input (from the block source)
    input   logic           blk_valid,
    output  logic           blk_ready,
    input   logic [511:0]   blk_data,
    input   logic [6:0]     blk_len,       // real bytes in this block, 0 to 64
    input   logic           blk_last,      // last block of this chunk
    input   logic           blk_root,      // this chunk is the whole message
    input   logic           blk_msg_last,  // last block of the whole message
    input   logic [63:0]    chunk_index,

    // hash settings (fixed for a whole message)
    input   logic [255:0]   key,           // user key, or the IV in plain mode
    input   logic [7:0]     base_flags,    // KEYED_HASH in keyed mode, else 0

    // compression core interface (request out)
    output  logic           core_in_valid,
    input   logic           core_in_ready,
    output  logic [255:0]   core_cv_in,
    output  logic [511:0]   core_block_in,
    output  logic [63:0]    core_counter,
    output  logic [6:0]     core_block_len,
    output  logic [7:0]     core_flags,

    // compression core interface (result back)
    input   logic           core_out_valid,
    input   logic [511:0]   core_out,

    // chunk value output (to the tree controller)
    output  logic           cv_valid,
    output  logic [255:0]   cv_out,
    output  logic           cv_last        // this chunk is the message's last chunk (valid with cv_valid)
);

    // flag bits
    localparam logic [7:0]  CHUNK_START = 8'd1; 
    localparam logic [7:0]  CHUNK_END   = 8'd2;
    localparam logic [7:0]  ROOT        = 8'd8;

    // state names
    localparam logic WAIT_BLOCK = 1'b0;
    localparam logic WAIT_CORE  = 1'b1;

    // registers
    logic state_q;      // WAIT_BLOCK or WAIT_CORE
    logic first_q;      // next block is the chunk's first
    logic last_q;       // current block is the chunk's last one
    logic msg_last_q;   // current block is the message's last one
    logic [255:0] cv_q; // chaining value

    // direct connections to core 
    assign core_block_in  = blk_data;
    assign core_block_len = blk_len;
    assign core_counter   = chunk_index;

    assign core_cv_in = first_q ? key : cv_q; // mux outputs key if first block or cv_q if not

    assign core_flags = base_flags  | (first_q ? CHUNK_START : 8'd0)            
                                    | (blk_last ? CHUNK_END : 8'd0) 
                                    | ((blk_last && blk_root) ? ROOT : 8'd0);

    assign blk_ready = (state_q == WAIT_BLOCK) && core_in_ready; // ready to take in a block
        
    assign core_in_valid = (state_q == WAIT_BLOCK) && blk_valid; // pass the block onto the core
        
    assign cv_valid = core_out_valid && last_q; // result is back, and it was the last block

    assign cv_out = core_out[255:0]; // chaining value half of the core's result 

    assign cv_last  = msg_last_q;     // saved from the chunk's last block, so valid when cv_valid is 1

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            state_q <= WAIT_BLOCK;
            first_q <= 1;
        end else begin
            if (state_q == WAIT_BLOCK) begin
                if (blk_valid && blk_ready) begin
                    state_q <= WAIT_CORE;           // block has been sent to core, wait for result
                    first_q <= 0;                   // any block after this is not the first one
                    last_q <= blk_last;             // store whether this block ends the chunk
                    msg_last_q <= blk_msg_last;     // remember whether this block ends the message
                end
            end else begin // WAIT_CORE
                if (core_out_valid) begin
                    cv_q <= core_out[255:0];        // store chaining value for next block
                    state_q <= WAIT_BLOCK;          // received result, ready for next block

                    if (last_q) begin
                        first_q <= 1;               // if this is chunk's last block, the next block starts a new chunk
                    end
                end
            end
        end
    end
endmodule