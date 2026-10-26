# blake3.py - Python BLAKE3 Implementation

# 1. CONSTANTS & HELPER FUNCTIONS

# Initialization Vector (IV) constants matching BLAKE2s / BLAKE3 specification
IV = [
    0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A,
    0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19
]

# Message Permutation schedule applied at the end of each round (Rounds 0 to 5)
MSG_PERMUTATION = [2, 6, 3, 10, 7, 0, 4, 13, 1, 11, 12, 5, 9, 14, 15, 8]

# Domain Separation Bit Flags
CHUNK_START         = 1 << 0  # 1
CHUNK_END           = 1 << 1  # 2
PARENT              = 1 << 2  # 4
ROOT                = 1 << 3  # 8
KEYED_HASH          = 1 << 4  # 16
DERIVE_KEY_CONTEXT  = 1 << 5  # 32
DERIVE_KEY_MATERIAL = 1 << 6  # 64


def rotr32(x: int, n: int) -> int:
    """32-bit Right Rotate operation (maps to hardware wire routing)."""
    return ((x >> n) | (x << (32 - n))) & 0xFFFFFFFF


# 2. COMBINATIONAL LOGIC

def g(state: list[int], a: int, b: int, c: int, d: int, mx: int, my: int):

    # 1. Addition: Mix state[b] and message word mx into state[a]
    # Hardware: 32-bit ripple-carry or carry-lookahead adder.
    state[a] = (state[a] + state[b] + mx) & 0xFFFFFFFF

    # 2. XOR & Rotate 16: Diffuse changes from state[a] down into state[d]
    # Hardware: 32 bitwise XOR gates followed by a 16-bit wire swap.
    state[d] = rotr32(state[d] ^ state[a], 16)

    # 3. Addition: Fold updated state[d] into state[c]
    state[c] = (state[c] + state[d]) & 0xFFFFFFFF

    # 4. XOR & Rotate 12: Diffuse updated state[c] back into state[b]
    state[b] = rotr32(state[b] ^ state[c], 12)

    # 5. Addition: Mix state[b] and message word my into state[a]
    state[a] = (state[a] + state[b] + my) & 0xFFFFFFFF

    # 6. XOR & Rotate 8: Diffuse into state[d] using an 8-bit rotation
    state[d] = rotr32(state[d] ^ state[a], 8)

    # 7. Addition: Fold updated state[d] into state[c]
    state[c] = (state[c] + state[d]) & 0xFFFFFFFF

    # 8. XOR & Rotate 7: Final diffusion into state[b] using a 7-bit rotation
    state[b] = rotr32(state[b] ^ state[c], 7)


def compress(chaining_value: list[int], block_words: list[int],
             counter: int, block_len: int, flags: int) -> list[int]:

    # Word 14 is a per-block byte count, so it can never exceed 64.
    assert 0 <= block_len <= 64, f"block_len {block_len} out of range (0..64)"

    # STEP 1: INITIALIZE MATRIX REGISTERS (16 x 32-bit registers)
    state = [0] * 16

    # Words 0 through 7 receive the chaining value passed from the previous block (or key/IV)
    state[0:8] = chaining_value[0:8]

    # Words 8 through 11 receive fixed constant IV values
    state[8:12] = IV[0:4]

    # Words 12 and 13 store the 64-bit counter (t0 = lower 32 bits, t1 = upper 32 bits).
    # Chunk blocks: the chunk index. Parent nodes: 0. Root output: the output block number.
    state[12] = counter & 0xFFFFFFFF
    state[13] = (counter >> 32) & 0xFFFFFFFF

    # Word 14 stores the actual byte length of data in this block (0 to 64)
    state[14] = block_len

    # Word 15 stores control flags (CHUNK_START, CHUNK_END, PARENT, ROOT, etc.)
    state[15] = flags

    # Make a local working copy of the 16 message words (m0..m15)
    m = list(block_words)

    # STEP 2: RUN 7 MIXING ROUNDS
    # In hardware, this is an FSM loop running 7 times, or 7 unrolled pipelined stages
    for r in range(7):

        # Column Step
        g(state, 0, 4,  8, 12, m[0], m[1])
        g(state, 1, 5,  9, 13, m[2], m[3])
        g(state, 2, 6, 10, 14, m[4], m[5])
        g(state, 3, 7, 11, 15, m[6], m[7])

        # Diagonal Step
        g(state, 0, 5, 10, 15, m[8],  m[9])
        g(state, 1, 6, 11, 12, m[10], m[11])
        g(state, 2, 7,  8, 13, m[12], m[13])
        g(state, 3, 4,  9, 14, m[14], m[15])

        # Message Permutation
        # Permute message array entries so the next round operates on different word pairings.
        # This occurs after rounds 0, 1, 2, 3, 4, and 5 (skipped after round 6).
        if r < 6:
            m = [m[MSG_PERMUTATION[i]] for i in range(16)]

    # STEP 3: FEED-FORWARD & OUTPUT GENERATION
    out = [0] * 16

    # XOR top two rows of final matrix state with bottom two rows
    for i in range(8):
        out[i] = state[i] ^ state[i + 8]

    # XOR bottom two rows of final matrix state with the original input chaining value
    for i in range(8):
        out[i + 8] = state[i + 8] ^ chaining_value[i]

    return out


