#import dataAPI
import struct
from sortedcontainers import SortedList
from serial import Serial
from serial.tools import list_ports as list_ports
import json
from time import sleep, time

from collections import deque

import logging


#AT info { https://ardupilot.org/copter/docs/common-3dr-radio-advanced-configuration-and-technical-information.html }

class Parser():
    def __init__(self):
        self.match_function = {'bit':self.bit,
                               'payload':self.payload,
                               'string':self.string,
                               'byte': self.byte}
        self.item_length = {'uint8':1,
                            'uint16':2,
                            'uint32':4,
                            'int8':1,
                            'int16':2,
                            'int32':4,
                            'float':4,
                            'double':8,
                            'long':4,
                            'byte':1,
                            'payload': 0}
        
        self.match_format = {'uint8':'B',
                            'uint16':'H',
                            'uint32':'I',
                            'int8':'b',
                            'int16':'h',
                            'int32':'i',
                            'float':'f',
                            'double':'d',
                            'long':'l'}
        
        self.packet_length = -1
        
    def unpack(self, format, b:bytes, start:int):
        if format in self.match_format:
            return (struct.unpack_from(self.match_format[format], b, start)[0], self.item_length[format])
        elif format in self.match_function:
            return self.match_function[format](b, start)
        
    def pack(self, format, item):
        if format in self.match_format:
            return (struct.pack(self.match_format[format], item), self.item_length[format])
        elif format == 'payload':
            return (item, len(item))
        
    def byte(self, b: bytes, start:int):
        return (bytes(b[start:start+1]), 1)
                
    def bit(self, b: bytes, start: int, bit: int):
        return((b[start]>>bit) & 1)
    
    def payload(self, b: bytes, start: int):
        return (b[start:self.packet_length-start], len(b[start:self.packet_length-start]))
    
    def get_length(self, length_keys:tuple, key = lambda x: x):
        return sum(map(lambda x: self.item_length[key(x)], length_keys))
    
    def string(self):
        return 'unimplemented'
    

        
    


