from radio_manager import radio_serial
import logging
import threading
from time import time, sleep
from Constants import Constants as C

from queue import Queue

from math import ceil
from sortedcontainers import SortedList

from Checksum import calculate_checksum

from gradient import gradient

import json

import numpy as np
from operator import itemgetter



logging.getLogger().setLevel(logging.DEBUG)


class debug_manager():
    def __init__(self):
        self.debug_dict = []



        with open("./Ground/Assets/debug.json", 'r') as f:
            self.debug_dict = json.load(f)
            if len(self.debug_dict) != 0:
                if input("There is data in debug.json, clear to delete? y/n:") == 'y':
                    self.debug_dict = []

        self.debug_data = SortedList(self.debug_dict, key=lambda x: -x['timestamp'])
        
    def store_debug_packet(self, payload):
        self.debug_data.add(payload)
        self.debug_dict.append(payload)
        
        #Dump data into json
        with open('./Ground/Assets/debug.json', 'w') as f:
            json.dump(self.debug_dict, f, indent=4)
        
    def extraxtData(self, keyword:str, dtype:np.dtype = np.int32):
        getter = itemgetter(keyword)
        return np.array(list(map(getter, self.debug_data)), dtype=dtype)
        
        
        

class receiver():
    def __init__(self, output_path = "./output/", serial_name = None):
        
        radio_config = {
            "FORMAT": None,
            "SERIAL_SPEED": None,
            "AIR_SPEED": 64,
            "NETID": C.REC_NET_ID,
            "TXPOWER": None,
            "ECC": 1,
            "MAVLINK": 0,
            "OPPRESEND": None,
            "MIN_FREQ": C.REC_FREQ[0],
            "MAX_FREQ": C.REC_FREQ[1],
            "NUM_CHANNELS": 5,
            "DUTY_CYCLE": None,
            "LBT_RSSI": None,
            "MANCHESTER": None,
            "RTSCTS": 0,
            "MAX_WINDOW": None
        }
        
        
        self.radio = radio_serial(name=serial_name, radio_settings=radio_config)  
        self.serial = self.radio.serial 
        self.unpack = self.radio.parser
        
        #Set the output path
        self.output_path = output_path
        if self.output_path[-1] != '/': self.output_path += '/'
                
        self.debug_manager = debug_manager()
        
        #Tracks how many data packets have been detected including corupt one, helps with recovery when the final packet is corrupt
        self.detected_packets = 0
        
        self.packet_count = -1
        
        # Meant for testing resend by faking packet loss, to disable set to true, ik its cxonfusing
        self.resend = True
        self.packets_to_lose = list(range(4, 14))
        self.packets_to_lose.append(165)
        
        
        self.radio.header_structure_config(structure= C.HEADER_STRUCTURE,
                                                      header_id=C.CAN_HEADER_ID)


        self.CTS_structure = (("CTS", 'uint8'))
        self.radio.payload_structure_config({'id': C.DEBUG_PACKET_ID, 'structure':C.DEBUG_PACKET_STRUCTURE},\
                                            {'id': C.DATA_PACKET_ID, 'structure': C.DATA_PACKET_STRUCTURE})

        self.first_packet = True
        
        self.header_length = self.unpack.get_length(C.HEADER_STRUCTURE, key=lambda x: x[1])
        
        #The resend format depends on the format of the packet_i or packet_count (uint8, uint16 etc)
        self.resend_format = C.DATA_PACKET_STRUCTURE[0][1]
        self.max_resend_count = (C.MAX_PACKET_SIZE-self.header_length - C.CHECKSUM_SIZE) // self.unpack.item_length[self.resend_format]
        
        # Hold the index of the last packet that needs to be received,
        # This updates with the resend of corrupt packets
        self.last_packet = None
        
        #A list that holds all the payloads in order
        self.payloads = []
        
        # A range from zero to the number of packets, if a packet is received, that index gets popped
        self.received_packet_tracker = []
        
        self.resend_timeout = 1.5 #seconds
        
        kwargs = {
            'packet_function': self.packet_handler,
            'corrupt_packet_function': self.corrupt_packet_handler,
            'timeout': 0,
            'timeout_function': self.request_resend
        }

        # Create and start the thread
        self.receiver_thread = threading.Thread(target=self.radio.read_packets, kwargs=kwargs)
        self.receiver_thread.daemon = True  # Set as daemon so it closes when the app closes
        self.receiver_thread.start()

        
    
    def start(self):
        pass
        
        
        
    def request_resend(self):
        
        self.resend = True
        payload = bytearray()
        
        length = self.header_length + C.CHECKSUM_SIZE
        
        count = min(len(self.received_packet_tracker), self.max_resend_count)
        
        resned_list = list(self.received_packet_tracker)[:count]
        
        # Pack the indexes of the packets that need resending
        for x in resned_list:
            
            packed_i, l = self.unpack.pack(self.resend_format, x)
            payload+=packed_i
            length += l
        
            self.last_packet = x

        print(f'Asking for retransmission of {resned_list}, packet length: {length}')
            
            
        header = \
               {"header_id" : C.GROUND_HEADER_ID,
                'id': C.RESEND_PACKET_ID, 
                'length': length}
               
        packed_header, _ = self.pack_sturct(header, C.HEADER_STRUCTURE)
        
        self.resend_packet = packed_header + payload
        self.resend_packet += calculate_checksum(self.resend_packet) 
        
        self.radio.transmit_packet(self.resend_packet)
               
    
    def pack_sturct(self, values:dict, structure:tuple):
        out = bytearray(0)
        snipet_length = 0
        
        # Loop throught the structure, and unpack the values stored into one bytearray
        for key, format, *args in structure:
            #logging.debug(f'unpacking item {values[key]} into format {format}')
            
            logging.debug(f'{values[key]}, {key}, {format}')
            
            #Ignore if items is already in byte form
            if type(values[key]) == bytes and format != 'payload': 
                #logging.debug(f'item already in byte form: {values[key]}')
                out += bytearray(values[key])
                snipet_length += self.unpack.item_length[format]
                continue
            
            
            b, l = self.unpack.pack(format, values[key])
            #logging.debug(f'Unpacked item {values[key]} into {b}')
            out += bytearray(b)
            snipet_length += l
        return (out, snipet_length)
    
        
    
    def corrupt_packet_handler(self, packet:dict):
        if packet['header']['id'] == C.DATA_PACKET_ID:
            self.detected_packets += 1
            
            # If its the last packet or we have received (including corupted) enough packets
            if self.last_packet == packet['payload']['packet_i'] or self.detected_packets == self.packet_count:
                logging.warning(f'packets {self.received_packet_tracker} corrupt or not received (INCLUDING LAST), requesting resend')
                self.request_resend()
            
        
        
    def packet_handler(self, packet:dict):
        
        match packet['header']['id']:
            case C.DATA_PACKET_ID:
                
                packet_i = packet['payload']['packet_i']
                
                
                
                #Simulate packet loss
                if packet_i in self.packets_to_lose and self.resend == False:
                    self.corrupt_packet_handler(packet)
                    return
                
                self.detected_packets += 1
                
                if self.first_packet:
                    #Configure the timeout once the first data packet has been received
                    self.radio.timeout = self.resend_timeout
                    
                    self.first_packet = False
                    self.packet_count = packet['payload']['packet_count']
                    
                    self.last_packet = self.packet_count-1
                    
                    # Initiate lists
                    self.payloads = [0]*self.packet_count
                    self.received_packet_tracker = set(range(self.packet_count))
                    
                self.received_packet_tracker.discard(packet_i)
                self.payloads[packet_i] = packet['payload']['payload']
                
                
                if packet_i == self.last_packet:

                    
                    #If some packets got corrupted
                    if len(self.received_packet_tracker) != 0:
                        logging.warning(f'packets {self.received_packet_tracker} corrupt or not received, requesting resend')
                        self.request_resend()
                    #All packets succesfuly received
                    else:

                        self.radio.timeout = 0
                        out = bytearray()
                        for payload in self.payloads:
                            out += payload
                        with open(self.output_path+'out', 'wb') as f:
                            f.write(out)
                        
                        logging.debug("exiting")
                        self.radio.stop_reading_packets()
                        exit()
                
                
            case C.DEBUG_PACKET_ID:
                self.debug_manager.store_debug_packet(packet['payload'])
                
                print("Debug packet:", packet)
        

        

 
