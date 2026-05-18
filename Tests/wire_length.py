a = 20 # length 1
b =  25 # length 2

h = 30
d = 6 # distence between conencting rods

tie_off_length = 1.5

from math import sqrt

def pythogar(a, b):
    return (sqrt(a**2+b**2))

r = (a+b*sqrt(2))/2

wire_1 = pythogar((a-d)/2, r)
wire_2 = pythogar(r-d/2, a/2)

wire_1 = pythogar(wire_1, h)
wire_2 = pythogar(wire_2, h)

print(f"wire 1:  {round(wire_1, 3)}\nwire 2:  {round(wire_2, 3)}\ndiff:  {round(wire_1-wire_2, 3)} \ntotal wire without tieoff:  {round(4*(wire_1+wire_2), 3)}\ntotal wire:  {round(4*(wire_1+wire_2+2*tie_off_length), 3)}")