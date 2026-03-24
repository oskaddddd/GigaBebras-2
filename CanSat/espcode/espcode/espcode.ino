
//Stuct for the packet header
#pragma pack(push, 1) 
struct packet_header {
  uint16_t header_id = 0x3253; 
  uint8_t id = 0xff;         
  uint8_t length {};
};
#pragma pack(pop)

const uint8_t RECEIVE = 0
const uint8_t TRANSMIT = 1

uint8_t state = RECEIVE

void setup() {
  Serial.begin(115200);
  esp_chip_info_t chip_info;
  esp_chip_info(&chip_info);
  printf("Chip Model: ESP32-%s\n", (chip_info.model == CHIP_ESP32) ? "D0WD" : "other");
  printf("Cores: %d\n", chip_info.cores);
  printf("Flash Size: 4MB (assumed from board config)\n");
}


void loop() {

  swith
}
