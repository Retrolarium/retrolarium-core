"""Enigma decoder kept as the oracle for the C++ port in retrolarium_core.

Ported verbatim from flicky_src scripts/formats/enigma_dec.py at commit
457eca1061047aec04fe5d6146958e8d0d0c8c77. It is no longer the implementation
Retrolarium uses - retrolarium_core owns that - but it stays here so the C++
decoder is checked against something written independently of it.

Worth knowing when reading this: modes 2 and 3 are unreachable. A six-bit code
is at most 0x1F after the shift, giving modes 0 and 1, and a seven-bit code is
always at least 0x40, giving modes 4 through 7. The C++ port reproduces this
rather than 'fixing' it.

Do not optimise or restructure this module. Its value is that it did not come
from the C++ code, and the parity corpus is generated from it.
"""

def decompress(data: bytes, base_tile: int = 0) -> bytes:
    """
    Decompress Enigma-compressed tilemap data.

    Args:
        data: Compressed data bytes
        base_tile: Base tile value to add to all tiles

    Returns:
        Decompressed tilemap data (big-endian words)
    """
    src = memoryview(data)
    pos = 0

    # Read header
    bits_count = src[pos]
    if bits_count >= 0x80:
        bits_count = bits_count - 0x100  # Sign extend
    pos += 1

    flags_byte = src[pos]
    if flags_byte >= 0x80:
        flags_byte = flags_byte - 0x100  # Sign extend
    pos += 1

    # Convert flags: ror.l #1, ror.w #1
    flags = flags_byte & 0xFFFFFFFF
    # ror.l #1
    flags = ((flags >> 1) | ((flags & 1) << 31)) & 0xFFFFFFFF
    # ror.w #1 (only low word)
    low = flags & 0xFFFF
    low = ((low >> 1) | ((low & 1) << 15)) & 0xFFFF
    flags = (flags & 0xFFFF0000) | low

    # Read inc_tile and static_tile (big-endian)
    inc_tile = ((src[pos] << 8) | src[pos + 1]) + base_tile
    pos += 2
    static_tile = ((src[pos] << 8) | src[pos + 1]) + base_tile
    pos += 2

    # Initialize bit buffer
    bit_buffer = (src[pos] << 8) | src[pos + 1]
    pos += 2
    bits_remaining = 16

    def refill():
        nonlocal bit_buffer, bits_remaining, pos
        if pos < len(src):
            bit_buffer = ((bit_buffer << 8) | src[pos]) & 0xFFFFFF
            pos += 1
        else:
            bit_buffer = (bit_buffer << 8) & 0xFFFFFF
        bits_remaining += 8

    def peek_bits(count):
        while bits_remaining < count:
            refill()
        shift = bits_remaining - count
        return (bit_buffer >> shift) & ((1 << count) - 1)

    def consume_bits(count):
        nonlocal bits_remaining
        bits_remaining -= count

    def get_bits(count):
        val = peek_bits(count)
        consume_bits(count)
        return val

    def decode_tile():
        tile = base_tile

        # Check vflip flag (bit 31)
        if flags & 0x80000000:
            if get_bits(1):
                tile |= 0x1000

        # Check hflip flag (bit 15)
        if flags & 0x8000:
            if get_bits(1):
                tile |= 0x0800

        # Read tile bits
        bits = bits_count
        if bits == 0:
            return tile

        if bits < 0:
            bits = -bits

        return tile + get_bits(bits)

    output = bytearray()

    while True:
        code = get_bits(7)
        repeat = code
        bits_used = 7

        if code < 0x40:
            bits_used = 6
            repeat >>= 1
            # Put back 1 bit
            bits_remaining += 1

        # Consume the bits we actually used (already consumed 7, adjust if 6)
        if bits_used == 6:
            pass  # Already adjusted above

        mode = (repeat >> 4) & 0x07
        repeat = repeat & 0x0F

        if mode == 0 or mode == 1:
            # Write incrementing from inc_tile
            for _ in range(repeat + 1):
                output.append((inc_tile >> 8) & 0xFF)
                output.append(inc_tile & 0xFF)
                inc_tile = (inc_tile + 1) & 0xFFFF

        elif mode == 2 or mode == 3:
            # Write static_tile repeated
            for _ in range(repeat + 1):
                output.append((static_tile >> 8) & 0xFF)
                output.append(static_tile & 0xFF)

        elif mode == 4:
            # Decode tile and write repeated
            tile = decode_tile()
            for _ in range(repeat + 1):
                output.append((tile >> 8) & 0xFF)
                output.append(tile & 0xFF)

        elif mode == 5:
            # Decode tile and write incrementing
            tile = decode_tile()
            for _ in range(repeat + 1):
                output.append((tile >> 8) & 0xFF)
                output.append(tile & 0xFF)
                tile = (tile + 1) & 0xFFFF

        elif mode == 6:
            # Decode tile and write decrementing
            tile = decode_tile()
            for _ in range(repeat + 1):
                output.append((tile >> 8) & 0xFF)
                output.append(tile & 0xFF)
                tile = (tile - 1) & 0xFFFF

        elif mode == 7:
            if repeat == 0x0F:
                # End marker
                break
            # Decode tiles inline
            for _ in range(repeat + 1):
                tile = decode_tile()
                output.append((tile >> 8) & 0xFF)
                output.append(tile & 0xFF)

    return bytes(output)
