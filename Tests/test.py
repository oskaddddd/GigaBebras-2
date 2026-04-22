import test_import
print('init')
from time import sleep
print(test_import.a)
test_import.a.append(4)
sleep(1)
a = test_import.hello()
print(test_import.a)