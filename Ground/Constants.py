class Constants:
    NET_ID = 63
    HEADER_ID =  b'\xf2\x4f' #65536 max
    DEBUG_PACKET_ID = b'\xef'
    DATA_PACKET_ID = b'\x24'
    CTS_PACKET_ID = b'\x12'
    
    RESEND_PACKET_ID = b'\x2c'

    UPDATE_RADIO_SETTINGS = False    

    DEBUG_PACKET_STRUCTURE = (('gps', 'uint32', 2, 1),
                              ('height', 'uint16', 1, 1),
                              ('velocity', 'int16', 1, 1),
                              ('temprature', 'int16', 1, 1/100),
                              ('preasure', 'uint32', 1, 1/1000)
                              )

    DATA_PACKET_STRUCTURE = (('packet_count', 'uint16', 1, 1),
                         ('packet_i', 'uint16', 1, 1),
                         ('payload', 'payload', 1, 1))
    
    RESEND_PACKET_STRUCTURE = [('payload', 'payload', 1, 1)]

    radio_name = None

    HEADER_STRUCTURE = (("header_id", 'uint16'),
                        ("id", 'byte'),
                        ('length', 'uint8'))
    
    
    MAX_PACKET_SIZE = 96
    
    CHECKSUM_SIZE = 2
    
    #96 - 15 - 7.369 /// 8 - 7.3136
    #128 - 12 - 7.265
    #64 - 19 - 7.87