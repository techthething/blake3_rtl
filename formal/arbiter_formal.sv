`default_nettype none

// Formal harness for blake3_arbiter.
//
// The solver drives every arbiter input freely, every cycle, and searches for
// ANY input sequence that breaks an assertion. The "assume" lines limit it to
// what the real compression core can do (otherwise it could, for example,
// return a result nobody asked for). Everything else is unrestricted: both
// controllers may request, stop, and change their data at any time.
//
// Besides the checks inside blake3_arbiter.sv, this harness adds end-to-end
// checks written only from the outside handshakes, without looking at the
// arbiter's internal owner_q:
//   - whatever the core accepts is exactly the accepted side's request
//   - every result goes back to the side whose request produced it

module arbiter_formal (
    input   logic           clk,
    input   logic           rst_n,

    input   logic           chunk_in_valid,
    input   logic [255:0]   chunk_cv_in,
    input   logic [511:0]   chunk_block_in,
    input   logic [63:0]    chunk_counter,
    input   logic [6:0]     chunk_block_len,
    input   logic [7:0]     chunk_flags,

    input   logic           tree_in_valid,
    input   logic [255:0]   tree_cv_in,
    input   logic [511:0]   tree_block_in,
    input   logic [63:0]    tree_counter,
    input   logic [6:0]     tree_block_len,
    input   logic [7:0]     tree_flags,

    input   logic           core_in_ready,
    input   logic           core_out_valid,
    input   logic [511:0]   core_out
);

    logic           chunk_in_ready, tree_in_ready;
    logic           chunk_out_valid, tree_out_valid;
    logic [511:0]   chunk_out, tree_out;
    logic           core_in_valid;
    logic [255:0]   core_cv_in;
    logic [511:0]   core_block_in;
    logic [63:0]    core_counter;
    logic [6:0]     core_block_len;
    logic [7:0]     core_flags;

    blake3_arbiter dut (.*);

    // ------------------------------------------------------------------
    // Start in reset
    // ------------------------------------------------------------------
    logic init_q = 1'b1;    // 1 only in the very first cycle

    always @(posedge clk) begin
        init_q <= 1'b0;
        if (init_q) assume (!rst_n);
    end

    // ------------------------------------------------------------------
    // Model of the compression core's behavior (assumptions)
    // ------------------------------------------------------------------
    logic       busy_q;     // a request is inside the core
    logic [3:0] age_q;      // cycles since the core accepted it

    always @(posedge clk) begin
        if (!rst_n) begin
            busy_q <= 1'b0;
        end else if (core_in_valid && core_in_ready) begin
            busy_q <= 1'b1;
            age_q  <= 4'd0;
        end else if (core_out_valid) begin
            busy_q <= 1'b0;
        end else if (busy_q && age_q != 4'd15) begin
            age_q  <= age_q + 4'd1;
        end
    end

    always @(*) begin
        if (rst_n) begin
            // a result only comes back for a request the core accepted
            assume (!core_out_valid || busy_q);
            // while busy, the core is ready again only in the cycle its result
            // appears (this is how blake3_compress behaves)
            assume (!busy_q || (core_in_ready == core_out_valid));
            // the result arrives within 8 cycles (the real core takes exactly 8);
            // the solver may return it any time up to then
            assume (!(busy_q && age_q >= 4'd7) || core_out_valid);
        end
    end

    // ------------------------------------------------------------------
    // End-to-end checks, from the outside handshakes only
    // ------------------------------------------------------------------
    logic chunk_accept, tree_accept, core_accept;
    assign chunk_accept = chunk_in_valid && chunk_in_ready;
    assign tree_accept  = tree_in_valid  && tree_in_ready;
    assign core_accept  = core_in_valid  && core_in_ready;

    logic side_q;           // whose request is in the core, per the handshakes: 1 = tree

    always @(posedge clk) begin
        if (core_accept) side_q <= tree_accept;
    end

    always @(posedge clk) begin
        if (rst_n && !init_q) begin
            // a request is accepted from a side exactly when the core accepts one
            assert (core_accept == (chunk_accept || tree_accept));

            // what the core receives is exactly the accepted side's request
            if (tree_accept) begin
                assert (core_cv_in == tree_cv_in && core_block_in == tree_block_in &&
                        core_counter == tree_counter && core_block_len == tree_block_len &&
                        core_flags == tree_flags);
            end
            if (chunk_accept) begin
                assert (core_cv_in == chunk_cv_in && core_block_in == chunk_block_in &&
                        core_counter == chunk_counter && core_block_len == chunk_block_len &&
                        core_flags == chunk_flags);
            end

            // every result goes to the side whose request produced it, with the core's data
            if (core_out_valid) begin
                assert (tree_out_valid == side_q && chunk_out_valid == !side_q);
                assert (tree_out == core_out && chunk_out == core_out);
            end
        end
    end

    // ------------------------------------------------------------------
    // Cover points: situations the solver must be able to reach. If one is
    // unreachable, the assumptions are too strict and the proof means less.
    // ------------------------------------------------------------------
    always @(posedge clk) begin
        if (rst_n && !init_q) begin
            cover (chunk_accept);                                   // chunk side gets the core
            cover (tree_accept);                                    // tree side gets the core
            cover (chunk_in_valid && tree_accept);                  // both ask: tree wins
            cover (chunk_out_valid);                                // a result goes to the chunk side
            cover (tree_out_valid);                                 // a result goes to the tree side
            cover (core_out_valid && core_accept);                  // result out and next request in, same cycle
        end
    end

endmodule

`default_nettype wire
