#include <Arduino.h>
#include "FS.h"
#include <Wire.h>


#include <esp_heap_caps.h>
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>


//Constants
#define HEADER_ID 0xf24f
#define DEBUG_ID 0xef
#define DATA_ID 0x24
#define RESEND_ID 0x5a

uint8_t* storage_buffer = NULL;

#define PACKET_BUFFER_SIZE 96
#define SERIAL_RX_SIZE 512
#define MAX_PACKETS 1000

#define RESEND_TIMEOUT 1500 //millisecods

uint16_t BUFFER_SIZE = MAX_PACKETS*PACKET_BUFFER_SIZE;

#define CHECKSUM_LENGTH 2
//Network Ids that radios will use
uint8_t net_ids[2] = {73, 42};

//Pins
#define radio_rx 5
#define radio_tx 18
#define radio_cts 16
#define radio_rts 17

#define gps_rx 19


//Presure, temprature
#include <BME280I2C.h>
BME280I2C bme;
BME280::TempUnit tempUnit = BME280::TempUnit_Celsius;
BME280::PresUnit presUnit = BME280::PresUnit_Pa;

//Calibrate the 9DOF module
#define calibrate false

//Global states
#define RECEIVE 0
#define TRANSMIT 1

//Packet parsing states
#define SYNC 0
#define READ_HEADER 1
#define READ_PAYLOAD 2
#define READ_CHECKSUM 3

//Bitmap for the packet tracker
typedef struct {
    uint8_t* bitmap;       // Dynamically allocated bitmap
    uint16_t maxPackets;  // Maximum number of packets (N)
    uint16_t bitmapSize;  // Size in bytes: (N + 7) / 8
} PacketTracker;



PacketTracker tracker;
uint8_t bitmapBuffer[(MAX_PACKETS + 7) / 8];  // 125 bytes

#pragma pack(push, 1) 
//struct for the packet header
struct packet_header {
  uint16_t header_id = HEADER_ID; 
  uint8_t id {};         
  uint8_t length {};
};
//struct for the data payload
struct data_payload {
    uint16_t packet_count {};
    uint16_t packet_i {};
    //Payload is ignored as the packet is not fully parsed,
    //instead it is stored unparsed in a file and later retransmited
};
struct debug_payload {
  int16_t angVelocity[3] {0, 0, 0};       // 6 bytes | 2 bytes * 3 
  int16_t acceleration[3] {};      // 6 bytes | 2 bytes * 3 
  int16_t magneticField[3] {};     // 6 bytes | 2 bytes * 3 
  uint32_t gps[2] {};              // 8 bytes | 4 bytes * 2
  uint16_t height {};              // 2 bytes | 2 bytes * 1
  int16_t velocity {};             // 2 bytes | 2 bytes * 1
  int16_t temperature = 2000;          // 2 bytes | 2 bytes * 1
  uint32_t pressure;          // 1 bytes | 1 bytes * 1
};

//Structs for the packets
struct data_packet_struct {
    packet_header header;
    data_payload payload;
};
struct debug_packet_struct {
    packet_header header;
    debug_payload payload;
};
#pragma pack(pop)

uint8_t header_length = sizeof(packet_header);
uint8_t MAX_RESEND_COUNT = (PACKET_BUFFER_SIZE - header_length)/2;


struct resend_packet_struct {
    packet_header header;
    uint16_t* buffer = NULL;
};

resend_packet_struct resend_packet;

debug_packet_struct debug_packet;

data_packet_struct data_packet;

uint8_t can_state = RECEIVE;
uint8_t packet_state = SYNC;






bool is_first_packet = true;

//Define serials
HardwareSerial& radio = Serial2;
HardwareSerial& gps   = Serial1;

uint8_t debug_delay = 2; //s

uint8_t length_byte_offset = 3;

uint16_t last_packet_i;

uint16_t packet_count;


