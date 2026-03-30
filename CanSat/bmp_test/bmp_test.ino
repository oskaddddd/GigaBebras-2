/***************************************************************************
  This is a library for the BME280 humidity, temperature & pressure sensor
  This example shows how to take Sensor Events instead of direct readings
  
  Designed specifically to work with the Adafruit BME280 Breakout
  ----> http://www.adafruit.com/products/2652

  These sensors use I2C or SPI to communicate, 2 or 4 pins are required
  to interface.

  Adafruit invests time and resources providing this open source code,
  please support Adafruit and open-source hardware by purchasing products
  from Adafruit!

  Written by Limor Fried & Kevin Townsend for Adafruit Industries.
  BSD license, all text above must be included in any redistribution
 ***************************************************************************/

#include <BME280I2C.h>
#include <Wire.h>

#define SERIAL_BAUD 115200

BME280I2C bme;

BME280::TempUnit tempUnit = BME280::TempUnit_Celsius;
BME280::PresUnit presUnit = BME280::PresUnit_Pa;

//////////////////////////////////////////////////////////////////
void setup()
{
  Serial.begin(SERIAL_BAUD);
  while (!Serial) {}

  Wire.begin();

  while (!bme.begin())
  {
    Serial.println("Could not find BME280 sensor!");
    delay(1000);
  }
}

void loop() {


  float temp, hum, pres;

  
  unsigned long a = millis();
  bme.read(pres, temp, hum, tempUnit, presUnit);
  

  // Now you can directly access and print the values
  Serial.println(millis()-a);
  //Serial.println(presUnit);
  Serial.print("Temp: ");
  Serial.print(temp);
  Serial.print("°C\t\t");
  Serial.print("Humidity: ");
  Serial.print(hum);
  Serial.print("% RH\t\t");
  Serial.print("Pressure: ");
  Serial.print(pres);
  Serial.println("Pa");

  delay(1000);
}