def bytes_to_words32(data: bytes) -> list[int]:
    """
    Converts a stream of raw 8-bit bytes into 32-bit little-endian integer words.
    Hardware: Equivalent to a Byte-to-Word deserializer FIFO buffer.
    """
    words = []
    for i in range(0, len(data), 4):
        words.append(int.from_bytes(data[i:i + 4], 'little'))
    return words


class ChunkState:
    def __init__(self, key_words: list[int], chunk_idx: int, flags: int):
        self.chaining_value = list(key_words)  # Initial CV (Key or IV)
        self.chunk_idx = chunk_idx             # Absolute 0-indexed position of chunk
        self.flags = flags                     # Domain flags
        self.block_buffer = bytearray()        # Temporary byte buffer

        # Inputs of the most recent compress() call, i.e. the chunk's LAST
        # block once output_cv() returns. XOF must replay exactly this call.
        # Hardware: registers held stable while squeezing extra output blocks.
        self.last_cv_in: list[int] = list(key_words)
        self.last_words: list[int] = [0] * 16
        self.last_block_len: int = 0
        self.last_flags: int = flags

    def update(self, data: bytes):
        """Buffers raw bytes into the chunk state."""
        self.block_buffer.extend(data)
        assert len(self.block_buffer) <= 1024, "a chunk holds at most 1024 bytes"

    def output_cv(self, is_root: bool = False) -> tuple[list[int], list[int]]:
        """
        Compresses all 64-byte blocks inside this 1024-byte chunk.
        Returns (8-word CV, 16-word full output).
        """
        total_bytes = len(self.block_buffer)
        offset = 0

        cv = list(self.chaining_value)
        out = []

        # Process block buffer 64 bytes at a time.
        # `or offset == 0` makes an empty chunk run exactly one 0-byte block.
        while offset < total_bytes or offset == 0:
            block = bytes(self.block_buffer[offset:offset + 64])
            block_len = len(block)

            # Pad incomplete final block with 0x00 up to 64 bytes
            padded_block = block + b'\x00' * (64 - block_len)
            words = bytes_to_words32(padded_block)

            # Construct boundary flags for this block
            current_flags = self.flags
            if offset == 0:
                current_flags |= CHUNK_START  # First block of this 1024-byte chunk
            if (offset + 64) >= total_bytes:
                current_flags |= CHUNK_END    # Last block of this 1024-byte chunk
            if is_root and ((offset + 64) >= total_bytes):
                current_flags |= ROOT         # Final block of the entire hash tree

            # Remember exactly what goes into this compression
            self.last_cv_in = cv
            self.last_words = words
            self.last_block_len = block_len
            self.last_flags = current_flags

            # Execute hardware compression step
            out = compress(cv, words, self.chunk_idx, block_len, current_flags)

            # Chain the first 8 output words as the CV for the next block
            cv = out[0:8]
            offset += 64

        return cv, out


def parent_cv(left_child_cv: list[int], right_child_cv: list[int],
              key_words: list[int], flags: int) -> list[int]:
    """Compresses two 8-word child CVs into a single 8-word parent CV"""
    block_words = left_child_cv + right_child_cv

    # Parent compression sets PARENT flag, counter = 0, block_len = 64
    out = compress(key_words, block_words, counter=0, block_len=64, flags=flags | PARENT)
    return out[0:8]