// Class vibe coded, dont know what happening inside
class CircularBuffer {
private:
    uint8_t buffer[PACKET_BUFFER_SIZE];  // Size as needed
    int head = 0;
    int tail = 0;
    static const int capacity = PACKET_BUFFER_SIZE;

    int index(int i) const { return (tail + i) % capacity; }

public:
    // Push multiple bytes
    int push(const uint8_t* data, int count) {
        int freeSpace = (tail - head - 1 + capacity) % capacity;
        int bytesToWrite = min(count, freeSpace);
        int written = 0;

        for (int i = 0; i < bytesToWrite; i++) {
            buffer[head] = data[i];
            head = (head + 1) % capacity;
            written++;
        }

        return written;
    }

    // Pop a single byte
    bool pop(uint8_t* byte) {
        if (head == tail) return false;  // empty
        *byte = buffer[tail];
        tail = (tail + 1) % capacity;
        return true;
    }

    uint8_t operator[](int i) const {
        if (i < 0 || i >= available()) return 0; // Invalid index
        return buffer[index(i)];
    }

    int available() const {
        return (head - tail + capacity) % capacity;
    }

    int free() {
        return (tail - head - 1 + capacity) % capacity;
    }

    int read(uint8_t* dest, uint8_t length) {
        // 1. Calculate first segment size (from tail to end of buffer)
        int firstChunk = (length < (capacity - tail)) ? length : (capacity - tail);

        // Copy first segment
        memcpy(dest, &buffer[tail], firstChunk);

        // 2. Copy second segment (if data wraps around to beginning)
        if (length > firstChunk) {
            memcpy(dest + firstChunk, &buffer[0], length - firstChunk);
        }

        // Advance tail (remove data from circular buffer)
        tail = (tail + length) % capacity;

        return length;
    }
};

CircularBuffer receive_buffer;
uint8_t transmit_buffer[PACKET_BUFFER_SIZE];

void setup() {
    // Allocate the storage buffer
    storage_buffer = (uint8_t*) malloc(BUFFER_SIZE);

    resend_packet.buffer = (uint16_t*) malloc(MAX_RESEND_COUNT);

    if (storage_buffer == NULL) {
      Serial.println("Failed to allocate buffer!");
      Serial.print("Free memory: ");
      Serial.println(heap_caps_get_free_size(MALLOC_CAP_8BIT));
      return;
    }
    if (!PacketTracker_Init(&tracker, MAX_PACKETS)) {
        Serial.println("BITMAP INIT FAILED!");
        return;
    }

    Serial.begin(115200);
    Wire.begin();
    delay(500);


    bme.begin();
    
    // Configure Serial coms
    radio.setRxBufferSize(SERIAL_RX_SIZE);
    radio.setPins(radio_rx, radio_tx, radio_cts, radio_rts);
    radio.begin(57600, SERIAL_8N1);
    radio.setHwFlowCtrlMode(UART_HW_FLOWCTRL_CTS_RTS);


    gps.begin(115200, SERIAL_8N1, gps_rx, -1);

    setNetID(net_ids[0]);
}

bool PacketTracker_Init(PacketTracker* tracker, uint16_t n) {
    if (!tracker || n == 0) return false;

    tracker->maxPackets = n;
    tracker->bitmapSize = (n + 7) / 8;

    tracker->bitmap = (uint8_t*)malloc(tracker->bitmapSize);

    if (!tracker->bitmap) return false;

    memset(tracker->bitmap, 0, tracker->bitmapSize);
    return true;
}

/**
 * Mark packet as received
 */
void PacketTracker_SetReceived(PacketTracker* tracker, uint16_t packetId) {
    if (!tracker || !tracker->bitmap) return;

    uint16_t byteIndex = packetId / 8;
    uint8_t bitIndex = packetId % 8;

    tracker->bitmap[byteIndex] |= (1 << bitIndex);
}

/**
 * Get list of unreceived packets.
 * If outIds is NULL, returns only the count.
 */
