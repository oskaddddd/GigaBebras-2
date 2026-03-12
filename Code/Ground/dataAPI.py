import struct
from sortedcontainers import SortedList
import json 

from time import sleep
import logging

from serial import Serial
from serial.tools import list_ports as list_ports

from operator import itemgetter

import numpy as np


logging.basicConfig(level=logging.DEBUG)

#A class to parse bytes into data based on type
class Unpack():
    def int8(self, b: bytes, start: int):
        return (struct.unpack_from('b', b, start)[0], 1)

    def int16(self, b: bytes, start: int):
        return (struct.unpack_from('h', b, start)[0], 2)

    def int32(self, b: bytes, start: int):
        return (struct.unpack_from('i', b, start)[0], 4)

    def uint8(self, b: bytes, start: int):
        return (struct.unpack_from('B', b, start)[0], 1)

    def uint16( self,b: bytes, start: int):
        return (struct.unpack_from('H', b, start)[0], 2)

    def uint32(self, b: bytes, start: int):
        return (struct.unpack_from('I', b, start)[0], 4)

    def float32(self, b: bytes, start: int):
        return (struct.unpack_from('f', b, start)[0], 4)
    
    def double(self, b: bytes, start: int):
        return (struct.unpack_from('d', b, start)[0], 8)
    
    def long(self, b: bytes, start: int):
        return (struct.unpack_from('l', b, start)[0], 4)
    
    def bit(self, b: bytes, start: int, bit: int):
        return((b[start]>>bit) & 1)
    
    def payload(self, b: bytes, start: int):
        return bytes[start:]
    
    def string(self, b: bytes, start: int, length: int):
        return b[start: length].decode('utf-8')
    



class DataMain():
    def __init__(self):
        
        #Object where all of the collected data is stored
        #Packets are stored in reverse order, so the newest one would have the index of 0
        self.path = "./Ground/assets/"
        
        self.data_packet_id = 0x01
        self.debug_packet_id = 0x00
        
        self.dictData = []
        self.dictDebug = []
        
        
        with open(self.path+"data.json", 'r') as f:
            self.dictData = json.load(f)
            if len(self.dictData) != 0:
                if input("There is data in data.json, clear to delete? y/n:") == 'y':
                    self.dictData = []
                else:
                    with open(self.path+"debug.json", 'r') as f:
                        self.dictDebug = json.load(f)
                
        self.debug_container = SortedList(self.dictDebug, key=lambda x: -x['timestamp'])
        self.data_container = bytearray()
        
        self.unpack = Unpack()
        self.packetCount = 0
        
        self.packetBuffer = bytearray()
        
        
        # Header Structure
        self.header_structure = (("headerId", self.unpack.uint16),
                                 ("id", self.unpack.uint8),
                                 ('length', self.unpack.uint8),
                                 ('timestamp', self.unpack.uint32))
        
        self.header_length = 0
        for _, parser in self.header_structure:
            self.header_length += self.get_item_length(parser)
        
        
        self.data_packet_structure = (('payload', self.unpack.payload, 1, 1))
        
        self.debug_packet_structure = (('angVelocity', self.unpack.int16, 3, 1/100),
                                       ('acceleration', self.unpack.int16, 3, 1/100),
                                       ('magneticField', self.unpack.int16, 3, 1/100),
                                       ('temprature', self.unpack.int16, 1, 1/100),
                                       ('humidity', self.unpack.uint8, 1, 1),
                                       ('preasure', self.unpack.uint32, 1, 1/1000),
                                       ('baterryVoltage', self.unpack.uint16, 1, 1/100),
                                       ('photoresistor', self.unpack.uint32, 1, 1)
                                       )
        
        
        self.match_packet_structure = {
            self.debug_packet_id:self.debug_packet_structure,
            self.data_packet_id:self.data_packet_structure
        }
        self.match_packet_buffer = {
            self.debug_packet_id:self.debug_container,
            self.data_packet_id:self.data_container
        }
 

        
  
        
        self.footerLength = 3
        
    def parse_data(self, byteSnipet:bytes):
        self.packetBuffer.extend(byteSnipet)
        logging.debug(self.packetBuffer, "packetbuffer")
        #Check the snippet and 2 earlier bytes for a Header Id
        index = self.packetBuffer[len(self.packetBuffer)-len(byteSnipet)-(len(self.id)-1):].find(self.id)
        
        if index != -1:
            #Check if that bytes before the startID is the end seq
            if self.packetBuffer[index-2:index] == b"\r\n":
                #Send finished packet for parsing 
                packet = self.packetBuffer[:index]
                
                #Check if this packet is fine, else throw it in the trash 
                if packet.startswith(self.id):
                    #Finally parse the packet
                    return self.parse_packet(packet)
                else:
                    logging.debug(f"Packet was fucked up 1:{packet}")
                #Set the buffer to only store the new packet
                self.packetBuffer = self.packetBuffer[index:]
            else:
                logging.debug(f"Packet was fucked up 2:{packet}")
                #Woooooo weee wooo weeeeeee
                #SOMETHING IS MAJORLY FUCKED UP
                
                #implement fix later
