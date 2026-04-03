a = b'\x24\xad'
from time import time
d = {b'\x00': 'miau'}
b = b'\x24\xad\x00'
c = bytearray()
c.extend(b)
print(b[:2] == a)
print(bytes(c[2:3]) in d)
print([x for x in c])
del c[:1]
print([x for x in c])