uint16_t PacketTracker_GetUnreceived(PacketTracker* tracker, uint16_t* outIds, uint16_t maxOutIds) {
    if (!tracker || !tracker->bitmap) return 0;

    uint16_t count = 0;

    for (uint16_t i = 0; i < tracker->maxPackets; i++) {
        uint16_t byteIndex = i / 8;
        uint8_t bitIndex = i % 8;

        // Check if bit is 0 (unreceived)
        if (!(tracker->bitmap[byteIndex] & (1 << bitIndex))) {
            if (outIds && count < maxOutIds) {
                outIds[count] = i;
            }
            count++;
        }
    }

    return count;
}


uint16_t calculate_checksum(const uint8_t* data, size_t length) {
    uint8_t sum1 = 0;
    uint8_t sum2 = 0;
    for (size_t i = 0; i < length; ++i) {
        sum1 = (sum1 + data[i]) % 255;
        sum2 = (sum2 + sum1) % 255;
    }
    return (static_cast<uint16_t>(sum2) << 8) | sum1;
}



bool request_resend(){
    uint8_t count = PacketTracker_GetUnreceived(&tracker, resend_packet.buffer, MAX_RESEND_COUNT);
    // All packets received
    if (count == 0){
        return false;
    }

    resend_packet.header.length = header_length + 2*count + 2;


    memcpy(transmit_buffer, &resend_packet.header, header_length);
    memcpy(transmit_buffer + header_length, resend_packet.buffer, count * sizeof(uint16_t));

    //Calculate and copy the checksum
    uint16_t checksum = calculate_checksum(transmit_buffer, resend_packet.header.length - 2);
    memcpy(transmit_buffer+resend_packet.header.length-2, &checksum, sizeof(uint16_t));

    radio.write(transmit_buffer, resend_packet.header.length);

}


uint8_t temp[PACKET_BUFFER_SIZE];


void read_packets() {
    uint8_t i = 0;
    unsigned long t1 = millis();

    while (true) {

        // Read bytes into the packet buffer
        uint16_t bytes_available = radio.available();
        if (bytes_available && receive_buffer.free()) {
            uint8_t N = min((int)bytes_available, receive_buffer.free());
            

            size_t bytes_read = radio.readBytes(temp, N);
            if (bytes_read > 0) {
                receive_buffer.push(temp, bytes_read);  // Push all read bytes
            }
            t1 = millis();
        }
        //In case last packet was corupted and the resend did not trigger a timeout is in place
        else{
            if ((millis() - t1) >= RESEND_TIMEOUT){
                request_resend();
            }
        }


        // State mashine to read packets
        switch (packet_state) {

            case SYNC: {
                // Wait for enough data
                if (receive_buffer.available() < 2) {continue;}


                uint16_t possibleHeader = (receive_buffer[0] << 8) | receive_buffer[1];
                i = 2;

                if (possibleHeader == HEADER_ID) {
                    data_packet.header.header_id = possibleHeader;

                    packet_state = READ_HEADER;
                }
                // Need to pop data
                break;

            }
            case READ_HEADER: {
                // Wait for enough data
                if (receive_buffer.available() < header_length) {continue;}

                data_packet.header.id = receive_buffer[i++];
                data_packet.header.length = receive_buffer[i++];

                // sanity check
                if (data_packet.header.length > PACKET_BUFFER_SIZE) {

                    packet_state = SYNC;
                    break;
                }

                packet_state = READ_PAYLOAD;
                break;
            }

            case READ_PAYLOAD: {

                // Wait for enough data (excluding checksum)
                if (receive_buffer.available() < data_packet.header.length-CHECKSUM_LENGTH) {continue;}

                switch (data_packet.header.id){
                    case DATA_ID:
                        // Parse payload
                        data_packet.payload.packet_count = receive_buffer[i++];
                        data_packet.payload.packet_i = receive_buffer[i++];

                        //TO FIX
                        if (last_packet_i == data_packet.payload.packet_i){
                            can_state = TRANSMIT;
                            setNetID(net_ids[1]);
                        }
                        break;
                    
                    case RESEND_ID:
                        break;
                        // Read the resend contents

                }
                
                packet_state = READ_CHECKSUM;
                break;
            
            }

            case READ_CHECKSUM: {
                // Wait for enough data
                if (receive_buffer.available() < data_packet.header.length) {continue;}

                receive_buffer.read(transmit_buffer, data_packet.header.length);

                uint16_t stored_checksum = (transmit_buffer[data_packet.header.length - 2] << 8) | transmit_buffer[data_packet.header.length - 1];
                if (stored_checksum == calculate_checksum(transmit_buffer, data_packet.header.length-2)){
                    
                    //Init the tracker system which i totally understand... some bitmaps and shii
                    if (is_first_packet){
                        is_first_packet = false;
                        
                        //Set the finishing packet to be the last index
                        last_packet_i = data_packet.payload.packet_count-1;
                        packet_count = data_packet.payload.packet_count;

                        if (!PacketTracker_Init(&tracker, data_packet.payload.packet_count)) {
                            Serial.println('Failed to alocate tracker buffer');
                            return; // Allocation failed
                        }
                    }
                    // Mark packet as received
                    PacketTracker_SetReceived(&tracker, data_packet.payload.packet_i);
                    
                    //Store packet
                    receive_buffer.read(
                        &storage_buffer[PACKET_BUFFER_SIZE*data_packet.payload.packet_i],
                        data_packet.header.length
                    );
                }
                packet_state = SYNC;
                i = 0;

                if (data_packet.payload.packet_i == last_packet_i){

                    //if no more packets need to be resent - start transmitting
                    if (!request_resend()){
                        can_state = TRANSMIT;
                        return;
                    }
                }
            }    

        }
    }
}

