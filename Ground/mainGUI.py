from PyQt6.QtWidgets import *
from PyQt6.QtGui import QPainter, QLinearGradient, QBrush, QPixmap ,QColor, QFont
from PyQt6 import uic
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QVector3D

from pyqtgraph import PlotWidget
import pyqtgraph as pg
import pyqtgraph.opengl as gl

import sys
import numpy as np

import qdarktheme


import logging

import time
import json 

import ground_station as gs

from math import tan

import atexit

from serial.tools import list_ports as list_ports





logging.basicConfig(level=logging.DEBUG)



startBytes = [0x98, 0x98]
canID = 0xff

fullID = bytes([byte for byte in startBytes]+[canID])

TRANSMIT = 0
RECEIVE = 1
mode = TRANSMIT

update_frequency = 10

settings = {}

keep_data = True

with open('Ground/Assets/settings.json', 'r') as f:
    settings = json.load(f)
    
    
#print("Hello")
        
debug_manager = None
ground_station = None

serial_port = None
    
#2D plot widget
class dataPlotWidget(PlotWidget):
    
    
    def __init__(self, parent=None, background='default', plotItem=None, **kargs):
        super().__init__(parent, background, plotItem, **kargs)
        self.plotItem.showGrid(x=True, y=True, alpha=0.5)
        
        self.curve = pg.PlotDataItem(pen = pg.mkPen('g', ))
        self.addItem(self.curve)
        self.curve1 = pg.PlotDataItem(pen = pg.mkPen('r', ))
        self.addItem(self.curve1)
        self.markerLine = pg.InfiniteLine(pos=0, pen = pg.mkPen('r'))
        self.addItem(self.markerLine)
        
        self.setLabel("bottom", "seconds")
        
        #self.marker.__init__()
    def setAxis(self, dataName, axis = "left"):
        table = {"height": "m",
                 "wind": "m/s",
                 "velocity": "m/s",
                 "humidity":"%",
                 "temprature":"°C",
                 "pressure":"Pa"}
        self.setLabel(axis, table[dataName])
    def marker(self, x):
        self.markerLine.setPos(x)
        #self.plotItem.addLine(x = x, y=None,  pen=pg.mkPen('r', width=1))
    
#Time slider widget      
class timeSlider(QSlider):
    timeUpdated = pyqtSignal(int)
    def __init__(self, parent=None):
        super().__init__(parent),
        
class SliderManager():
    def __init__(self, slider:timeSlider):
        self.time = 0
        self.timeRange = 0
        
        print(debug_manager)
        
        if len(debug_manager.debug_data) != 0:
            self.time = debug_manager.debug_data[0]["timestamp"]
            self.timeRange = debug_manager.debug_data[0]["timestamp"] - debug_manager.debug_data[-1]["timestamp"]
        
        self.index = 0
        self.slider = slider
        self.slider.valueChanged.connect(self.updateSliderVal)
        self.slider.setMaximum(len(debug_manager.debug_data))
    #Called to update the slide object, when new data is recieved and timestamp range expands
    def updateTimerange(self):
        if not len(debug_manager.debug_data):
            logging.debug("Not updating time range, len(DataBase) = 0")
            return
        
        #Function to handle if slider is at a maximum
        def doMaximum():
            self.time = debug_manager.debug_data[0]["timestamp"]
            self.slider.blockSignals(True)
            self.slider.setValue(self.slider.maximum())
            self.slider.blockSignals(False)
            self.slider.timeUpdated.emit(0)
        
        logging.debug("Updating time range")
        #Calculate the timerange
        self.timeRange = debug_manager.debug_data[0]["timestamp"] - debug_manager.debug_data[len(debug_manager.debug_data)-1]["timestamp"]
        
        maximum = False
        #Check if slider is at the maximum and store it
        if self.slider.value() == self.slider.maximum():
            maximum = True
        
        #Extend the slider range to match the amount of data, with a max of 1000
        
        if len(debug_manager.debug_data) < 1000:
            self.slider.setMaximum(len(debug_manager.debug_data))
            
            if maximum:
                doMaximum()
                return
            
        else:
            if maximum:
                doMaximum()
                return
            if self.timeRange>= self.index+1:
                self.index+=1
                self.slider.timeUpdated.emit(self.index)
                
            self.slider.blockSignals(True)
            #Handle division by 0 case
            if self.timeRange == 0:
                self.slider.setValue(self.slider.maximum())
            #Calculate and set the value of the slider
            else:
                self.slider.setValue(round((self.time-debug_manager.debug_data[-1]["timestamp"])/self.timeRange*self.slider.maximum()))
            self.slider.blockSignals(False)
        
        #debug_manager.debug_data.bisect_left({"timestamp":100})
    
        
    #Called when the slider value is changed
    def updateSliderVal(self, value):
        if self.timeRange == 0:
            return
        
        expectedTime = (self.timeRange*value/self.slider.maximum()) + debug_manager.debug_data[-1]["timestamp"]
        self.index = debug_manager.debug_data.bisect_left({"timestamp":expectedTime })
        
        self.time = debug_manager.debug_data[self.index]["timestamp"]
        logging.debug(f"ratio:{value/self.slider.maximum()}\n-timerange:{self.timeRange}\n-expectedTime:{expectedTime}\n-TIME:{self.time}\n-Index:{self.index}\n-RangeLen:{len(debug_manager.debug_data)}")
        self.slider.timeUpdated.emit(self.index)
        
    
        
        
        
