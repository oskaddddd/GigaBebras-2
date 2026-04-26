#include <Arduino.h>
#include "FS.h"
#include <Wire.h>


#include <esp_heap_caps.h>
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

//#include <FreeRTOS.h>
//#include <queue.h>
//#include <semphr.h>


//PROTOCOL CONFIG
#define GROUND_HEADER_ID 0xf24f
#define CAN_HEADER_ID 0x350a
#define DEBUG_ID 0xef
#define DATA_ID 0x24
#define RESEND_ID 0x2c

//Network Ids that radios will use

#define TRANS_NET_ID 15
#define REC_NET_ID 63

uint32_t TRANS_FREQ[2] = {433000,  433500};
uint32_t REC_FREQ[2] = {433700,  434200};

#define CHECKSUM_LENGTH 2
uint8_t length_byte_offset = 3;

#define MAX_PACKET_SIZE 96 
#define MAX_PACKETS 1000 


#define SERIAL_RX_SIZE 512 //Serial fifo rx buffer size 
#define RESEND_TIMEOUT 1500 //millisecods

#define DEBUG_DELAY 2000 // miliseconds

//PINS
#define radio_rx 5
#define radio_tx 18

#define gps_rx 19

//STATES
//Global states
#define RECEIVE 0
#define TRANSMIT 1
#define RESEND 2

//Packet parsing states
#define SYNC 0
#define READ_HEADER 1
#define READ_PAYLOAD 2
#define READ_CHECKSUM 3

uint8_t can_state = RECEIVE;
uint8_t packet_state = SYNC;

//PACKET STRUCTs
// Put struct which will be copied in their entirety using memcpy in here
#pragma pack(push, 1) 
//struct for the packet header
struct packet_header {
    uint16_t header_id = htons(CAN_HEADER_ID); 
    uint8_t id {};         
    uint8_t length {};
};

struct debug_payload {
    uint32_t timestamp {};
    uint32_t gps[2] {};              // 8 bytes | 4 bytes * 2
    uint16_t height {};              // 2 bytes | 2 bytes * 1
    int16_t velocity {};             // 2 bytes | 2 bytes * 1
    int16_t temperature = 2000;          // 2 bytes | 2 bytes * 1
    uint32_t pressure;          // 1 bytes | 1 bytes * 1
};

struct debug_packet_struct {
    packet_header header;
    debug_payload payload;
};
#pragma pack(pop)


//struct for the data payload
struct data_payload {
    uint16_t packet_count {};
    uint16_t packet_i {};
    //Payload is ignored as the packet is not fully parsed,
    //instead it is stored unparsed in a file and later retransmited
};
//Structs for the packets
struct data_packet_struct {
    packet_header header;
    data_payload payload;
};
struct resend_packet_struct {
    packet_header header;
    uint16_t* buffer = NULL;
};


resend_packet_struct resend_packet;

debug_packet_struct debug_packet;

data_packet_struct data_packet;


//BUFFERS

//Buffer for storing packets, initialization in setup(), since more memory is available during runtime than compile
uint16_t STORAGE_BUFFER_SIZE = MAX_PACKETS*MAX_PACKET_SIZE;
uint8_t* storage_buffer = NULL;

//Bitmap for the packet tracker
typedef struct {
    uint8_t* bitmap;       // Dynamically allocated bitmap
    uint16_t maxPackets;  // Maximum number of packets (N)
    uint16_t bitmapSize;  // Size in bytes: (N + 7) / 8
} PacketTracker;

PacketTracker tracker;
uint8_t bitmapBuffer[(MAX_PACKETS + 7) / 8];  // 125 bytes

uint8_t header_length = sizeof(packet_header);
uint8_t MAX_RESEND_COUNT = (MAX_PACKET_SIZE - header_length)/2;

QueueHandle_t resend_queue; 
SemaphoreHandle_t radioMutex;

uint8_t transmit_buffer[MAX_PACKET_SIZE];

// Queue to hold packet IDs (uint16_t)
//QueueHandle_t resend_queue; 

