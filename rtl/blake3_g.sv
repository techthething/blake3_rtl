`default_nettype none

module blake3_g (
    input   logic [31:0] a,
    input   logic [31:0] b,
    input   logic [31:0] c,
    input   logic [31:0] d,
    input   logic [31:0] mx,
    input   logic [31:0] my,
    output  logic [31:0] a_out,
    output  logic [31:0] b_out,
    output  logic [31:0] c_out,
    output  logic [31:0] d_out
);

    function automatic logic [31:0] rotr32(input logic [31:0] x, input int n);
        rotr32 = (x >> n) | (x << (32 - n)); // assigning to the function name sets its result (Yosys does not support return)
    endfunction

    logic [31:0] a1, b1, c1, d1;

    assign a1 = a + b + mx;                 // step 1
    assign d1 = rotr32(a1 ^ d, 16);         // step 2
    assign c1 = d1 + c;                     // step 3
    assign b1 = rotr32(c1 ^ b, 12);         // step 4
    assign a_out = b1 + a1 + my;            // step 5
    assign d_out = rotr32(a_out ^ d1, 8);   // step 6
    assign c_out = d_out + c1;              // step 7
    assign b_out = rotr32(c_out ^ b1, 7);   // step 8

endmodule

`default_nettype wire