#3D plot widget for GPS
class gpsWidget(gl.GLViewWidget):
    def __init__(self, *args, devicePixelRatio=None, **kwargs):
        global debug_manager
        global ground_station
        
        super().__init__(*args, devicePixelRatio=devicePixelRatio, **kwargs)
        grid = gl.GLGridItem()
        grid.setSize(800, 800)
        grid.setSpacing(1, 1)
        self.addItem(grid)
        
        self.wind = gl.GLLinePlotItem(color = (0, 0, 255, 255), mode = "lines")
        self.addItem(self.wind)
        
        self.plot = gl.GLLinePlotItem(antialias = True, color = (255, 255, 255, 255), mode = 'line_strip')
        self.markerDot = gl.GLScatterPlotItem(pos = np.array([[0, 0, 0]]), size = 10, color = (255, 0, 0, 255))
        #self.markerDot.setData(pos = [[0, 0, 0]], size = 1, color = 'r')

        self.addItem(self.markerDot)
        

        self.addItem(self.plot)
    def paintGL(self):
        self.makeCurrent()
        super().paintGL()
        
    
    
class update_loop(QThread):
    signal = pyqtSignal()
    def __init__(self):
        super().__init__()
    def run(self):
        while 1:
            self.signal.emit()
            time.sleep(1/update_frequency)
            
class MainWindow1(QMainWindow):
    global settings
    global mode
    def __init__(self):
        #Init the UI
        super(MainWindow, self).__init__()
        self.ui = uic.loadUi('Ground/Assets/UI.ui', self)
    