class Blake3Tree:
    def __init__(self, key_words: list[int] | None = None, flags: int = 0):
        self.key_words = list(key_words) if key_words is not None else list(IV)
        self.flags = flags
        self.cv_stack: list[list[int]] = []  # Hardware: Finite Depth Stack RAM

    def add_chunk_cv(self, new_cv: list[int], total_chunks: int):
        """
        Pushes a new chunk CV to the stack. Automatically collapses matching sibling
        nodes into parent nodes whenever subtree pairs are completed.

        The number of parent merges required equals the count of trailing zeros in
        the binary representation of total_chunks (1-indexed count of chunks so far).
        """
        assert total_chunks > 0, "total_chunks is 1-indexed; 0 would never terminate"
        while total_chunks & 1 == 0:
            left_child = self.cv_stack.pop()
            new_cv = parent_cv(left_child, new_cv, self.key_words, self.flags)
            total_chunks >>= 1  # Shift right to check next tree layer height

        self.cv_stack.append(new_cv)


class Blake3:
    def __init__(self, key_words: list[int] | None = None, flags: int = 0):
        self.key_words = list(key_words) if key_words is not None else list(IV)
        self.flags = flags

    def hash(self, data: bytes, out_len: int = 32) -> bytes:
        """Main entry point: Computes an arbitrary-length BLAKE3 hash"""
        # Local tree, so hash() keeps no state between calls
        tree = Blake3Tree(self.key_words, self.flags)

        data_len = len(data)

        # PATH A: Single Chunk Fast Path (Data <= 1024 Bytes)
        if data_len <= 1024:
            chunk = ChunkState(self.key_words, 0, self.flags)
            chunk.update(data)
            _, root_out = chunk.output_cv(is_root=True)
            return self._squeeze_xof(root_out, chunk, out_len)

        # PATH B: Multi-Chunk Tree Hashing Path (Data > 1024 Bytes)
        offset = 0
        chunk_idx = 0
        last_chunk_data = b""

        while offset < data_len:
            chunk_data = data[offset:offset + 1024]
            offset += 1024

            if offset < data_len:
                # Standard internal chunk: Compress and push CV to tree stack
                chunk = ChunkState(self.key_words, chunk_idx, self.flags)
                chunk.update(chunk_data)
                cv, _ = chunk.output_cv(is_root=False)
                chunk_idx += 1
                tree.add_chunk_cv(cv, chunk_idx)
            else:
                # Hold the final chunk out of the stack for root parent assembly
                last_chunk_data = chunk_data
                chunk_idx += 1

        # Process final chunk leaf node
        final_chunk = ChunkState(self.key_words, chunk_idx - 1, self.flags)
        final_chunk.update(last_chunk_data)
        final_cv, _ = final_chunk.output_cv(is_root=False)

        # Reduce all remaining tree stack entries into the final ROOT parent node
        while len(tree.cv_stack) > 0:
            left_child = tree.cv_stack.pop()

            if len(tree.cv_stack) == 0:
                # Final Merge: Set ROOT flag to generate full hash digest
                parent_block = left_child + final_cv
                root_out = compress(self.key_words, parent_block, counter=0,
                                    block_len=64, flags=self.flags | PARENT | ROOT)
                return self._finalize_xof_bytes(root_out, parent_block, out_len)
            else:
                # Non-root parent merge
                final_cv = parent_cv(left_child, final_cv, self.key_words, self.flags)

        # Unreachable: data > 1024 bytes always leaves >= 1 stack entry.
        raise AssertionError("tree stack was empty on the multi-chunk path")

    def _squeeze_xof(self, initial_root_out: list[int], chunk: 'ChunkState', out_len: int) -> bytes:
        """Squeezes variable-length output bytes for single-chunk inputs."""
        out_bytes = bytearray()

        # Grab first 64 output bytes from initial root compression
        for w in initial_root_out:
            out_bytes.extend(w.to_bytes(4, 'little'))

        # Extra output blocks replay the chunk's LAST block compression with
        # identical CV, message words, block_len and flags; only the counter changes.
        counter = 1
        while len(out_bytes) < out_len:
            out = compress(chunk.last_cv_in, chunk.last_words, counter,
                           chunk.last_block_len, chunk.last_flags)
            for w in out:
                out_bytes.extend(w.to_bytes(4, 'little'))
            counter += 1

        return bytes(out_bytes[:out_len])

    def _finalize_xof_bytes(self, initial_out: list[int], parent_block: list[int], out_len: int) -> bytes:
        """Squeezes variable-length output bytes for multi-chunk tree outputs."""
        out_bytes = bytearray()

        for w in initial_out:
            out_bytes.extend(w.to_bytes(4, 'little'))

        counter = 1
        # Continuously re-compress the ROOT parent node with incremented counter values
        while len(out_bytes) < out_len:
            out = compress(self.key_words, parent_block, counter, 64, self.flags | PARENT | ROOT)
            for w in out:
                out_bytes.extend(w.to_bytes(4, 'little'))
            counter += 1

        return bytes(out_bytes[:out_len])