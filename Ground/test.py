from Checksum import calculate_checksum as check




a = bytearray(b'5\n$`\x16\x00\x0e\x00llis maximus augue, vel lacinia felis mollis quis. Vestibulum iaculis placerat faucibu\x84S')

b = bytearray(b'\xf2O$`\x16\x00\x0e\x00llis maximus augue, vel lacinia felis mollis quis. Vestibulum iaculis placerat faucibuVZ')

print(check(a[:-2]))