class MainWindow(QMainWindow):
    def __init__(self):
        global debug_manager
        global ground_station
        #Init the UI
        super(MainWindow, self).__init__()
        self.ui = uic.loadUi('Ground/Assets/UI.ui', self)
        
        #Get the start time of the code to display packets/second graph 
        self.startTime = round(time.time())
        #Arrays for staring data for amount of packets recieved per second

        self.pens = [pg.mkPen(color = "w"), pg.mkPen(color = 'r'), pg.mkPen(color = 'b')]
                
        #self.ui.text_frame.setStyleSheet('background-color: rgb(50,50,50)')  

        if serial_port != None:
            if mode == TRANSMIT:
                ground_station = gs.transmitter(settings['trans_path'], serial_port)
            else:
                ground_station = gs.receiver(settings['rec_path'], serial_port)
                self.start_button.setEnabled(False)
            
            debug_manager = ground_station.debug_manager

            # Cocect start button to the start function 
            self.start_button.clicked.connect(ground_station.start)
        else:
            debug_manager = gs.debug_manager()
            
        #A list of all the timestamps recieved from the CanSat for the X axis of graphs 
        #(not related to starttime. Startime is local time, while timeline is as reported by cansat)
        self.timeline = np.array([])
        
        self.packet_plot_x = []
        self.packet_plot_in = []
        self.packet_plot_out = []
        
        if keep_data:
            with open('./assets/packet_data.json', 'r') as f:
                d = json.load(f)
                self.packet_plot_in = d['in']
                self.packet_plot_out = d["out"]
                self.packet_plot_x = d['x']
            
            
        if len(debug_manager.debug_dict) != 0:
            dialog = DeleteDialog()

            # Use exec_() to block here until the dialog is accepted/
            dialog.exec()
        
        
        #Connect the data selection dropdown to a function responsible for changing the data on the graph
        self.ui.dataDropdown.currentTextChanged.connect(self.dataDropboxChenged)
        self.dataType = "height"
        
        #self.ui.debugPlot.curve.pen = self.pens[1]
        self.ui.debugPlot.setLabel("left", "packets")
        
        self.valid_gps_index = 2
        for i in range(1, len(debug_manager.debug_data)):
            if debug_manager.debug_data[-i]["gps"][0] != 0:
                self.valid_gps_index = max(i, 2)
                break
            
        print(debug_manager)
        
        self.sliderManager = SliderManager(self.ui.timeSlider)
        
    
        
        

        #If data was not cleared, display it
        if len(debug_manager.debug_dict) != 0:
            self.updateData()

        
        self.ui.timeSlider.timeUpdated.connect(self.updateGraphMarkers)

        
        self.updater = update_loop()
        self.updater.signal.connect(self.updateData)
        self.updater.start()
        
    def store_data_on_exit(self):
        with open('./assets/packet_data.json', 'w') as f:
            d = {"in":self.packet_plot_in ,
                 "out":self.packet_plot_out,
                 "x":self.packet_plot_x}
            json.dump(d, f)

    
    def getProgress(self):
        if mode == TRANSMIT:
            return (ground_station.queue.qsize()*100)//len(ground_station.payloads)
        else:
            if ground_station.packet_count != -1:
                unreceived = len(ground_station.received_packet_tracker)
                total = ground_station.packet_count
                return (total-unreceived)*100//total
            else:
                return 0
        
        
    def updateGraphMarkers(self, index):
        dot = debug_manager.debug_data[index]
        if dot["gps"][0] != 0:
            gpsDot = np.array([[*dot["gps"], dot["height"]]], dtype=np.float32)
        else:
            gpsDot = np.array([[*debug_manager.debug_data[-self.valid_gps_index]["gps"], debug_manager.debug_data[-self.valid_gps_index]["height"]]], dtype=np.float32)
        gpsDot[0]-=np.array([*debug_manager.debug_data[0]["gps"], debug_manager.debug_data[0]["height"]])
        gpsDot[0, :2] /= 100
        gpsDot[0, 2] /= 10
        #print(gpsDot)
        self.ui.locationPlot.markerDot.setData(pos = gpsDot)
        
        self.ui.locationPlot.setCameraPosition(pos = QVector3D(*gpsDot[0]))
        self.ui.dataPlot.marker(self.sliderManager.time/1000)
        #self.ui.debugPlot.marker(self.sliderManager.time/1000)
        
        
        
    def updateGpsPlot(self):
        
        #Extract gps and height data into a np array
        
        gps = debug_manager.extraxtData("gps", np.float32)
        
        
        

        #Ignore the invalid gps data
        if len(gps) != 0 and gps[0][0] == 0:
            self.valid_gps_index = max(len(gps)-1, 2)
            return
        
        height = debug_manager.extraxtData("height", np.float32)
        
        result = np.column_stack((gps[:-self.valid_gps_index+1], height[:-self.valid_gps_index+1]))
        
        
        #Normalise the data
        if len(gps) != 0 and len(height) != 0:
            for i in range(3):
                #Normalise so that the canSat is always at (0;0)
                result[:, i] -= result[0][i]
            
            #Gps returned with 6 digits after decimal (as an int *10^6)
            #6 dec - 0.11m; 5 dec - 1.1m; 4 dec - 11m...
            #So gps devided by 100, 1 unit = 11m
            result[:, :2] /= 100
            
            #Height devided by 10, so 1 unit = 10 meters
            result[:, 2] /= 10

            #Plot the data
            self.ui.locationPlot.plot.setData(pos = result, width = 4.0)
            
        #Calculate wind 
        arrowLength = 10
        deltaTimes = self.timeline[self.valid_gps_index:]+self.timeline[self.valid_gps_index-1:-1]
        
        gpsDifference = gps[0:-self.valid_gps_index] - gps[1:-self.valid_gps_index+1]
        gpsDifference = gpsDifference[:, :]/(deltaTimes[:, np.newaxis]/0.11/arrowLength)
        
        wind_data = np.empty(((result.shape[0]-1)*2, 3))
        wind_data[0::2] = result[1:]
        wind_data[1::2] = result[1:]
        wind_data[1::2, :2] += gpsDifference
        
        print(gpsDifference)
        
        self.ui.locationPlot.wind.setData(pos = wind_data)
        #self.updateGraphMarkers(self.sliderManager.index)
            
   
    
    #Handles ploting when new data is recieved      
    def updateData(self):
        print(self.valid_gps_index)
        self.sliderManager.updateTimerange()


        if ground_station and ground_station.start_time != 0:
            relative_time = time.time()-ground_station.start_time
            
            # Set the time elapsed value
            self.time_label.setText(f"{round(relative_time, 1)} s")
            
            # Set the resend ratio
            ratio = ground_station.packets_resent*100 // ground_station.packet_count
            self.resend_label.setText(f'{ratio} %')
            
            #Set the progress bar
            progress = self.getProgress()
            self.progressBar.setValue(progress)
            
            update_packet_plot = False
            
            in_data = ground_station.packets_received
            out_data = ground_station.packets_sent
            
            if len(self.packet_plot_x) != 0:
                in_data -= self.packet_plot_in[-1]
                out_data -= self.packet_plot_out[-1]
            
            
            # If the plot is empty or data has changed or
            # If the plot has only 1 point or the last 2 points are not the same 
            # Then add a point of the same value at a current timestamp 
            if  len(self.packet_plot_x) == 0 or\
                self.packet_plot_in[-1] != in_data or self.packet_plot_out[-1] != out_data or \
                len(self.packet_plot_x) == 1 or self.packet_plot_in[-2] != self.packet_plot_in[-1] or self.packet_plot_out[-2] != self.packet_plot_out[-1]:
                
                
                #Add the data
                self.packet_plot_in.append(in_data)
                self.packet_plot_out.append(out_data)
                self.packet_plot_x.append(round(relative_time, 2))
            # The data has not chnaged, so move the latest data point to the current timestamp
            else:
                self.packet_plot_x[-1] = round(relative_time, 2)
                
            self.debugPlot.curve1.setData(x = np.array(self.packet_plot_x), y = np.array(self.packet_plot_out))
            self.debugPlot.curve.setData(x = np.array(self.packet_plot_x), y = np.array(self.packet_plot_in))
                
                    
                    
                    
                    
                
                
        
        #Update the gps plot
        self.timeline = debug_manager.extraxtData("timestamp")[:]/1000
                
                
        match self.dataType:
            case "acceleration" | "magneticField" | "angVelocity":
                #dat = DataManager.extraxtData(self.dataType, np.float32)
                #magnitudes = np.linalg.norm(dat, axis=1)
                #print("dat", dat, "\nmag:", magnitudes)
                self.ui.dataPlot.curve.setData(\
                    x = self.timeline,\
                    y = np.linalg.norm(debug_manager.extraxtData(self.dataType, np.float32), axis=1)\
                )

            case "wind":
                gpsData = debug_manager.extraxtData("gps", np.float32)
                print(gpsData[:-self.valid_gps_index].shape, gpsData[:-self.valid_gps_index+1].shape)
                
                deltaTimes = self.timeline[self.valid_gps_index:]+self.timeline[self.valid_gps_index-1:-1]
                gpsDifference = gpsData[0:-self.valid_gps_index] - gpsData[1:-self.valid_gps_index+1]
                print(gpsDifference)
                
                self.ui.dataPlot.curve.setData(\
                    x = self.timeline[:-self.valid_gps_index],\
                    y = (np.linalg.norm(gpsDifference, axis=1)*0.11)/deltaTimes\
                )
                
            case _:
                self.ui.dataPlot.curve.setData(\
                    x = self.timeline, \
                    y = debug_manager.extraxtData(self.dataType, np.float32)\
                )

                
                
                #Update the entire timeline (x axis of graphs displaying CanSat data)
    
    
                #Clear the data plot and draw a new graph with the updated data
                
        self.updateGpsPlot()

        #Plot the {packets per second} graphs
        #self.ui.debugPlot.curve1.setData(x = list(range(tStamp+1)), y = self.debugPlotDebug, pen = self.pens[0])
        #self.ui.debugPlot.plot(list(range(tStamp+1)), self.debugPlotDebug, pen = self.pens[1])
        #self.ui.debugPlot.marker(self.ui.timeSlider.time/1000)
    
        
    #Fucntion handling the change of the data type selection dropdown
    def dataDropboxChenged(self, text):
        self.dataType = text
        self.ui.dataPlot.setAxis(self.dataType)
        self.updateData()

        self.ui.dataPlot.centerOn(self.ui.dataPlot.curve)
        self.ui.dataPlot.plotItem.enableAutoRange('xy', True)
        self.ui.dataPlot.plotItem.autoRange()
        