#
        
    def get_item_length(self, key):
        match key:
            case self.unpack.int8 | self.unpack.uint8:
                return 1
            case self.unpack.int16 | self.unpack.uint16:
                return 2
            case self.unpack.int32 | self.unpack.uint32 | self.unpack.float32 | self.unpack.long:
                return 4
            case self.unpack.double:
                return 8
            
    #A function that proccesses incoming packets from the Can 
    def parse_packet(self, packet:bytes) -> bytes: # returns the type of packet parsed 

        logging.debug(f"Started parsing packet nr{self.packetCount+1}: {packet.hex()}")
        
        header = {}
        payload = {}
        
        byte_i = 0

        # Parse header
        for key, parser in self.header_structure:
            header[key], l = parser(packet, byte_i)
            byte_i += l
        
        
        # Check if the length of the packet matches the actual length
        if len(packet) != header['length']:
            logging.warning("lengths dont match", packet)
            return -1


        payload = {'timestamp': header['timestamp']}
        
        # Loop through the packet and parse it based on the specified structure
        structure = self.match_packet_structure[header['id']]
        for key, parser, dimentions, transform in structure:
            
            # Create a temporary buffer to store the data for a certain key
            temp_container = [0]*dimentions
            
            # Parse the data and store in temp container
            for i in range(dimentions):  
                temp_container[i], l = parser(packet, byte_i)
                
                temp_container[i]*transform
                byte_i += l
            
            # Store the data in the payload
            if dimentions == 1: payload[key] = temp_container[0]
            else: payload[key] = temp_container
        
        
                
        # Return the type of packet 
        return header['id']
            
        
            

    #A function that deals with all the data
    def add_data(self, data: dict):
        self.DataBase.add(data)
        self.dictData.append(data)
        
        #Dump data into json
        with open(self.path + 'data.json', 'w') as f:
            json.dump(self.dictData, f, indent=4)
        
    
    #A function that deals with all the debug data
    def debug_data(self, data: dict):
        self.debug_container.add(data)
        self.dictDebug.append(data)
        
        #Dump debug data to json
        with open(self.path + 'debug.json', 'w') as f:
            json.dump(self.dictDebug, f, indent=4)
    #Funcion to get all of certain value from the sorted list
    def extraxtData(self, keyword:str, dtype:np.dtype = np.int32):
        getter = itemgetter(keyword)
        return np.array(list(map(getter, self.DataBase)), dtype=dtype)


#Establishes serial communication with the radio        
def SerialSetup(name:str = None, baund = 57600) -> Serial:
    
    
    
    if not name:
        #Find available ports and promt user to choose
        ports = list_ports.comports()
        print("\nCHOOSE POPRT\n------------")
        for i, port in enumerate(ports):
            if port.description!="n/a":
                print(f"({port.description})")
                print(f"[{i}] {port.name} {port.description}")

        ser = Serial(f"/dev/{ports[int(input('\nENTER SELECTION:'))].name}", baund)
    else:
        names = list(map(lambda x: x.name, list_ports.comports()))
        i = 1
        while name not in names:
            logging.warning(f'Serial [{name}] unavailable. Attempt #{i}, retrying...')
            i+=1
            sleep(1)
            names = list(map(lambda x: x.name, list_ports.comports()))
        ser = Serial(f"/dev/{name}", baund)


    
    #Wait till serial initialises
    i = 0
    while (not ser.is_open):
        logging.debug(f"Waiting for serial to begin:", i)
        i+=1
        sleep(1)
    
    logging.debug("Serial initialised!")

    
    return ser


if __name__ == "__main__":
    pass