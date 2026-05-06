side_length = 21.3
h = 20
wire_distance = 6

tie_off_length = 1.5

from math import sqrt
r = (sqrt(2)+1)/2*side_length
a = sqrt(((side_length-wire_distance)/2)**2 + r**2)

b = sqrt((side_length/2)**2 + (r - wire_distance/2)**2)
a_len = sqrt(a**2+h**2)
b_len = sqrt(b**2 + h**2)
print(f"wire 1:  {round(a_len, 3)}\nwire 2:  {round(b_len, 3)}\ndiff:  {round(a_len-b_len, 3)} \ntotal wire without tieoff:  {round(4*(a_len+b_len), 3)}\ntotal wire:  {round(4*(a_len+b_len+2*tie_off_length), 3)}")