// Class vibe coded, dont know what happening inside
class CircularBuffer {
private:
    uint8_t buffer[MAX_PACKET_SIZE*2];  // Size as needed
    int head = 0;
    int tail = 0;
    static const int capacity = MAX_PACKET_SIZE*2;

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
    bool pop() {
        if (head == tail) return false;  // empty
        buffer[tail];
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

        return length;
    }
    void del(uint8_t length){
        // Advance tail (remove data from circular buffer)
        tail = (tail + length) % capacity;
    }
};

CircularBuffer receive_buffer;



//HARDWARE

//Presure, temprature
#include <BME280I2C.h>
BME280I2C bme;
BME280::TempUnit tempUnit = BME280::TempUnit_Celsius;
BME280::PresUnit presUnit = BME280::PresUnit_Pa;

//gps
#include <TinyGPSPlus.h>
TinyGPSPlus gps;


//Define serials
HardwareSerial& radio = Serial2;
HardwareSerial& gps_serial   = Serial1;


//OTHER VARIABLES
bool is_first_packet = true;
uint16_t last_packet_i;
uint16_t packet_count;
uint16_t packets_seen = 0;
uint16_t packets_seen_target = 0;

bool pause_receiver = false;



void setup() {
    Serial.begin(115200);
    
    delay(500);

    // Allocate buffers
    storage_buffer = (uint8_t*) malloc(STORAGE_BUFFER_SIZE);

    resend_packet.buffer = (uint16_t*) malloc(MAX_RESEND_COUNT * sizeof(uint16_t));


    if (storage_buffer == NULL) {
      Serial.println("Failed to allocate buffer!");
      Serial.print("Free memory: ");
      Serial.println(heap_caps_get_free_size(MALLOC_CAP_8BIT));
      return;
    }

    //Alocate the resend queue
    resend_queue = xQueueCreate(MAX_RESEND_COUNT, sizeof(uint16_t));
    radioMutex = xSemaphoreCreateMutex();

    // Initialize packet tracker
    if (!PacketTracker_Init(&tracker, MAX_PACKETS)) {
        Serial.println("BITMAP INIT FAILED!");
        return;
    }

    resend_packet.header.id = RESEND_ID;
    debug_packet.header.id = DEBUG_ID;
    debug_packet.header.length = sizeof(debug_packet)+CHECKSUM_LENGTH;

    Wire.begin();
    delay(500);

    // Configure Serial coms
    radio.setRxBufferSize(SERIAL_RX_SIZE);
    radio.setTxBufferSize(MAX_PACKET_SIZE);
    radio.setPins(radio_rx, radio_tx);


    radio.begin(57600, SERIAL_8N1);

    gps_serial.begin(115200, SERIAL_8N1, gps_rx, -1);

    //Initialize BME
    bme.begin();

    delay(1000);

    //Set the network ID to receive
    setNetID();

    delay(1000);

    xTaskCreatePinnedToCore (
        read_packets,     // Function to implement the task
        "receiver",   // Name of the task
        4096,      // Stack size in bytes
        NULL,      // Task input parameter
        0,         // Priority of the task
        NULL,      // Task handle.
        0          // Core where the task should run
    );

}


//HARDWARE FUNCTIONS

String sendCommand(const String& message) {
    String msg = message;
    int lenToSkip = 0;

    // 1. Send the message using write() to match Python's byte transmission
    // Calculate the length of the data being sent for echo stripping later
    if (message == "+++") {
        lenToSkip = message.length(); // Length of "+++" is 3
        // Write raw bytes (cast const char* to uint8_t* for compatibility)
        radio.write((const uint8_t*)msg.c_str(), lenToSkip);
        delay(1000);
    } else {
        msg += "\r\n";
        lenToSkip = msg.length(); // Length of message + "\r\n"
        radio.write((const uint8_t*)msg.c_str(), lenToSkip);
    }

    // 2. Wait for response to stabilize
    size_t lastSize = radio.available();
    delay(100);

    while (true) {
        size_t currentSize = radio.available();
        if (currentSize == lastSize) break;
        lastSize = currentSize;
        delay(50);
    }


    // Second, read the remaining bytes into the response string
    String response = "";
    while (radio.available()) {
        response += (char)radio.read();
    }

    return response;
}


