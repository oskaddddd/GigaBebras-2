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

logging.getLogger().setLevel(logging.DEBUG)

debug_dict = []


with open("data.json", 'r') as f:
    debug_dict = json.load(f)
    if len(debug_dict) != 0:
        if input("There is data in data.json, clear to delete? y/n:") == 'y':
            dictData = []

debug_data = SortedList(debug_dict, key=lambda x: -x['timestamp'])

class receiver():
    def __init__(self):
        self.radio = radio_serial(C.NET_ID)  
        self.serial = self.radio.serial 
        self.unpack = self.radio.parser
                
        self.debug_time_window = 0.1
        
        self.detected_packets = 0
        
        self.packet_count = -1
        
        # Meant for testing reseng by faking packet loss, to disable set to true, ik its cxonfusing
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
        
        self.resend_format = C.DATA_PACKET_STRUCTURE[0][1]
        self.max_resend_count = (C.MAX_PACKET_SIZE-self.header_length - C.CHECKSUM_SIZE) // self.unpack.item_length[self.resend_format]
        
        self.last_packet = None
        
        #A list that holds all the payloads in order
        self.payloads = []
        
        # A range from zero to the number of packets, if a packet is received, that index gets popped
        self.received_packet_tracker = []
        
        
        
        self.radio.read_packets(packet_function=self.packet_handler,
                                corrupt_packet_function= self.corrupt_packet_handler,
                                timeout=1.5,
                                timeout_function=self.request_resend)
        
        
        
        
        
    def request_resend(self):
        
        self.resend = True
        payload = bytearray()
        
        length = self.header_length + C.CHECKSUM_SIZE
        
        count = min(len(self.received_packet_tracker), self.max_resend_count)
        
        
        
        
        # Pack the indexes of the packets that need resending
        for i in range(count):
            x = self.received_packet_tracker.pop()
            packed_i, l = self.unpack.pack(self.resend_format, x)
            payload+=packed_i
            length += l
            
            self.last_packet = x


            
            
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
                        
                        out = bytearray()
                        for payload in self.payloads:
                            out += payload
                        with open('./output/out.jpg', 'wb') as f:
                            f.write(out)
                        
                        logging.debug("exiting")
                        self.radio.stop_reading_packets()
                        exit()
                
                
            case C.DEBUG_PACKET_ID:
                print("Debug packet:", packet)
        
    def parse_data():
        
        pass        
    def parse_debug():    
        pass
        

 
class transmitter():
    def __init__(self, data_dir):
        
        #Setup radio
        self.radio = radio_serial(C.NET_ID)  
        self.serial = self.radio.serial 
        self.unpack = self.radio.parser
        
        # Transmission variables
        self.data_rate = 64 #kb/s
        self.max_packet_length = C.MAX_PACKET_SIZE
        self.debug_time_window = 0.1
        
        self.DEBUG_MODE = True
        
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
        
        if self.DEBUG_MODE:
            print('started')
            sleep(1)
            t1 = time()
            self.transmission_thread.start()
            print('started')
            self.transmission_thread.join()
            print('stoped sending', time()-t1-5)
            
            self.radio.stop_reading_packets()
            print('sent signal to stop reading')
        
        self.debug_frequency = 1
        
    def packet_handler(self, packet:dict):
        
        match packet['header']['id']:
            case C.DEBUG_PACKET_ID:
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
            
            
            sleep(0.5)
                            
            # If queue is empty wait a little to see if new data comes in 
            if self.queue.empty():
                wait = time() + 5
                print(wait >= time(), wait, time())
                while wait >= time() and self.queue.empty():
                    #print(wait >= time(), wait, time())
                    sleep(0.05)
            
    def build_transmission_queue(self):
        
        payload = \
               {'packet_count': 0,
                'packet_i': 0,
                'payload': b'\x00'}
               
        
        with open(self.dir,'rb') as f:
            raw = f.read()
            print(raw)
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
    
    