class transmitter():
    def __init__(self, data_dir, serial_name):
        
        radio_config = {
            "FORMAT": None,
            "SERIAL_SPEED": None,
            "AIR_SPEED": 64,
            "NETID": C.TRANS_NET_ID,
            "TXPOWER": None,
            "ECC": 1,
            "MAVLINK": 0,
            "OPPRESEND": None,
            "MIN_FREQ": C.TRANS_FREQ[0],
            "MAX_FREQ": C.TRANS_FREQ[1],
            "NUM_CHANNELS": 5,
            "DUTY_CYCLE": None,
            "LBT_RSSI": None,
            "MANCHESTER": None,
            "RTSCTS": 0,
            "MAX_WINDOW": None
        }
        
        #Setup radio
        self.radio = radio_serial(name=serial_name, radio_settings= radio_config)  
        self.serial = self.radio.serial 
        self.unpack = self.radio.parser
        
        self.debug_manager = debug_manager()
        
        # Transmission variables
        self.data_rate = 64 #kb/s
        self.max_packet_length = C.MAX_PACKET_SIZE
        self.debug_time_window = 0.1
        
        
        
        # Configure radio for receiving
        self.radio.header_structure_config(structure= C.HEADER_STRUCTURE,
                                                      header_id=C.CAN_HEADER_ID)
        
        
        self.CTS_structure = (("CTS", 'uint8'))
        self.radio.payload_structure_config({'id': C.DEBUG_PACKET_ID, 'structure':C.DEBUG_PACKET_STRUCTURE},
                                            {'id': C.CTS_PACKET_ID, 'structure': C.DEBUG_PACKET_STRUCTURE},
                                            {'id': C.RESEND_PACKET_ID, 'structure': C.RESEND_PACKET_STRUCTURE})
        
        sleep(1)
        
        self.dir = data_dir
        self.payloads = []
        
        self.queue = Queue()
        self.build_transmission_queue()
        
        
        
        
        self.transmission_thread = threading.Thread(target=self.transmit_data)
        self.receiver_thread = threading.Thread(target=self.radio.read_packets, args=[self.packet_handler])
        self.receiver_thread.start()
        #if self.DEBUG_MODE:
        #    print('started')
        #    sleep(1)
        #    t1 = time()
        #    self.transmission_thread.start()
        #    print('started')
        #    self.transmission_thread.join()
        #    print('stoped sending', time()-t1-5)
        #    
        #    self.radio.stop_reading_packets()
        #    print('sent signal to stop reading')
        
        self.debug_frequency = 1
        
    def start(self):
        
        self.transmission_thread.start()
        
        
    def packet_handler(self, packet:dict):
        
        match packet['header']['id']:
            case C.DEBUG_PACKET_ID:
                self.debug_manager.store_debug_packet(packet['payload'])
                
                print("Debug packet:", packet)
            case C.CTS_PACKET_ID:
                self.transmission_thread.start()
                
            case C.RESEND_PACKET_ID:
                
                format = C.DATA_PACKET_STRUCTURE[0][1] 
                
                packet_count = len(packet['payload']['payload'])// self.unpack.item_length[format]  
                start = 0
                
                print(format, packet_count)
                # Loop through the payload and unpack the packet indexes which need to be retransmitted
                for _ in range(packet_count):
                    packet_i, l = self.unpack.unpack(format, packet['payload']['payload'], start)
                    start += l
                    
                    self.queue.put(packet_i)
                print(self.queue)
                    
                       
        
    def pack_sturct(self, values:dict, structure:tuple):
        out = bytearray(0)
        snipet_length = 0
        
        # Loop throught the structure, and unpack the values stored into one bytearray
        for key, format, *args in structure:
            #logging.debug(f'unpacking item {values[key]} into format {format}')
            
            logging.debug(f'{values[key]}, {key}, {format}')
            
            #Ignore if items is already in byte form
            if type(values[key]) == bytes and format != 'payload': 
                #logging.debug(f'item already in byte form: {values[key]}')
                out += bytearray(values[key])
                snipet_length += self.unpack.item_length[format]
                continue
            
            
            b, l = self.unpack.pack(format, values[key])
            #logging.debug(f'Unpacked item {values[key]} into {b}')
            out += bytearray(b)
            snipet_length += l
        return (out, snipet_length)
            
    def transmit_data(self):
        
        header = \
               {"header_id" : C.GROUND_HEADER_ID,
                'id': C.DATA_PACKET_ID, 
                'length': 0}
               
        
        while not self.queue.empty():

            
            packed_payload = self.payloads[self.queue.get()]
            
            
            
            #Set the header variables and pack it
            header['length'] = len(packed_payload) + self.header_length + C.CHECKSUM_SIZE
            packed_header, _ = self.pack_sturct(header, C.HEADER_STRUCTURE)
            
            packet_wo_footer = packed_header+packed_payload 
            
            packet = packet_wo_footer + calculate_checksum(packet_wo_footer)
                   
            print(packet)
            self.radio.transmit_packet(packet)
            
            
            #sleep(0.1)
                            
            # If queue is empty wait a little to see if new data comes in 
            if self.queue.empty():
                wait = time() + 30
                print(wait >= time(), wait, time())
                while wait >= time() and self.queue.empty():
                    #print(wait >= time(), wait, time())
                    sleep(0.05)
        
        self.radio.stop_reading_packets()
            
    def build_transmission_queue(self):
        
        payload = \
               {'packet_count': 0,
                'packet_i': 0,
                'payload': b'\x00'}
               
        
        with open(self.dir,'rb') as f:
            raw = f.read()
            #print(raw)
            file_length = len(raw)
            
            #Some calsulations for the lengths of the packet
            self.header_length = self.unpack.get_length(C.HEADER_STRUCTURE, key=lambda x: x[1])

            non_data_payload_length = self.unpack.get_length(C.DATA_PACKET_STRUCTURE, key=lambda x: x[1])
            
            max_payload_length = self.max_packet_length - self.header_length - non_data_payload_length - C.CHECKSUM_SIZE
            
            payload['packet_count'] = ceil(file_length/max_payload_length)
            
            #Build packets and add them to a list
            for x in range(0, payload['packet_count']):
                #Set the start and end indexes of slices from the raw data
                start_i = x*max_payload_length
                end_i = ((x+1)*max_payload_length) if (x != payload['packet_count']-1) else (len(raw))
                
                
                #Set the payload variables and pack it
                payload['payload'] = raw[start_i:end_i]
                payload['packet_i'] = x
                packed_payload, _ = self.pack_sturct(payload, C.DATA_PACKET_STRUCTURE)
                
                #Add payload to list
                self.payloads.append(packed_payload)
                
                #print(self.payloads)
                
                #Add the current packet index to the queue
                self.queue.put(x)
            
                
                
                
                
                
                

        #exit()
                
        
if __name__ == '__main__':
    body = transmitter('./test')
    
    