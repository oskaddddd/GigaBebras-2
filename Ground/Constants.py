class Constants:
    NET_ID = 15
    HEADER_ID =  b'\xf2\x4f' #65536 max
    DEBUG_PACKET_ID = b'\xef'
    DATA_PACKET_ID = b'\x24'
    CTS_PACKET_ID = b'\x12'



    DEBUG_PACKET_STRUCTURE = (('angVelocity', 'int16', 3, 1/100),
                              ('acceleration', 'int16', 3, 1/100),
                              ('magneticField', 'int16', 3, 1/100),
                              ('gps', 'uint32', 2, 1),
                              ('height', 'uint16', 1, 1),
                              ('velocity', 'int16', 1, 1),
                              ('temprature', 'int16', 1, 1/100),
                              ('preasure', 'uint32', 1, 1/1000)
                              )

    DATA_PACKET_STRUCTURE = (('packet_count', 'uint8', 1, 1),
                         ('packet_i', 'uint8', 1, 1),
                         ('payload', 'payload', 1, 1))

    radio_name = None

    HEADER_STRUCTURE = (("header_id", 'uint16'),
                        ("id", 'byte'),
                        ('length', 'uint8'))