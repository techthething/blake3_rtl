`default_nettype none

module blake3_compress (
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

    // define IV0 to IV3 constants
    localparam logic [31:0] IV0 = 32'h6A09E667;
    localparam logic [31:0] IV1 = 32'hBB67AE85;
    localparam logic [31:0] IV2 = 32'h3C6EF372;
    localparam logic [31:0] IV3 = 32'hA54FF53A;

    logic [511:0] state_init;
    logic [511:0] state_next;   

    logic [511:0] msg_next;

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
            out_valid <= busy_q && (round_q == 3'd6); // output valid if compression is active AND we are in the last round

            if (in_valid && in_ready) begin // new compression starts
                state_q <= state_init;
                msg_q <= block_in;
                cv_q <= cv_in;

                round_q <= 3'd0;
                busy_q <= 1;
            end else if (busy_q) begin
                state_q <= state_next;
                msg_q <= msg_next;
                round_q <= round_q + 3'd1;

                if (round_q == 3'd6) begin // set busy_q to 0 on the last round
                    busy_q <= 0;
                end
            end
        end
    end

endmodule

`default_nettype wire
