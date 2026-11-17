`default_nettype none
`include "blake3_assert.svh"

module blake3_compress #(
    // 0 = one full round per cycle (8 G functions: columns, then diagonals, in one cycle)
    // 1 = one round per two cycles: 4 shared G functions do the columns in the
    //     first cycle and the diagonals in the second (shorter critical path, half the G logic)
    parameter bit TWO_CYCLE_ROUND = 1'b0
) (
    // clock and reset
    input   logic            clk,
    input   logic            rst_n,

    // request in
    input   logic            in_valid,
    output  logic            in_ready,
    input   logic [255:0]    cv_in,
    input   logic [511:0]    block_in,
    input   logic [63:0]     counter,
    input   logic [6:0]      block_len,
    input   logic [7:0]      flags,

    // result out
    output  logic            out_valid,
    output  logic [511:0]    out
);

    logic [511:0] state_q;  // state register output
    logic [511:0] msg_q;    // message register output
    logic [255:0] cv_q;     // saved cv input register
    logic [2:0] round_q;    // what round (from 0 to 6) we are on
    logic busy_q;           // function is still going or already done
    logic phase_q;          // two-cycle mode only: 0 = column step next, 1 = diagonal step next

    // define IV0 to IV3 constants
    localparam logic [31:0] IV0 = 32'h6A09E667;
    localparam logic [31:0] IV1 = 32'hBB67AE85;
    localparam logic [31:0] IV2 = 32'h3C6EF372;
    localparam logic [31:0] IV3 = 32'hA54FF53A;

    logic [511:0] state_init;
    logic [511:0] state_next;   

    logic [511:0] msg_next;

    logic [511:0] step_next;    // state after this cycle's step (a full round, or half of one)
    logic         round_done;   // this cycle's step finishes a round
    logic         last_step;    // this cycle's step finishes the compression

    // define initial state saved to state register
    assign state_init = {
        {24'd0, flags},     // word 15
        {25'd0, block_len}, // word 14
        counter[63:32],     // word 13     
        counter[31:0],      // word 12
        IV3,                // word 11
        IV2,                // word 10
        IV1,                // word 9
        IV0,                // word 8
        cv_in               // word 7 to 0
    };

    assign in_ready = !busy_q; // compression core is ready when not busy 

    // ------------------------------------------------------------------
    // Round datapath
    // ------------------------------------------------------------------
    generate
        if (!TWO_CYCLE_ROUND) begin : g_full_round
        // One full round per cycle: 4 column G functions feed 4 diagonal G functions.

        // column steps

        logic [511:0] col_out;

        blake3_g g_col0 (
            .a      (state_q[32*0   +: 32]),
            .b      (state_q[32*4   +: 32]),
            .c      (state_q[32*8   +: 32]),
            .d      (state_q[32*12  +: 32]),
            .mx     (msg_q[32*0 +: 32]),
            .my     (msg_q[32*1 +: 32]),
            .a_out  (col_out[32*0   +: 32]),
            .b_out  (col_out[32*4   +: 32]),
            .c_out  (col_out[32*8   +: 32]),
            .d_out  (col_out[32*12   +: 32])
        );

        blake3_g g_col1 (
            .a      (state_q[32*1   +: 32]),
            .b      (state_q[32*5   +: 32]),
            .c      (state_q[32*9   +: 32]),
            .d      (state_q[32*13  +: 32]),
            .mx     (msg_q[32*2 +: 32]),
            .my     (msg_q[32*3 +: 32]),
            .a_out  (col_out[32*1   +: 32]),
            .b_out  (col_out[32*5   +: 32]),
            .c_out  (col_out[32*9   +: 32]),
            .d_out  (col_out[32*13   +: 32])
        );

        blake3_g g_col2 (
            .a      (state_q[32*2   +: 32]),
            .b      (state_q[32*6   +: 32]),
            .c      (state_q[32*10   +: 32]),
            .d      (state_q[32*14  +: 32]),
            .mx     (msg_q[32*4 +: 32]),
            .my     (msg_q[32*5 +: 32]),
            .a_out  (col_out[32*2   +: 32]),
            .b_out  (col_out[32*6   +: 32]),
            .c_out  (col_out[32*10   +: 32]),
            .d_out  (col_out[32*14   +: 32])
        );

        blake3_g g_col3 (
            .a      (state_q[32*3   +: 32]),
            .b      (state_q[32*7   +: 32]),
            .c      (state_q[32*11   +: 32]),
            .d      (state_q[32*15  +: 32]),
            .mx     (msg_q[32*6 +: 32]),
            .my     (msg_q[32*7 +: 32]),
            .a_out  (col_out[32*3   +: 32]),
            .b_out  (col_out[32*7   +: 32]),
            .c_out  (col_out[32*11   +: 32]),
            .d_out  (col_out[32*15   +: 32])
        );

        // diagonal steps

        blake3_g g_diag0 (
            .a      (col_out[32*0       +: 32]),
            .b      (col_out[32*5       +: 32]),
            .c      (col_out[32*10      +: 32]),
            .d      (col_out[32*15      +: 32]),
            .mx     (msg_q[32*8         +: 32]),
            .my     (msg_q[32*9         +: 32]),
            .a_out  (state_next[32*0    +: 32]),
            .b_out  (state_next[32*5    +: 32]),
            .c_out  (state_next[32*10   +: 32]),
            .d_out  (state_next[32*15   +: 32])
        );

        blake3_g g_diag1 (
            .a      (col_out[32*1       +: 32]),
            .b      (col_out[32*6       +: 32]),
            .c      (col_out[32*11      +: 32]),
            .d      (col_out[32*12      +: 32]),
            .mx     (msg_q[32*10        +: 32]),
            .my     (msg_q[32*11        +: 32]),
            .a_out  (state_next[32*1    +: 32]),
            .b_out  (state_next[32*6    +: 32]),
            .c_out  (state_next[32*11   +: 32]),
            .d_out  (state_next[32*12   +: 32])
        );

        blake3_g g_diag2 (
            .a      (col_out[32*2       +: 32]),
            .b      (col_out[32*7       +: 32]),
            .c      (col_out[32*8       +: 32]),
            .d      (col_out[32*13      +: 32]),
            .mx     (msg_q[32*12        +: 32]),
            .my     (msg_q[32*13        +: 32]),
            .a_out  (state_next[32*2    +: 32]),
            .b_out  (state_next[32*7    +: 32]),
            .c_out  (state_next[32*8    +: 32]),
            .d_out  (state_next[32*13   +: 32])
        );

        blake3_g g_diag3 (
            .a      (col_out[32*3       +: 32]),
            .b      (col_out[32*4       +: 32]),
            .c      (col_out[32*9       +: 32]),
            .d      (col_out[32*14      +: 32]),
            .mx     (msg_q[32*14        +: 32]),
            .my     (msg_q[32*15        +: 32]),
            .a_out  (state_next[32*3    +: 32]),
            .b_out  (state_next[32*4    +: 32]),
            .c_out  (state_next[32*9    +: 32]),
            .d_out  (state_next[32*14   +: 32])
        );

        assign step_next = state_next;

        end else begin : g_half_round
        // One round per two cycles: the same 4 G functions do the column step
        // (phase_q = 0) and then the diagonal step (phase_q = 1).
        //
        // Lane i always uses word i as its "a" input. Its b, c and d words are:
        //   column step:   4+i,           8+i,           12+i
        //   diagonal step: 4+(i+1)%4,     8+(i+2)%4,     12+(i+3)%4
        // and its message words are 2i, 2i+1 (columns) or 8+2i, 9+2i (diagonals).
        // Each lane writes its results back to the same words it read.

            logic [127:0] lane_a, lane_b, lane_c, lane_d;  // lane i's G outputs at [32*i +: 32]

            for (genvar i = 0; i < 4; i++) begin : g_lane
                blake3_g g (
                    .a      (state_q[32*i +: 32]),
                    .b      (phase_q ? state_q[32*(4  + (i+1)%4) +: 32] : state_q[32*(4  + i) +: 32]),
                    .c      (phase_q ? state_q[32*(8  + (i+2)%4) +: 32] : state_q[32*(8  + i) +: 32]),
                    .d      (phase_q ? state_q[32*(12 + (i+3)%4) +: 32] : state_q[32*(12 + i) +: 32]),
                    .mx     (phase_q ? msg_q[32*(8 + 2*i) +: 32]       : msg_q[32*(2*i)     +: 32]),
                    .my     (phase_q ? msg_q[32*(9 + 2*i) +: 32]       : msg_q[32*(2*i + 1) +: 32]),
                    .a_out  (lane_a[32*i +: 32]),
                    .b_out  (lane_b[32*i +: 32]),
                    .c_out  (lane_c[32*i +: 32]),
                    .d_out  (lane_d[32*i +: 32])
                );
            end

            // write back: word 4+k came from lane k (columns) or lane (k+3)%4 (diagonals),
            // word 8+k from lane k or (k+2)%4, word 12+k from lane k or (k+1)%4
            for (genvar k = 0; k < 4; k++) begin : g_writeback
                assign step_next[32*k        +: 32] = lane_a[32*k +: 32];
                assign step_next[32*(4  + k) +: 32] = phase_q ? lane_b[32*((k+3)%4) +: 32] : lane_b[32*k +: 32];
                assign step_next[32*(8  + k) +: 32] = phase_q ? lane_c[32*((k+2)%4) +: 32] : lane_c[32*k +: 32];
                assign step_next[32*(12 + k) +: 32] = phase_q ? lane_d[32*((k+1)%4) +: 32] : lane_d[32*k +: 32];
            end

        end
    endgenerate

    // a round ends every cycle (full mode) or every second cycle (two-cycle mode)
    assign round_done = TWO_CYCLE_ROUND ? phase_q : 1'b1;
    assign last_step  = round_done && (round_q == 3'd6);

    // message permutation

    assign msg_next = {
        msg_q[32*8  +:  32],    // new #15 = old #8
        msg_q[32*15 +:  32],    // new #14 = old #15
        msg_q[32*14 +:  32],    // new #13 = old #14
        msg_q[32*9  +:  32],    // new #12 = old #9
        msg_q[32*5  +:  32],    // new #11 = old #5
        msg_q[32*12 +:  32],    // new #10 = old #12
        msg_q[32*11 +:  32],    // new #9 = old #11
        msg_q[32*1  +:  32],    // new #8 = old #1
        msg_q[32*13 +:  32],    // new #7 = old #13
        msg_q[32*4  +:  32],    // new #6 = old #4
        msg_q[0     +:  32],    // new #5 = old #0
        msg_q[32*7  +:  32],    // new #4 = old #7
        msg_q[32*10 +:  32],    // new #3 = old #10
        msg_q[32*3  +:  32],    // new #2 = old #3
        msg_q[32*6  +:  32],    // new #1 = old #6
        msg_q[32*2  +:  32]     // new #0 = old #2
    };


    // feed forward and output generation

    always_comb begin
        for (int i = 0; i < 8; i++) begin
            out[32*i +: 32] = state_q[32*i +: 32] ^ state_q[32*(i+8) +: 32];
        end
        
        for (int i = 0; i < 8; i++) begin
            out[32*(i+8) +: 32] = state_q[32*(i+8) +: 32] ^ cv_q[32*i +: 32];
        end
    end

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            // reset
            busy_q <= 0;
            out_valid <= 0;
        end else begin
            out_valid <= busy_q && last_step; // output valid if compression is active AND this is its last step

            if (in_valid && in_ready) begin // new compression starts
                state_q <= state_init;
                msg_q <= block_in;
                cv_q <= cv_in;

                round_q <= 3'd0;
                phase_q <= 1'b0;
                busy_q <= 1;
            end else if (busy_q) begin
                state_q <= step_next;
                phase_q <= TWO_CYCLE_ROUND ? !phase_q : 1'b0; // alternate column / diagonal steps

                if (round_done) begin // the message is permuted once per round
                    msg_q <= msg_next;
                    round_q <= round_q + 3'd1;
                end

                if (last_step) begin // set busy_q to 0 on the last step
                    busy_q <= 0;
                end
            end
        end
    end

    // ------------------------------------------------------------------
    // Assertions (simulation and formal only; see blake3_assert.svh)
    // ------------------------------------------------------------------
`ifndef SYNTHESIS
    always @(posedge clk) begin
        if (rst_n) begin
            // input contract: a block holds at most 64 bytes
            `CHECK(!(in_valid && in_ready) || block_len <= 7'd64, "block_len above 64")

            // the round counter stays within the 7 rounds (0 to 6) while busy
            `CHECK(!busy_q || round_q <= 3'd6, "round_q went past round 6")

            // when the result appears, the core is already free for the next request
            `CHECK(!out_valid || in_ready, "out_valid high while still busy")
        end
    end
`endif

endmodule

`default_nettype wire
