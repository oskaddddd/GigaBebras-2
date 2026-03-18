from radio_manager import radio_serial
import logging
import threading
from time import time, sleep



NET_ID = 15
HEADER_ID =  b'\xf2\x4f' #65536 max
logging.getLogger().setLevel(logging.DEBUG)

debug_packet_structure = (('angVelocity', 'int16', 3, 1/100),
                          ('acceleration', 'int16', 3, 1/100),
                          ('magneticField', 'int16', 3, 1/100),
                          ('temprature', 'int16', 1, 1/100),
                          ('humidity', 'uint8', 1, 1),
                          ('preasure', 'uint32', 1, 1/1000),
                          ('baterryVoltage', 'uint16', 1, 1/100),
                          ('photoresistor', 'uint32', 1, 1)
                          )

radio_name = None

HEADER_STRUCTURE = (("header_id", 'uint16'),
                    ("id", 'byte'),
                    ('length', 'uint8'))

        

class receiver():
    def __init__(self):
        self.radio = radio_serial(NET_ID, set_parameters=False)  
        self.serial = self.radio.serial 
        self.unpack = self.radio.parser
                
        self.debug_time_window = 0.1
        
        
        self.radio.header_structure_config(structure= HEADER_STRUCTURE,
                                                      header_id=HEADER_ID)
        self.payload_structure =\
               (('packet_count', 'uint8', 1, 1),
                ('packet_i', 'uint8', 1, 1),
                ('payload', 'payload', 1, 1))
        
        self.CTS_structure = (("CTS", 'uint8'))
        self.radio.payload_structure_config({'id': b'\x01', 'structure':debug_packet_structure},\
                                            {'id': b'\x12', 'structure': self.CTS_structure},
                                            {'id': b'\x24', 'structure': self.payload_structure})
        
        self.radio.read_packets(packet_function=print)
        
        
        
     
    def send_ack():
        pass             
                
        


class transmitter():
    def __init__(self, data_dir):
        
        #Setup radio
        self.radio = radio_serial(NET_ID)  
        self.serial = self.radio.serial 
        self.unpack = self.radio.parser
        
        # Transmission variables
        self.data_rate = 64
        self.max_packet_length = 64
        self.debug_time_window = 0.1
        
        
        
        # Configure radio for receiving
        self.radio.header_structure_config(structure= HEADER_STRUCTURE,
                                                      header_id=HEADER_ID)
        
        
        self.CTS_structure = (("CTS", 'uint8'))
        self.radio.payload_structure_config({'id': b'\x01', 'structure':debug_packet_structure},\
                                            {'id': b'\x12', 'structure': self.CTS_structure})
        
        
        # Transmitting structures
        self.payload_structure =\
               (('packet_count', 'uint8'),
                ('packet_i', 'uint8'),
                ('payload', 'payload'))
        self.payload = \
               {'packet_count': 0,
                'packet_i': 0,
                'payload': b'\x00'}
               
        
        
        self.packet_ids =\
               {'NON_CTS': b'\x24',
                'CTS': b'\xf3'}
        self.header = \
               {"header_id" : HEADER_ID,
                'id': self.packet_ids['NON_CTS'], 
                'length': 0}
        
        
        self.dir = data_dir
        
        self.queue = []
        self.build_queue()
        self.transmit_data()
        
        transmission_thread = threading.Thread(target=self.transmit_data)
        
        self.debug_frequency = 1
        
    def pack_sturct(self, values:dict, structure:tuple):
        out = bytearray(0)
        snipet_length = 0
        
        # Loop throught the structure, and unpack the values stored into one bytearray
        for key, format in structure:
            #logging.debug(f'unpacking item {values[key]} into format {format}')
            
            #Ignore if items is already in byte form
            if type(values[key]) == bytes and format != 'payload': 
                logging.debug(f'item already in byte form: {values[key]}')
                out += bytearray(values[key])
                snipet_length += self.unpack.item_length[format]
                continue
            
            
            b, l = self.unpack.pack(format, values[key])
            #logging.debug(f'Unpacked item {values[key]} into {b}')
            out += bytearray(b)
            snipet_length += l
        return (out, snipet_length)
            
            
    
    def transmit_data(self):
        
        self.payload['packet_count'] = len(self.queue)
        t1 = time()
        wait_for_debug = False
        
        while self.queue:
            self.payload['packet_i'] += 1
            self.payload['payload'] = self.queue[0]
            
            #logging.debug(self.payload)
        
            packed_payload, l = self.pack_sturct(self.payload, self.payload_structure)
            logging.debug('Packed payload')
            self.header['length'] = l + self.header_length
            print(self.header)
            
            #t2 = time()
            #if t2 >= t1+self.debug_frequency:
            #    wait_for_debug = True
            #    self.header['id'] = self.packet_ids['CTS']
            #    t2 = t1
            

            packed_header, _ = self.pack_sturct(self.header, HEADER_STRUCTURE)
            logging.debug("Packed header")
            packet = packed_header + packed_payload
            
            print([hex(b) for b in packed_payload])          
            self.radio.transmit_packet(packet)
            self.queue.pop(0)
            #sleep(0.1)
            if wait_for_debug:
                wait_for_debug = False
                self.header['id'] = self.packet_ids['NON_CTS']
                debug_packet = self.radio.read_packets(self.debug_time_window)
            
    
    # Add the bytes to queue 
    def build_queue(self):
        
        with open(self.dir,'rb') as f:
            raw = f.read()
            
            file_length = len(raw)
            
            self.header_length = self.unpack.get_length(HEADER_STRUCTURE, key=lambda x: x[1])
            non_data_payload_length = self.unpack.get_length(self.payload_structure, key=lambda x: x[1])
            max_payload_length = self.max_packet_length - self.header_length - non_data_payload_length
            
            #Add the payload data to the queue
            for x in range(0, file_length//max_payload_length):
                self.queue.append(raw[x*max_payload_length:(x+1)*max_payload_length])

            if file_length%max_payload_length != 0:
                self.queue.append(raw[-(file_length%max_payload_length):])
                
            
    def wait_for_CTS(self):
        while 'CST' not in self.radio.read_packets(count=1):
            logging.debug('Received a non CTS packet')
        return 1
        
if __name__ == '__main__':
    body = transmitter('./test.tar.gz')
    
    