//Sets the net ID and the frequencies depending on the currecnt state
void setNetID() {
    Serial.println("SETTING NET_ID");
    delay(1000);

    // Enter AT mode
    Serial.println(sendCommand("+++"));

    // Build command string
    String cmd = "";
    if (can_state == RECEIVE){cmd = "ATS3=" + String(TRANS_NET_ID);}
    else{cmd = "ATS3=" + String(REC_NET_ID);}
    Serial.println("Setting NETID...");
    Serial.println(sendCommand(cmd));

    if (can_state == RECEIVE){cmd = "ATS8=" + String(TRANS_FREQ[0]);}
    else{cmd = "ATS8=" + String(REC_FREQ[0]);}
    Serial.println("Setting MIN_FREQ...");
    Serial.println(sendCommand(cmd));
    
    if (can_state == RECEIVE){cmd = "ATS9=" + String(TRANS_FREQ[1]);}
    else{cmd = "ATS9=" + String(REC_FREQ[1]);}
    Serial.println("Setting MIN_FREQ...");
    Serial.println(sendCommand(cmd));

    // Save settings
    Serial.println("Saving...");
    Serial.println(sendCommand("AT&W"));

    // Reboot radio
    Serial.println("Rebooting...");
    Serial.println(sendCommand("ATZ"));
    delay(1000);
}

void read_sensors(){

  float temp, hum, pres;
  bme.read(pres, temp, hum, tempUnit, presUnit);

  debug_packet.payload.temperature = temp*100;
  debug_packet.payload.pressure = pres*100;

  if (gps.location.isValid())
  {  
    debug_packet.payload.gps[0] = gps.location.lng() * pow(10, 6);
    debug_packet.payload.gps[1] = gps.location.lat() * pow(10, 6);
    debug_packet.payload.height = gps.altitude.isValid() ? gps.altitude.meters() : 0;
    
    debug_packet.payload.velocity = gps.speed.isValid() ? gps.speed.mps()*100 : 0;
  }

}


//PACKET TRACKER FUNCTIONS
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


//CHECKSUM
uint16_t calculate_checksum(const uint8_t* data, size_t length) {
    uint8_t sum1 = 0;
    uint8_t sum2 = 0;
    for (size_t i = 0; i < length; ++i) {
        sum1 = (sum1 + data[i]) % 255;
        sum2 = (sum2 + sum1) % 255;
    }
    return (static_cast<uint16_t>(sum2) << 8) | sum1;
}


//PACKET FUNCTION
bool request_resend(){
    uint8_t count = PacketTracker_GetUnreceived(&tracker, resend_packet.buffer, MAX_RESEND_COUNT);
    // All packets received
    if (count == 0){
        return false;
    }
    Serial.print("\n Asking for retransmission of packets: ");
    Serial.println(count);
    resend_packet.header.length = header_length + 2*count + 2;

    last_packet_i = resend_packet.buffer[count-1];
    packets_seen_target = count;


    memcpy(transmit_buffer, &resend_packet.header, header_length);
    memcpy(transmit_buffer + header_length, resend_packet.buffer, count * sizeof(uint16_t));

    //Calculate and copy the checksum
    uint16_t checksum = calculate_checksum(transmit_buffer, resend_packet.header.length - 2);
    memcpy(transmit_buffer+resend_packet.header.length-2, &checksum, sizeof(uint16_t));

    send_packet(resend_packet.header.length);
    return true;

}

uint8_t temp[MAX_PACKET_SIZE];


