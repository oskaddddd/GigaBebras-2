import json
dictData = []

with open("./Assets/data.json", 'r') as f:
    dictData = json.load(f)
    for i in range(len(dictData)):
        dictData[i]["pollution"] = dictData[i]["height"]
    
with open("./GroundMain/assets/data.json", 'w') as f:
    json.dump(dictData, f)
    
    