class DeleteDialog(QDialog):
    def __init__(self):
        #Init the UI
        super(DeleteDialog, self).__init__()
        self.ui = uic.loadUi('Ground/Assets/delete_dialog.ui', self)
        
    def keep(self):
        self.accept()
        
    def delete(self):
        
        global debug_manager
        
        debug_manager.debug_dict = []
        debug_manager.debug_data = gs.SortedList(debug_manager.debug_dict, key=lambda x: -x['timestamp'])
        self.accept()
        
class StartupDialog(QDialog):
    def __init__(self):
        #Init the UI
        super(StartupDialog, self).__init__()
        self.ui = uic.loadUi('Ground/Assets/dialog.ui', self)
        
        # Connect both buttons to the same slot
        self.trans_button.toggled.connect(self.handle_toggle)
        self.rec_button.toggled.connect(self.handle_toggle)
        
        self.file_button.clicked.connect(self.handle_browse)
        
        self.buttonBox.accepted.connect(self.finish)
        self.buttonBox.rejected.connect(exit)
        
        self.path_input.setText('/select transmitter or receiver')
        
        serial_names = []
        for port in list_ports.comports():
            if port.description != "n/a": serial_names.append(port.name)
        serial_names.append("None")
        self.serial_box.addItems(serial_names)
        
        
    def finish(self):
        global serial_port
        serial_port = str(self.serial_box.currentText())
        if serial_port == "None": serial_port = None
        if mode != None:
            with open('Ground/Assets/settings.json', 'w') as f:
                json.dump(settings, f)
                
            
    def handle_toggle(self, checked):
        global mode
        # Determine which sender triggered the signal
        sender = self.sender()
        self.path_input.setEnabled(True)
        self.file_button.setEnabled(True)
        
        if checked:
            if sender == self.trans_button:
                self.rec_button.setChecked(False) # Untoggle the other button
                mode = TRANSMIT
                self.path_input.setText(settings['trans_path'])
            elif sender == self.rec_button:
                self.trans_button.setChecked(False) # Untoggle the other button
                mode = RECEIVE
                self.path_input.setText(settings['rec_path'])

            print(f"Mode changed to: {mode}")
    
    def handle_browse(self):
        global settings
        # Check which mode is active and open the appropriate dialog
        if self.trans_button.isChecked():
            # Open a dialog to select a file
            file_path, _ = QFileDialog.getOpenFileName(self, "Select File to Transmit")
            if file_path:
                self.path_input.setText(file_path)
                settings['trans_path'] = file_path

        elif self.rec_button.isChecked():
            # Open a dialog to select a directory
            dir_path = QFileDialog.getExistingDirectory(self, "Select Receive Directory")
            if dir_path:
                self.path_input.setText(dir_path)
                settings['rec_path'] = dir_path
                

        


    
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    #qdarktheme.setup_theme()

    dialog = StartupDialog()

    # Use exec_() to block here until the dialog is accepted/
    dialog.exec()
    if dialog.accepted:


        window = MainWindow()
        window.show()
        app.exec()
        #print(1)
        #window = MainWindow()
        #window.show()