// Change this to your desired NETID


String sendCommand(const String& message) {
    String msg = message;

    if (message == "+++") {
        radio.print(msg);
        delay(1000);
    } else {
        msg += "\r\n";
        radio.print(msg);
    }

    // Wait for response to stabilize
    size_t lastSize = radio.available();
    delay(100);

    while (true) {
        size_t currentSize = radio.available();
        if (currentSize == lastSize) break;
        lastSize = currentSize;
        delay(50);
    }

    // Read response
    String response = "";
    while (radio.available()) {
        response += (char)radio.read();
    }

    return response;
}

void setNetID(uint8_t netid) {
    delay(1000);

    // Enter AT mode
    sendCommand("+++");

    // Build command string
    String cmd = "ATS3=" + String(netid);

    Serial.println("Setting NETID...");
    Serial.println(sendCommand(cmd));

    // Save settings
    Serial.println("Saving...");
    Serial.println(sendCommand("AT&W"));

    // Reboot radio
    Serial.println("Rebooting...");
    Serial.println(sendCommand("ATZ"));
}

void read_sensors(){

  float temp, hum, pres;
  bme.read(pres, temp, hum, tempUnit, presUnit);

  debug_packet.payload.temperature = temp*100;
  debug_packet.payload.pressure = temp*100;

}


void debug()
{

}


void transmit_packets()
{
    unsigned long t0 = millis();
    for (int i = 0; i < packet_count; i++){

        if (millis() - t0 > debug_delay){
            debug();
            t0 = millis();
        }

        //Get packet length
        uint8_t packet_length = storage_buffer[i*PACKET_BUFFER_SIZE+2];

        //Copy to transmit buffer
        memcpy(transmit_buffer, storage_buffer+(i*PACKET_BUFFER_SIZE), packet_length);

        //Transmit packet
        radio.write(transmit_buffer, packet_length);
    }
//    for (size_t i = 0; i < count; i++) {
//        // 1. Calculate pointer to the start of the current uint16_t
//        uint8_t* ptr = storage_buffer + (i * 2);
//
//        // 2. Cast the pointer to uint16_t* and read the value
//        uint16_t value = *((uint16_t*)ptr);
//
//    }



}


void loop() {

  switch (can_state){
    case RECEIVE:
      read_packets();
      break;
    case TRANSMIT:
      transmit_packets();

  }
}