void read_packets(void *parameters) {
    
    //Bytes parsed tracker
    uint8_t bytes_parsed = 0;

    //timeout tracker
    unsigned long t1 = millis();
    Serial.println("startiing packet parser");

    while (true) {
        if (pause_receiver){
            vTaskDelay(0.05);
            continue;
        }
        
        // Read bytes into the packet buffer
        uint16_t bytes_available = radio.available();
        
        if (bytes_available && receive_buffer.free()) {
            //Serial.println("Reading bytes");
            //Number of bytes to read
            uint8_t N = min((int)bytes_available, receive_buffer.free());
            
            //How many bytes were actually read
            size_t bytes_read = radio.readBytes(temp, N);
            if (bytes_read > 0) {
                receive_buffer.push(temp, bytes_read);  // Push all read bytes
            }

            //Reset timeout tracker
            t1 = millis();
            //Serial.print(bytes_available);
            //Serial.print(" ");
            //Serial.print(receive_buffer.free());
            //Serial.print(" ");
            //Serial.println(receive_buffer.available()); 
        }
        //In case last packet was corupted and the resend did not trigger a timeout is in place
        else{
            

            if ((millis() - t1) >= RESEND_TIMEOUT && is_first_packet == false){
                t1 = millis();
                request_resend();
            }
            vTaskDelay(0.001);
        }


        // State mashine to read packets
        switch (packet_state) {

            case SYNC: {
                // Wait for enough data
                if (receive_buffer.available() < 2) {continue;}


                uint16_t possibleHeader = (receive_buffer[0] << 8) | receive_buffer[1];
                bytes_parsed = 2;

                if (possibleHeader == GROUND_HEADER_ID) {
                    Serial.println("Started parsing packet");
                    packet_state = READ_HEADER;
                }
                else{
                    //Pop the first byte
                    receive_buffer.pop();
                    Serial.println("POPPING DATA");
                }

                Serial.print(bytes_available);
                Serial.print(" ");
                Serial.print(receive_buffer.free());
                Serial.print(" ");
                Serial.println(receive_buffer.available());
                break;

            }
            case READ_HEADER: {
                // Wait for enough data
                if (receive_buffer.available() < header_length) {continue;}

                Serial.println("Started parsing Header");
                data_packet.header.id = receive_buffer[bytes_parsed++];
                data_packet.header.length = receive_buffer[bytes_parsed++];

                // sanity check
                if (data_packet.header.length > MAX_PACKET_SIZE) {

                    Serial.print("Packet too long");
                    packet_state = SYNC;
                    receive_buffer.pop();
                    break;
                }

                packet_state = READ_CHECKSUM;
                break;
            }

            case READ_CHECKSUM: {
                // Wait for enough data
                if (receive_buffer.available() < data_packet.header.length) {continue;}

                Serial.println("Started parsing CHECKSUM");

                if (data_packet.header.id == DATA_ID){
                    // Parse payload
                    packets_seen += 1;
                    data_packet.payload.packet_count = (receive_buffer[bytes_parsed+1] << 8) | receive_buffer[bytes_parsed];
                    bytes_parsed+=2;
                    data_packet.payload.packet_i = (receive_buffer[bytes_parsed+1] << 8) | receive_buffer[bytes_parsed];
                    bytes_parsed+=2;

                    Serial.print("packet_i:");
                    Serial.print(data_packet.payload.packet_i);
                    

                }

                Serial.print(" packet_length:");
                Serial.println(data_packet.header.length);

                //Read data into the temp buffer
                receive_buffer.read(temp, data_packet.header.length);

                // I hate endians :)) (Don't touch, it works)
                uint16_t stored_checksum = (temp[data_packet.header.length - 1] << 8) | temp[data_packet.header.length - 2];
                uint16_t calc_checksum = calculate_checksum(temp, data_packet.header.length-2);

                Serial.print("stored:");
                Serial.println(stored_checksum);
                Serial.print("calc:");
                Serial.println(calc_checksum);
                if (stored_checksum == calc_checksum){
                    Serial.println("CHECKSUM MATCH");

                    switch (data_packet.header.id){
                        case DATA_ID:{
                            //Init the tracker system which i totally understand... some bitmaps and shii
                            if (is_first_packet){
                                is_first_packet = false;

                                //Set the finishing packet to be the last index
                                last_packet_i = data_packet.payload.packet_count-1;
                                packet_count = data_packet.payload.packet_count;
                                packets_seen_target = packet_count;
                            
                                if (!PacketTracker_Init(&tracker, data_packet.payload.packet_count)) {
                                    Serial.println("Failed to alocate tracker buffer");
                                    return; // Allocation failed
                                }
                            }
                            // Mark packet as received
                            PacketTracker_SetReceived(&tracker, data_packet.payload.packet_i);

                            //THE ENDIANS ARE CORRECT, DON'T TOUCH
                            //Change the header id
                            uint16_t new_header_id = htons(CAN_HEADER_ID);
                            memcpy(temp, &new_header_id, 2);

                            //Calculate and set the new checksum
                            uint16_t new_checksum = calculate_checksum(temp, data_packet.header.length-2);
                            memcpy(temp+data_packet.header.length-2, &new_checksum, 2);

                            //Store packet
                            memcpy(&storage_buffer[MAX_PACKET_SIZE*data_packet.payload.packet_i],
                                temp,
                                data_packet.header.length);
                            
                            Serial.write(temp, data_packet.header.length);
                            Serial.println("\n Finished parsing packet");

                            if (is_first_packet == false && (data_packet.payload.packet_i == last_packet_i || packets_seen == packets_seen_target)){
                                Serial.println("Read final packet");
                                packets_seen = 0;
                                //if no more packets need to be resent - start transmitting
                                if (!request_resend()){
                                    can_state = TRANSMIT;
                                }
                            }
                    
                
                            break;

                        }

                        case RESEND_ID:{

                            uint8_t resned_count = (data_packet.header.length - header_length - CHECKSUM_LENGTH) / 2;
                            uint16_t resend_packet_i;
                            
                            Serial.print("Putting packets into resend queue");
                            for (int i = 0; i < resned_count; i++){
                                //Read the resend packet index
                                resend_packet_i = (temp[header_length + 2*i + 1] << 8) | temp[header_length + 2*i];
                                Serial.print('[');
                                Serial.print(resend_packet_i);
                                Serial.println(']');
                                if (xQueueSend(resend_queue, &resend_packet_i, portMAX_DELAY) != pdTRUE) {
                                    Serial.println("Queue full :(");
                                }

                            }

                            break;

                        }
                    }

                    //Delete processed packet
                    receive_buffer.del(data_packet.header.length);
                    

                }
                else{
                    receive_buffer.pop();
                }
                packet_state = SYNC;
                bytes_parsed = 0;

            }   
            

        }
    }
}



