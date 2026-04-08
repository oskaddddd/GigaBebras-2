def calculate_checksum(data: bytes) -> bytes:
    """
    Calculate a 2-byte Fletcher-16 checksum of the input bytes object.
    Returns the checksum as a 2-byte bytes object.
    """
    sum1 = 0
    sum2 = 0
    for byte in data:
        sum1 = (sum1 + byte) % 255
        sum2 = (sum2 + sum1) % 255
    return bytes([sum1, sum2])