class radio_serial():
    def __init__(self, NET_ID, name:str = None, baud = 57600, max_packet_size = 70, set_parameters = False):
        '''This function is responsible for handling the serial communication with the radio, radio settings and eceiving the packets from the radio. It is not respnsible for sending packets.'''
        
        self.radio_config = {
            "FORMAT": None,
            "SERIAL_SPEED": None,
            "AIR_SPEED": 64,
            "NETID": NET_ID,
            "TXPOWER": None,
            "ECC": 1,
            "MAVLINK": 0,
            "OPPRESEND": None,
            "MIN_FREQ": None,
            "MAX_FREQ": None,
            "NUM_CHANNELS": None,
            "DUTY_CYCLE": None,
            "LBT_RSSI": None,
            "MANCHESTER": None,
            "RTSCTS": 1,
            "MAX_WINDOW": None
        }
        
        self.serial_setup(name, baud)
        if set_parameters: self.config_radio()

        self.parser = Parser()
        
        self.packetCount = 0
        self.max_packet_size = max_packet_size
        self.packetBuffer = bytearray()
  
        self.last_transmit = 0
    
        
    # Establish serial communication with the radio
    def serial_setup(self, name, baud) -> Serial:
        if not name:
            #Find available ports and promt user to choose
            ports = list_ports.comports()
            print("\nCHOOSE POPRT\n------------")
            for i, port in enumerate(ports):
                if port.description!="n/a":
                    print(f"({port.description})")
                    print(f"[{i}] {port.name} {port.description}")
            name = ports[int(input('\nENTER SELECTION:'))].name
            self.serial = Serial(f"/dev/{name}", baud, rtscts=True)
        else:
            names = list(map(lambda x: x.name, list_ports.comports()))
            i = 1
            while name not in names:
                logging.warning(f'Serial [{name}] unavailable. Attempt #{i}, retrying...')
                i+=1
                sleep(1)
                names = list(map(lambda x: x.name, list_ports.comports()))
            self.serial = Serial(f"/dev/{name}", baud)

        logging.debug("Serial initialised!")

    # Configure radio settings
    def config_radio(self):
        def write(message:bytes):
    

            # 1 second sleep interval required by docs, when entering AT setup
            if message == b'+++': 
                self.serial.write(message)
                sleep(1)
            else:
                message+=b'\r\n'
                self.serial.write(message)

            # Wait for and return answer
            #while self.serial.in_waiting <= len(message): sleep(0.01)
            
            l = self.serial.in_waiting
            sleep(0.1)
            while l != self.serial.in_waiting:
                l = self.serial.in_waiting
                sleep(0.05)
            
            return self.serial.read_all()[len(message):]

        #Enter AT setup
        # 1 second sleep interval is required by docs
        sleep(1)
        write(b'+++')

        #Get a list of all user changable EEPROM variables
        EEPROM_variables_string = write(b'ATI5').decode()
        if not EEPROM_variables_string: 
            logging.debug('Failed to get variables')
            return
        logging.debug(f'Got variables string: {EEPROM_variables_string}')

        changed_parameters = False
        # Format EEPROM vaeriable string into a dictionary of variables that need changing
        for variable in EEPROM_variables_string.splitlines():
            #S0: FORMAT=22 (example)
            logging.debug(f'Procesing variable: {variable}')
            command, temp_name_val_combo = variable.split(':')
            key, value = temp_name_val_combo.split('=')
    
            # If a value for a key does not match, save it to the dict
            if key in self.radio_config and self.radio_config[key] and str(self.radio_config[key]) != value:

                logging.debug(f'Chnaging radio parameter {key}: [{value}] to [{self.radio_config[key]}]')
                message = f'AT{command}={self.radio_config[key]}'
                out = write(message.encode())

                logging.debug(out)
                changed_parameters = True

        if changed_parameters:
            logging.debug('Saving changed parameter(s)...')
            out = write(b'AT&W')
            logging.debug(out)
            
            logging.debug('Rebooting radio...')
            out = write(b'ATZ')
            logging.debug(out)
        else: 
            logging.debug('No parameters were changed')
            out = write(b'ATZ')
     
    # Configure the header structure     
    def header_structure_config(self, structure, header_id):
        # Header Structure
        self.header_structure = structure
        
        self.header_length = self.parser.get_length(structure, key=lambda x: x[1])
        self.header_id = header_id
  
    def payload_structure_config(self, *structures):
        self.packet_structures = {}
        
        for structure in structures:
            self.packet_structures[structure['id']] = structure['structure']
            
    def read_packets(self, time_window = None, count = None, packet_function = None):
        packetBuffer = bytearray(self.max_packet_size)
        
        bytes_read = 0
        t1 = time()
        header = {}
        payload = {}
        
        SYNC, HEADER, PAYLOAD = range(3)
        state = SYNC
        
        sync_buffer = deque(maxlen=3)
        
        packets_received = 0
        
        debug_read_bytes = 0
        
        while time_window == None or time() < t1 + time_window:
            
            if self.serial.in_waiting:
                #logging.debug(bytes_read, packetBuffer)
                byte = self.serial.read(1)[0]
                #logging.debug(f'readByte {hex(byte)}, this is the {bytes_read}')
                # Search for the header id
                debug_read_bytes +=1
                if state == SYNC:
                    sync_buffer.append(byte)
                    #logging.debug(f'{bytes(list(sync_buffer))}, {self.header_id}, {self.parser.pack('uint8', sync_buffer[-1] )[0]}, {self.parser.pack('uint8', sync_buffer[-1])[0]  in self.packet_structures}')
                    if bytes(list(sync_buffer)[:-1]) == self.header_id\
                        and self.parser.pack('uint8', sync_buffer[-1])[0] in self.packet_structures:
                        logging.debug(f'Started parsing packet, read {debug_read_bytes} until found valid packet')
                        
                        bytes_read = len(sync_buffer)
                        
                        # Copy the sync buffer to the packet buffer
                        for i in range(bytes_read):
                            packetBuffer[i] = sync_buffer[i]
                        
                        state = HEADER
                
                # Parse the header
                elif state == HEADER:
                    # Read the header
                    packetBuffer[bytes_read] = byte
                    bytes_read += 1
                    
                    if bytes_read == self.header_length:
                        byte_i = 0
                        for key, parser_key in self.header_structure:
                            header[key], l = self.parser.unpack(parser_key, packetBuffer, byte_i)
                            #logging.debug(f'key:{header[key]}, key:{key}, parser:{parser_key}')
                            byte_i += l
                        #logging.debug(f'packetBuffer:{packetBuffer}')
                        state = PAYLOAD
                
                # Parse the payload 
                elif state == PAYLOAD:
                    # Read the payload
                    packetBuffer[bytes_read] = byte
                    bytes_read += 1
                    
                    
                    if bytes_read == header['length']:
                        self.parser.packet_length = header['length']
                        #logging.debug(f'packet_structures: {self.packet_structures}')
                        #logging.debug(f'packet id:{header["id"]}')
                        payload_structure = self.packet_structures[header['id']]
                        byte_i = self.header_length

                        for key, parser, dimentions, transform in payload_structure:
                        
                            # Create a temporary buffer to store the data for a certain key
                            temp_container = [0]*dimentions

                            # Parse the data and store in temp container
                            for dim_i in range(dimentions):  
                                temp_container[dim_i], l = self.parser.unpack(parser, packetBuffer, byte_i)

                                temp_container[dim_i]*=transform
                                byte_i += l

                            # Store the data in the payload
                            if dimentions == 1: payload[key] = temp_container[0]
                            else: payload[key] = temp_container

                        packets_received += 1
                            
                        if packet_function:
                            packet_function({'header': header, 'payload': payload})
                            
                        if time_window or (count and packets_received >= count):
                            return {'header': header, 'payload': payload}
                        else:
                            payload = {}
                            header = {}
                            state = SYNC
                            bytes_read = 0

    def transmit_packet(self, packet):
        #while self.serial.in_waiting: sleep(0.005)
        self.serial.write(packet)
    

if __name__ == "__main__":
    NET_ID = int(input("Enter NetID:"))
    logging.getLogger().setLevel(logging.DEBUG)
    main = radio_serial(NET_ID)
    a = b'\xff'*64
    i = 1
    deltaT = 0
    while True:
        t1 = time()
        main.transmit_packet(a)
        deltaT = (time()-t1)
        print(deltaT)
        i+=1
    main.config_radio()
    
