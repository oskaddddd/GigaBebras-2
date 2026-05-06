import json

d = None
a = 0
with open('./Ground/Assets/packet_data.json', 'r') as f:
    d = json.load(f)
    
    for i in range(len(d["x"])):
        print(i)
        if i == 0:
            a = d['x'][0]
            
        d['x'][i] -=  a
        print(d['x'][i])

with open('./Ground/Assets/packet_data.json', 'w') as f:
    json.dump(d, f)