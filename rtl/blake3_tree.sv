`default_nettype none

module blake3_tree #(
    parameter int STACK_DEPTH = 8 // default depth is 8, but can be adjusted
)   (
    // clock and reset
    input   logic           clk,
    input   logic           rst_n,

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

    // chunk value input (from the chunk controller)
    input   logic           chunk_cv_valid, // chunk value is arriving this cycle
    input   logic [255:0]   chunk_cv,
    input   logic           chunk_cv_last, // it is the message's last chunk
    
    // final outputs
    output  logic           root_valid,
    output  logic [255:0]   root_out
);

    // flag bits
    localparam logic [7:0] PARENT     = 8'd4;
    localparam logic [7:0] ROOT       = 8'd8;

    // state names
    localparam logic [1:0] IDLE       = 2'd0;
    localparam logic [1:0] MERGE      = 2'd1;
    localparam logic [1:0] WAIT_CORE  = 2'd2;

    // registers
    logic [1:0]                         state_q;
    logic [255:0]                       cur_q;
    logic [255:0]                       stack_q [STACK_DEPTH];  // values waiting for a merge partner
    logic [$clog2(STACK_DEPTH+1)-1:0]   sp_q;                   // stack pointer   
    logic [STACK_DEPTH:0]               count_q;                // total chunks so far
    logic [STACK_DEPTH:0]               merge_q;                // copy of count_q; merge while bit 0 is 0, shift right after each merge
    logic                               final_q;                // this is the message's last chunk
    logic                               pend_valid_q;           // a chunk is waiting in input buffer
    logic [255:0]                       pend_cv_q;              // waiting chunk value
    logic                               pend_last_q;            // whether it is last chunk

    // direct connections
    logic need_merge;

    assign core_cv_in       = key;
    assign core_counter     = 64'd0;
    assign core_block_len   = 7'd64;
    assign core_block_in    = {cur_q, stack_q[sp_q-1]}; // {right, left}
    assign core_flags       = base_flags | PARENT | ((final_q && sp_q == 1) ? ROOT : 8'd0); // ROOT on the merge that empties the stack

    assign need_merge = final_q ? (sp_q != 0) : (merge_q[0] == 1'b0);                       // merge if last chunk and there's something left on stack; if not last, merge if there is trailing 0

    assign core_in_valid = (state_q == MERGE) && need_merge;                                // holding a value that needs a merge
    assign root_valid    = (state_q == MERGE) && final_q && !need_merge;                    // final chunk, no merges left
    assign root_out      = cur_q;                                                           // the root ends up in cur_q

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            state_q         <= IDLE;
            sp_q            <= 0;
            count_q         <= 0;
            pend_valid_q    <= 0;
        end else begin
            if (state_q == IDLE) begin
                if (pend_valid_q) begin                 // a chunk value is waiting
                    cur_q           <= pend_cv_q;       // chunk value becomes current value
                    final_q         <= pend_last_q;     // record if it's the message's last chunk
                    count_q         <= count_q + 1;     // one more chunk finished
                    merge_q         <= count_q + 1;     // copy of the new count, used to decide merges
                    pend_valid_q    <= 0;               // buffer is now empty

                    state_q         <= MERGE;           // decide what to do with cur_q (merge, push, or output as root)
                end
            end
            
            if (state_q == MERGE) begin
                if (need_merge) begin                   // merge needed
                    if (core_in_ready) begin            // core accepts the merge request
                        state_q <= WAIT_CORE;
                    end
                end else if (final_q) begin             // final chunk and no merges left
                    count_q <= 0;                       // next message starts counting from 0
                    state_q <= IDLE;
                end else begin                          // not final and no merges left, push and wait for the next chunk
                    stack_q[sp_q] <= cur_q;             // write into the first empty slot
                    sp_q          <= sp_q + 1;
                    state_q       <= IDLE;
                end 
            end 

            if (state_q == WAIT_CORE) begin
                if (core_out_valid) begin               // merge result is ready
                    cur_q   <= core_out[255:0];         // the parent becomes the current value
                    sp_q    <= sp_q - 1;                // once value on top of stack has been merged, we pop it off
                    merge_q <= merge_q >> 1;            // one merge done, move to the next bit
                    state_q <= MERGE;                   // check whether another merge is needed
                end
            end

            if (chunk_cv_valid) begin                   // if chunk cv is valid, fill the input buffer
                pend_cv_q       <= chunk_cv;
                pend_last_q     <= chunk_cv_last;
                pend_valid_q    <= 1;
            end
        end
    end 
endmodule

`default_nettype wire