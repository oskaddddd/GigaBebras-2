#include <Arduino.h>
#include "FS.h"
#include "LittleFS.h"
#include <Wire.h>


//Constants
#define HEADER_ID 0xf24f
#define DEBUG_ID 0xef
#define DATA_ID 0x24
//Network Ids that radios will use
uint8_t net_ids[2] = {73, 42};

//Pins
#define radio_rx 16
#define radio_tx 17
#define gps_rx 4


//9DOF
#include <ICM20948_WE.h>
#define ICM20948_ADDR 0x68
ICM20948_WE IMU = ICM20948_WE(ICM20948_ADDR);

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


#pragma pack(push, 1) 
//struct for the packet header
struct packet_header {
  uint16_t header_id = HEADER_ID; 
  uint8_t id {};         
  uint8_t length {};
};
//struct for the data payload
struct data_payload {
    uint8_t packet_count {};
    uint8_t packet_i {};
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
}
struct debug_packet_struct {
    packet_header header;
    debug_payload payload;
}
#pragma pack(pop)

debug_packet_struct debug_packet;
debug_packet.header.id = DEBUG_ID;

data_packet_struct data_packet;
data_packet.header.id = DATA_ID;

File packet_storage;

uint8_t can_state = RECEIVE;
uint8_t packet_state = SYNC




uint8_t buffer[70];

const uint32_t FLUSH_INTERVAL_MS = 1000;

//Define serials
HardwareSerial& radio = Serial2;
HardwareSerial& gps   = Serial1;

uint8_t transmission_rate = 20; //hz
uint8_t debug_delay = 2; //s


void setup() {
  Serial.begin(115200);
  Wire.begin();
  delay(500);

  initIMU();
  bme.begin()
  
  // Configure Serial coms
  radio.begin(57600, SERIAL_8N1, radio_rx, radio_tx);
  gps.begin(115200, SERIAL_8N1, gps_rx, -1);
  setNetID(net_ids[0]);
  initStorage();





}

void initIMU(){
  if(!IMU.init()){
    Serial.println("ICM20948 does not respond");
  }
  else{
    Serial.println("ICM20948 is connected");

  }

  if(!myIMU.initMagnetometer()){
    Serial.println("Magnetometer does not respond");
  }
  else{
    Serial.println("Magnetometer is connected");
  }

  if (calibrate){
    Serial.println("Position your ICM20948 flat and don't move it - calibrating...");
    delay(1000);
    myIMU.autoOffsets();
    Serial.println("Done!"); 
  }

  myIMU.setAccRange(ICM20948_ACC_RANGE_2G);
  myIMU.setAccDLPF(ICM20948_DLPF_6);


  IMU.setGyrRange(ICM20948_GYRO_RANGE_250);
  IMU.setGyrDLPF(ICM20948_DLPF_6);

  IMU.setMagOpMode(AK09916_CONT_MODE_20HZ);

}

bool initStorage() {
    if (!LittleFS.begin(true)) {
        Serial.println("LittleFS mount failed");
        return false;
    }

    dataFile = LittleFS.open("/packets.bin", FILE_APPEND);

    if (!dataFile) {
        Serial.println("Failed to open file");
        return false;
    }

    return true;
}



unsigned long lastFlush = 0;
void appendPacketToFile(const uint8_t* buffer, uint8_t length) {
    size_t written = dataFile.write(buffer, length);

    if (written != length) {
        Serial.println("Write failed!");
    }

    if (millis() - lastFlush > FLUSH_INTERVAL_MS) {
        dataFile.flush();
        lastFlush = millis();
    }
}

void read_packets() {
    while (true) {
        

        uint8_t byte = radio.read();

        switch (state) {

            case SYNC:
                buffer[0] = buffer[1];
                buffer[1] = byte;

                uint16_t possibleHeader = (buffer[0] << 8) | buffer[1];

                if (possibleHeader == EXPECTED_HEADER_ID) {
                    header.header_id = possibleHeader;
                    bytesRead = 2;
                    state = READ_HEADER;
                }
                break;

            case READ_HEADER:
                buffer[bytesRead++] = byte;

                if (bytesRead == 4) {
                    header.id = buffer[2];
                    header.length = buffer[3];

                    // sanity check
                    if (header.length > 64) {
                        state = SYNC;
                        break;
                    }

                    state = READ_PAYLOAD;
                }
                break;

            case READ_PAYLOAD:
                buffer[bytesRead++] = byte;

                if (bytesRead == header.length) {

                    // Parse payload
                    uint8_t index = 4;

                    packet.header = header;

                    packet.packet_count = buffer[index++];
                    packet.packet_i = buffer[index++];
                    

                    if (payload.packet_count == payload.packet_i){
                        can_state = TRANSMIT;
                        dataFile.flush();
                        setNetID(net_ids[1])

                        break;

                    }

                    // Reset
                    state = SYNC;
                    bytesRead = 0;
                    
                }
                break;
        }
    }
}

// Change this to your desired NETID


String sendCommand(const uint message) {
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

void appendPacket(const Packet& pkt) {
    File file = LittleFS.open("/data.bin", FILE_APPEND);

    if (!file) {
        Serial.println("Failed to open file");
        return;
    }

    file.write(pkt.data.payload); // adjust if payload is larger
    file.close();
}

void read_sensors(){
  xyzFloat gValue;
  xyzFloat gyr;
  xyzFloat magValue;
  
  IMU.readSensor();
  IMU.getGValues(&gValue);
  IMU.getGyrValues(&gyr);
  IMU.getMagValues(&magValue);

  debug_packet.payload.acceleration[0] = gValue.x*100
  debug_packet.payload.acceleration[1] = gValue.y*100
  debug_packet.payload.acceleration[2] = gValue.z*100

  debug_packet.payload.angVelocity[0] = gyr.x*100
  debug_packet.payload.angVelocity[1] = gyr.y*100
  debug_packet.payload.angVelocity[2] = gyr.z*100

  debug_packet.payload.magneticField[0] = magValue.x*100
  debug_packet.payload.magneticField[1] = magValue.y*100
  debug_packet.payload.magneticField[2] = magValue.z*100

  float temp, hum, pres;
  bme.read(pres, temp, hum, tempUnit, presUnit);

  debug_packet.payload.temperature = temp*100;
  debug_packet.payload.pressure = temp*100;

}


void make_debug_packet()
{

}

void transmit_packets()
{
    while
}


void loop() {

  switch (state){
    case RECEIVE:
      read_packets();
      break;
    case TRANSMIT:
      transmit_packets();

  }
}