void send_packet(uint8_t length){
    radio.flush();
    radio.write(transmit_buffer, length);
}


unsigned long debug_timer = millis();
// A non looping function which can be called to check it is time to debug and if so debug
void debug(){
    
    for(int i = 0; i < gps_serial.available(); i++){
      gps.encode(gps_serial.read());
    }
    uint32_t timestamp = millis();
    if (timestamp - debug_timer > DEBUG_DELAY){
        read_sensors();
        //Update the timestamp in the debug packet
        debug_packet.payload.timestamp = timestamp;
        memcpy(transmit_buffer, &debug_packet, debug_packet.header.length-2);
        uint16_t checksum = calculate_checksum(transmit_buffer, debug_packet.header.length-2);
        memcpy(transmit_buffer + (debug_packet.header.length - 2), &checksum, CHECKSUM_LENGTH);
        send_packet(debug_packet.header.length);
        debug_timer = timestamp;
    }
}


void transmit_data_packet(uint16_t i){
    
    Serial.print("Transmitting packet:");
    Serial.println(i);
    //Get packet length
    uint8_t packet_length = storage_buffer[i*MAX_PACKET_SIZE+length_byte_offset];

    //Copy to transmit buffer
    memcpy(transmit_buffer, storage_buffer+(i*MAX_PACKET_SIZE), packet_length);

    //Transmit packet
    send_packet(packet_length);
}

void transmit_loop()
{   
    //Pause the reading thread
    pause_receiver = true;

    //Reconfigure and restart the radio
    setNetID();

    //Resume the reading thread
    pause_receiver = false;


    //Transmit the data packets
    for (uint16_t i = 0; i < packet_count; i++){
        transmit_data_packet(i);
        debug();
        
    }
    can_state = RESEND;
}

void resend_loop(){
    uint16_t retransmit_i;
    while (true){
        if (xQueueReceive(resend_queue, &retransmit_i, 0) == pdTRUE) {
            transmit_data_packet(retransmit_i);
        }   
        debug();
    }

}

void loop() {
    switch (can_state){
        case RECEIVE:
            debug();
            break;
        case TRANSMIT:
            transmit_loop();
            break;
        case RESEND:
            resend_loop();


    }
}
