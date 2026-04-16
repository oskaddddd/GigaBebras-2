#import dataAPI
import struct

from serial import Serial
from serial.tools import list_ports as list_ports

from time import sleep, time

import queue
import threading

import logging
from Constants import Constants as C

from Checksum import calculate_checksum


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
        return (b[start:self.packet_length-C.CHECKSUM_SIZE], self.packet_length-start-C.CHECKSUM_SIZE) # Return the rest of the packet
    
    def get_length(self, length_keys:tuple, key = lambda x: x):
        return sum(map(lambda x: self.item_length[key(x)], length_keys))
    
    def string(self):
        return 'unimplemented'
    

        
    


class radio_serial():
    def __init__(self, NET_ID, name:str = None, baud = 57600, set_parameters = C.UPDATE_RADIO_SETTINGS):
        '''This function is responsible for handling the serial communication with the radio, radio settings and eceiving the packets from the radio. It is not respnsible for sending packets.'''
        
        self.radio_config = {
            "FORMAT": None,
            "SERIAL_SPEED": None,
            "AIR_SPEED": 250,
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
        
        self.stop_event = threading.Event()
        
        
        
        
    
        
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
    
    #Triggers the signal to stop reading packets 
    def stop_reading_packets(self):
        self.stop_event.set()
            
    def read_packets(self, packet_function, corrupt_packet_function = None, timeout = None, timeout_function = None, count = None):
       
        
        self.serial.read_all() #Clear buffer
        serial_buffer = queue.Queue()
        
        # Threaded function to read serial stream and add it to a queue
        def read_serial():
            while not self.stop_event.is_set():
                if self.serial.in_waiting:
                    serial_buffer.put(self.serial.read_all())
                        

        def parse_buffer():
            packets_received = 0
            
            header = {}
            payload = {}
            checksum = '\x00'
            
            rx_buffer = bytearray()
            
            SYNC, HEADER, PAYLOAD, CHECKSUM = range(4)
            state = SYNC
            

            t1 = time()
            
            while (not self.stop_event.is_set()):
                t2 = time()
                if serial_buffer.qsize() != 0:
                    t1 = t2
                    rx_buffer.extend(serial_buffer.get())
                    #logging.debug(rx_buffer)
                elif timeout:
                    if (t2 - t1) > timeout:
                        timeout_function()
                        t1 = t2

                
                if state == SYNC:
                    if len(rx_buffer) < 3: 
                        sleep(0.005)
                        continue # Wait for more data to flow in 
                    
                    #Check if the header matches and if the id is valid
                    if rx_buffer[:2] == self.header_id and bytes(rx_buffer[2:3]) in self.packet_structures:
                        logging.debug(f'Started parsing packet')
                        state = HEADER
                    else: 
                        logging.debug(f"Popping some data (SYNC): {rx_buffer[:1]}")
                        rx_buffer.pop(0)
                        
                # Parse the header
                elif state == HEADER:
                    if len(rx_buffer) < self.header_length:
                        sleep(0.005)
                        continue # Wait for more data to flow in 
                    

                    byte_i = 0
                    for key, parser_key in self.header_structure:
                        header[key], l = self.parser.unpack(parser_key, rx_buffer, byte_i)
                        #logging.debug(f'key:{header[key]}, key:{key}, parser:{parser_key}')
                        byte_i += l

                    state = PAYLOAD
                    
                # Parse the payload 
                elif state == PAYLOAD:
                    
                    if len(rx_buffer) < header['length']-C.CHECKSUM_SIZE: 
                        sleep(0.005)
                        continue # Wait for more data to flow in 

                    self.parser.packet_length = header['length']

                    payload_structure = self.packet_structures[header['id']]
                    
                    byte_i = self.header_length
                    #logging.debug(f'buffer:{rx_buffer}, payload struct: {payload_structure}')
                    for key, parser, dimentions, transform in payload_structure:
                    
                        # Create a temporary buffer to store the data for a certain key
                        temp_container = [0]*dimentions
                        
                        # Parse the data and store in temp container
                        for dim_i in range(dimentions):  
                            temp_container[dim_i], l = self.parser.unpack(parser, rx_buffer, byte_i)
                            temp_container[dim_i]*=transform
                            byte_i += l
                            
                        # Store the data in the payload
                        if dimentions == 1: payload[key] = temp_container[0]
                        else: payload[key] = temp_container
                        
                    state = CHECKSUM
                    
                elif state == CHECKSUM:
                    if len(rx_buffer) < header['length']: 
                        sleep(0.005)
                        continue # Wait for more data to flow in 
                    
                    # Read the footer
                    checksum = rx_buffer[header['length']-C.CHECKSUM_SIZE:header['length']]
                    
                    #Validate the checksum
                    
                    calculated_checksum = calculate_checksum(rx_buffer[:(header['length'] - C.CHECKSUM_SIZE)])
                    
                    #logging.debug(f'checksum context: {rx_buffer[:(header["length"] - C.CHECKSUM_SIZE)]}, real checksum:{checksum}, got checksum:{calculated_checksum}, sanity: {checksum == calculated_checksum}')
                    
                    if checksum == calculated_checksum:
                        
                        
                        
                        #Finish parsing the packet
                        
                        packets_received += 1
                        logging.debug({'header': header, 'payload': payload})
                        packet_function({'header': header, 'payload': payload, 'checksum': checksum})
                    
                        if (count and packets_received >= count):
                            self.stop_event.set()
                        
                        else:
                            logging.debug(f'Finished parsing packet')
                            del rx_buffer[:header['length']]
                            payload = {}
                            header = {}
                            state = SYNC
                    
                    # Packen invalid -- Reset the parser and pop the first byte of the buffer      
                    else:
                        
                        if corrupt_packet_function:
                            corrupt_packet_function({'header': header, 'payload': payload, 'checksum': checksum})
                        payload = {}
                        header = {}
                        state = SYNC
                        
                        logging.debug(f"Popping some data (checksum): {rx_buffer[:1]}")
                        rx_buffer.pop(0)
            
            
            
        
            
            
        
            
        
        reading_thread = threading.Thread(target=read_serial, daemon=True)
        parsing_thread = threading.Thread(target=parse_buffer, daemon=True)
        
        reading_thread.start()
        parsing_thread.start()

            
        self.stop_event.wait()
        reading_thread.join()
        parsing_thread.join()
        
        return
        
        

    def transmit_packet(self, packet):
        #while self.serial.in_waiting: sleep(0.005)
        while self.serial.out_waiting: sleep(0.0001)
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
    
