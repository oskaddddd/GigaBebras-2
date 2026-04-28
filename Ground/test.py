    
    init<...>
    
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
        
        # Reset packet counters
        self.expected_packet_count = count
        self.detected_packets = 0
        
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
            if self.last_packet == packet['payload']['packet_i'] or self.detected_packets == self.expected_packet_count:
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
                        print('time:', time()-self.start_time)
                        self.radio.stop_reading_packets()
                        exit()
                
                
            case C.DEBUG_PACKET_ID:
                self.debug_manager.store_debug_packet(packet['payload'])
                
                print("Debug packet:", packet)
                
            case C.CONNECT_PACKET_ID:
                
                # Once a Connect packet is received configure all the buffers, 
                # but do not reconfigure them if multiple are received (CanSat did not receive ack)
                if self.first_packet:
                    #Configure the timeout once the first data packet has been received
                    self.radio.timeout = self.resend_timeout
                    
                    self.first_packet = False
                    self.packet_count = packet['payload']['packet_count']
                    
                    self.expected_packet_count = self.packet_count
                    
                    self.last_packet = self.packet_count-1
                    
                    # Initiate lists
                    self.payloads = [0]*self.packet_count
                    self.received_packet_tracker = set(range(self.packet_count))
                
                # Send ack
                self.radio.transmit_packet(self.connect_resp_packet)
                
                self.start_time = time()
                